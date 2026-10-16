"""模块 6 管理接口：身份、配置、人工审核、任务及运行证据。"""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import tenant_config
from app.core.request_audit import spool_root
from app.core.security import Permission
from app.core.tenant import bypass_tenant_filter
from app.core.timeutil import as_utc_naive
from app.core.versions import prompt_versions, workflow_versions
from app.db.session import get_db
from app.deps import get_current_user, require_permissions
from app.models.audit import AuditLog
from app.models.governance import ConfigRevision, DurableJob, HumanReview, ModelUsage
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.governance import (
    JobCreate,
    OrgCreate,
    OrgUpdate,
    ReviewDecision,
    ReviewSubmit,
    TenantCreate,
    TenantUpdate,
    UserUpdate,
)
from app.services.governance_service import GovernanceUpdate, read_governance, save_governance
from app.services.identity_service import IdentityService, is_platform_admin, public_record
from app.services.job_service import enqueue
from app.services.review_service import ReviewService
from app.services.run_log_service import (
    RUN_EVENTS,
    RUN_KINDS,
    RunLogFilters,
    count_run_logs,
    fetch_run_logs,
)
from app.services.version_trail_service import (
    PROMPT_DEFAULTS,
    count_knowledge_revisions,
    fetch_knowledge_revisions,
    knowledge_scope_note,
    prompt_scope_note,
    prompt_version_history,
)

router = APIRouter()
identity_admin = require_permissions(Permission.IDENTITY_MANAGE)
config_admin = require_permissions(Permission.CONFIG_MANAGE)
review_user = require_permissions(Permission.REVIEW_MANAGE)
ops_admin = require_permissions(Permission.OPS_QUERY)
# 版本留痕属治理与审计证据（与问答记录、审计查询同一枚权限）：能查"谁问了什么"的人，
# 才需要能查"这条答案由哪个版本产出"。
audit_admin = require_permissions(Permission.AUDIT_QUERY)


def response(request: Request, data: object) -> APIResponse:
    return APIResponse(
        data=jsonable_encoder(data), trace_id=getattr(request.state, "trace_id", None)
    )


async def changed(
    db: AsyncSession,
    request: Request,
    user: User,
    row: User | OrgUnit | Tenant,
    action: str,
    kind: str,
) -> APIResponse:
    try:
        data = public_record(row)
        await audit_operation(
            db,
            request,
            user,
            action=action,
            resource_type=kind,
            resource_id=str(row.id),
            new_value=data,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "登记信息与现有记录冲突") from None
    return response(request, data)


@router.get("/admin/tenants")
async def tenants(
    request: Request, user: User = Depends(identity_admin), db: AsyncSession = Depends(get_db)
) -> APIResponse[dict[str, Any]]:
    return response(request, {"items": await IdentityService(db, user).list_tenants()})


@router.post("/admin/tenants")
async def create_tenant(
    body: TenantCreate,
    request: Request,
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await IdentityService(db, user).create_tenant(body.model_dump())
    return await changed(db, request, user, row, "create", "tenant")


@router.patch("/admin/tenants/{record_id}")
async def update_tenant(
    record_id: str,
    body: TenantUpdate,
    request: Request,
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await IdentityService(db, user).update_tenant(
        record_id, body.model_dump(exclude_unset=True)
    )
    return await changed(db, request, user, row, "update", "tenant")


@router.get("/admin/organizations")
async def organizations(
    request: Request,
    tenant_id: str | None = Query(None, max_length=36),
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    return response(
        request,
        {"items": [public_record(row) for row in await IdentityService(db, user).orgs(tenant_id)]},
    )


@router.post("/admin/organizations")
async def create_organization(
    body: OrgCreate,
    request: Request,
    tenant_id: str | None = Query(None, max_length=36),
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await IdentityService(db, user).save_org(tenant_id, body.model_dump())
    return await changed(db, request, user, row, "create", "organization")


@router.patch("/admin/organizations/{record_id}")
async def update_organization(
    record_id: str,
    body: OrgUpdate,
    request: Request,
    tenant_id: str | None = Query(None, max_length=36),
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await IdentityService(db, user).save_org(
        tenant_id, body.model_dump(exclude_unset=True), record_id
    )
    return await changed(db, request, user, row, "update", "organization")


# 开户（POST /admin/users）由平台系统管理员专用接口承担（app/api/v1/admin.py）。
# 治理侧刻意不注册同方法+同路径：重复注册会按 include_router 顺序静默遮蔽其中一方，
# 这里只保留学校管理员（IDENTITY_MANAGE）可用的读取与维护。
@router.get("/admin/users")
async def users(
    request: Request,
    tenant_id: str | None = Query(None, max_length=36),
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    return response(
        request,
        {"items": [public_record(row) for row in await IdentityService(db, user).users(tenant_id)]},
    )


@router.patch("/admin/users/{record_id}")
async def update_user(
    record_id: str,
    body: UserUpdate,
    request: Request,
    tenant_id: str | None = Query(None, max_length=36),
    user: User = Depends(identity_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await IdentityService(db, user).save_user(
        tenant_id, body.model_dump(exclude_unset=True), record_id
    )
    return await changed(db, request, user, row, "update", "user")


@router.get("/admin/governance")
async def governance(
    request: Request, user: User = Depends(config_admin), db: AsyncSession = Depends(get_db)
) -> APIResponse[dict[str, Any]]:
    return response(request, await read_governance(db, user))


@router.patch("/admin/governance")
async def update_governance(
    body: GovernanceUpdate,
    request: Request,
    user: User = Depends(config_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    data = await save_governance(db, user, body)
    await audit_operation(
        db,
        request,
        user,
        action="config_update",
        resource_type="governance",
        resource_id=str(user.tenant_id),
        # 键名用 ``config_version``：它属于审计摘要白名单里的"不可变版本指针"，
        # 写 ``version`` 会被统一脱敏成 sha256，留痕反而读不出第几个版本。
        new_value={"config_version": data["version"]},
    )
    await db.commit()
    return response(request, data)


@router.get("/admin/config-history")
async def config_history(
    request: Request,
    page: int = Query(1, ge=1),
    user: User = Depends(config_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(ConfigRevision)
                .where(ConfigRevision.tenant_id == str(user.tenant_id))
                .order_by(ConfigRevision.version.desc())
                .offset((page - 1) * 20)
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return response(
        request,
        {
            "items": [
                {
                    key: getattr(row, key)
                    for key in ("version", "actor_id", "reason", "created_at", "values")
                }
                for row in rows
            ],
            "page": page,
        },
    )


@router.get("/admin/reviews")
async def reviews(
    request: Request,
    page: int = Query(1, ge=1),
    status: Literal["pending", "approved", "returned"] | None = None,
    user: User = Depends(review_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    items = await ReviewService(db, user).visible_reviews()
    if status:
        items = [item for item in items if item["effective_status"] == status]
    start = (page - 1) * 40
    return response(
        request,
        {
            "items": items[start : start + 40],
            "page": page,
            "has_more": len(items) > start + 40,
            "total": len(items),
        },
    )


@router.post("/admin/reviews")
async def submit_review(
    body: ReviewSubmit,
    request: Request,
    user: User = Depends(review_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    service = ReviewService(db, user)
    row = await service.submit(body)
    await audit_operation(
        db,
        request,
        user,
        action="review_submit",
        resource_type="human_review",
        resource_id=str(row.id),
        data_level="sensitive",
        new_value={"source_version": row.source_version},
    )
    await db.commit()
    return response(request, await service.view(row))


@router.get("/admin/reviews/{record_id}")
async def review_detail(
    record_id: str,
    request: Request,
    user: User = Depends(review_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = (
        await db.execute(
            select(HumanReview).where(
                HumanReview.id == record_id, HumanReview.tenant_id == str(user.tenant_id)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "审核记录不存在")
    return response(request, await ReviewService(db, user).view(row, include_content=True))


@router.post("/admin/reviews/{record_id}/decision")
async def review_decision(
    record_id: str,
    body: ReviewDecision,
    request: Request,
    user: User = Depends(review_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    service = ReviewService(db, user)
    row = await service.decide(record_id, body)
    await audit_operation(
        db,
        request,
        user,
        action="review_decision",
        resource_type="human_review",
        resource_id=str(row.id),
        data_level="sensitive",
        new_value={"status": row.status, "source_version": row.source_version},
    )
    await db.commit()
    return response(request, await service.view(row))


def job_view(row: DurableJob) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "kind",
            "status",
            "attempts",
            "max_attempts",
            "available_at",
            "lease_until",
            "created_at",
            "finished_at",
            "error_code",
            "result",
        )
    }


@router.post("/admin/jobs")
async def create_job(
    body: JobCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    row = await enqueue(db, user, body)
    await audit_operation(
        db,
        request,
        user,
        action="job_enqueue",
        resource_type="job",
        resource_id=str(row.id),
        new_value={"kind": row.kind},
    )
    await db.commit()
    return response(request, job_view(row))


@router.get("/admin/jobs")
async def jobs(
    request: Request,
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    stmt = select(DurableJob).where(
        DurableJob.tenant_id == str(user.tenant_id),
        DurableJob.actor_id == str(user.id),
        DurableJob.is_deleted.is_(False),
    )
    rows = (
        (
            await db.execute(
                stmt.order_by(DurableJob.created_at.desc(), DurableJob.id)
                .offset((page - 1) * 40)
                .limit(40)
            )
        )
        .scalars()
        .all()
    )
    return response(request, {"items": [job_view(row) for row in rows], "page": page})


@router.get("/admin/run-logs")
async def run_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    event: Optional[str] = Query(
        None, description="按事件筛选（任务入队 / 执行完成 / 执行失败 / 定时扫描）"
    ),
    kind: Optional[str] = Query(None, description="按任务类型筛选（以任务表为准）"),
    result: Optional[str] = Query(
        None, pattern="^(success|failed|denied)$", description="按结果筛选"
    ),
    start_at: Optional[datetime] = Query(
        None, description="起始时间（含；北京时间输入，如 2026-10-16T09:00:00+08:00）"
    ),
    end_at: Optional[datetime] = Query(None, description="结束时间（含；北京时间输入）"),
    user: User = Depends(ops_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    """工作流运行日志（T-SYS-06E）：任务生命周期与定时扫描，从审计轨迹派生。

    与「任务台账」的分工：台账是**我提交的任务现在什么状态**（按提交人可见），运行日志是
    **这个租户最近实际跑了什么、失败在哪一步**（`admin.ops`，租户内可见）。
    """
    if event and event not in RUN_EVENTS:
        raise HTTPException(422, "未知的运行事件")
    if kind and kind not in RUN_KINDS:
        raise HTTPException(422, "未知的任务类型")
    start, end = as_utc_naive(start_at), as_utc_naive(end_at)
    if start and end and start > end:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    filters = RunLogFilters(
        tenant_id=str(user.tenant_id),
        event=event,
        kind=kind,
        result=result,
        start_at=start,
        end_at=end,
    )
    total = await count_run_logs(db, filters)
    rows = await fetch_run_logs(db, filters, offset=(page - 1) * page_size, limit=page_size)
    return response(
        request,
        {
            "items": [asdict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "scope_note": filters.scope_note(),
        },
    )


@router.get("/admin/version-trail")
async def version_trail(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(audit_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    """版本留痕（SEC-11 / T-SEC-11）：提示词 / 工作流 / 知识库三个版本的可查记录。

    与 `/admin/config-history` 的分工：那边是**配置管理**视角（整份配置的历史，权限
    `config.manage`）；这边是**留痕**视角——只挑出版本变化，并回答"这条答案由哪个版本
    产出"（权限 `admin.audit`，与其他治理审计证据同一枚）。三块来源各自权威，不另立登记表：

    - 提示词：租户配置版本表（谁、何时、为什么改）；
    - 工作流：代码里的契约版本（只给现行值，变更历史在代码与发布记录）；
    - 知识库：条目入库与内容更新的审计（修订号在审计白名单里可读）。
    """
    tenant_id = str(user.tenant_id)
    history = await prompt_version_history(db, tenant_id)
    total = await count_knowledge_revisions(db, tenant_id)
    revisions = await fetch_knowledge_revisions(
        db, tenant_id, offset=(page - 1) * page_size, limit=page_size
    )
    return response(
        request,
        {
            "prompt": {
                "current": prompt_versions(tenant_id),
                "defaults": dict(PROMPT_DEFAULTS),
                "history": [asdict(entry) for entry in history],
                "scope_note": prompt_scope_note(tenant_id, len(history)),
            },
            "workflow": {
                "items": workflow_versions(),
                "scope_note": (
                    "工作流契约版本来自代码常量（app/schemas/wf.py）：契约变更才升版本；"
                    "它的变更历史在代码与发布记录里，数据库不另存一份，这里也不编造"
                ),
            },
            "knowledge": {
                "items": [asdict(row) for row in revisions],
                "total": total,
                "page": page,
                "page_size": page_size,
                "scope_note": knowledge_scope_note(tenant_id),
            },
        },
    )


@router.get("/admin/operations")
async def operations(
    request: Request, user: User = Depends(ops_admin), db: AsyncSession = Depends(get_db)
) -> APIResponse[dict[str, Any]]:
    tid, since = str(user.tenant_id), datetime.utcnow() - timedelta(hours=24)

    async def counts(model: type[DurableJob], *conditions: Any) -> dict[str, int]:
        rows = (
            await db.execute(
                select(model.status, func.count())
                .where(model.tenant_id == tid, *conditions)
                .group_by(model.status)
            )
        ).all()
        return {key: value for key, value in rows}

    usage = (
        await db.execute(
            select(
                ModelUsage.model_type,
                ModelUsage.result,
                func.count(),
                func.avg(ModelUsage.duration_seconds),
            )
            .where(ModelUsage.tenant_id == tid, ModelUsage.created_at >= since)
            .group_by(ModelUsage.model_type, ModelUsage.result)
        )
    ).all()
    platform = await is_platform_admin(db, user)
    event_scope = AuditLog.tenant_id.in_([tid, "unauthenticated"] if platform else [tid])
    with bypass_tenant_filter():
        events = (
            await db.execute(
                select(AuditLog.action, AuditLog.result, func.count())
                .where(event_scope, AuditLog.created_at >= since)
                .group_by(AuditLog.action, AuditLog.result)
            )
        ).all()
    alerts = [
        {"action": action, "result": result, "count": count, "window_hours": 24}
        for action, result, count in events
        if (result == "denied" and count >= 5)
        or (action == "login" and result in {"failed", "denied"} and count >= 5)
        or (action == "export" and count >= 50)
    ]
    await tenant_config.load(db, tid)
    review_counts: dict[str, int] = {}
    for item in await ReviewService(db, user).visible_reviews():
        state = item["effective_status"]
        review_counts[state] = review_counts.get(state, 0) + 1
    return response(
        request,
        {
            "jobs": await counts(DurableJob),
            "reviews": review_counts,
            "model_usage": [
                {"type": kind, "result": result, "calls": count, "mean_seconds": duration}
                for kind, result, count, duration in usage
            ],
            "request_usage": [
                {"action": action, "result": result, "count": count}
                for action, result, count in events
            ],
            "alerts": alerts,
            "audit_spool_pending": len(list(spool_root().glob("*.audit"))),
            "admission": (await read_governance(db, user))["admission"],
        },
    )


@router.get("/admin/metrics")
async def metrics(user: User = Depends(ops_admin), db: AsyncSession = Depends(get_db)) -> Response:
    # Prometheus 是进程级指标，只允许系统管理员，学校查看自己的持久使用量。
    if not await is_platform_admin(db, user):
        raise HTTPException(403, "仅系统管理员可读取进程指标")
    return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
