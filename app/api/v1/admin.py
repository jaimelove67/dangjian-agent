"""当前租户的账号创建、持久配置和只追加审计日志。"""

from contextlib import nullcontext
from datetime import datetime
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.audit import audit_operation
from app.core.audit import ANONYMOUS_TENANT, AuditQuery, audit_view
from app.core.config import tenant_config
from app.core.constants import DataLevel
from app.core.security import Permission, hash_password
from app.core.tenant import bypass_tenant_filter
from app.core.timeutil import as_utc_naive
from app.db.session import get_db
from app.deps import require_permissions, require_roles
from app.models.audit import AuditLog
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.schemas.admin import AccountCreated, AccountCreateRequest, AccountOrgOption, AccountOrgType
from app.schemas.auth import UserInfo
from app.schemas.common import APIResponse, ErrorCode
from app.services.audit_export import MAX_EXPORT_ROWS, build_audit_package
from app.services.identity_service import IdentityService, is_platform_admin
from app.services.org_scope import accessible_org_units

router = APIRouter()
_require_config = require_permissions(Permission.CONFIG_MANAGE)
_require_audit = require_permissions(Permission.AUDIT_QUERY)
_require_system_admin = require_roles(UserRole.SYSTEM_ADMIN)

# 与角色的业务范围一致；系统管理员可以绑定当前租户内的任意有效组织。
_ROLE_ORG_TYPES = {
    UserRole.SCHOOL_ADMIN: "school",
    UserRole.DEPARTMENT_ADMIN: "department",
    UserRole.BRANCH_SECRETARY: "branch",
    UserRole.ORGANIZER: "branch",
    UserRole.MEMBER: "branch",
    UserRole.APPLICANT: "branch",
}


@router.get(
    "/admin/org-units",
    response_model=APIResponse[list[AccountOrgOption]],
    summary="账号可分配的组织",
)
async def account_org_units(
    request: Request,
    user: User = Depends(_require_system_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[AccountOrgOption]]:
    """仅系统管理员可获取当前租户的有效组织选项。"""
    organizations = await accessible_org_units(db, user)
    return APIResponse(
        data=[
            AccountOrgOption(
                id=str(org.id), name=org.name, org_type=cast(AccountOrgType, org.org_type)
            )
            for org in organizations
            if org.org_type in {"school", "department", "branch"}
        ],
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post(
    "/admin/users",
    response_model=APIResponse[AccountCreated],
    status_code=201,
    summary="创建登录账号",
)
async def create_account(
    body: AccountCreateRequest,
    request: Request,
    user: User = Depends(_require_system_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[AccountCreated]:
    """创建同租户账号，并在同一事务内记录不含密码的审计日志。"""
    organization = (
        await db.execute(
            select(OrgUnit)
            .where(
                OrgUnit.id == body.org_unit_id,
                OrgUnit.tenant_id == str(user.tenant_id),
                OrgUnit.is_deleted.is_(False),
                OrgUnit.org_type.in_(["school", "department", "branch"]),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=403, detail="请选择当前租户内的有效组织")
    expected_type = _ROLE_ORG_TYPES.get(body.role)
    if expected_type and organization.org_type != expected_type:
        raise HTTPException(status_code=422, detail="所选角色与组织类型不匹配")

    existing = (
        await db.execute(
            select(User.id).where(
                User.tenant_id == str(user.tenant_id), User.username == body.username
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名不可用，请更换后重试")

    account = User(
        tenant_id=str(user.tenant_id),
        username=body.username,
        name=body.name,
        password_hash=await run_in_threadpool(hash_password, body.password.get_secret_value()),
        role=body.role,
        org_unit_id=str(organization.id),
        is_active=True,
    )
    db.add(account)
    try:
        await db.flush()
    except IntegrityError as exc:
        # 用户名全局唯一；同时处理跨租户重名与并发创建，不泄露已有账号归属。
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名不可用，请更换后重试") from exc
    await audit_operation(
        db,
        request,
        user,
        action="create",
        resource_type="user",
        resource_id=str(account.id),
        new_value={"role": account.role.value, "org_unit_id": account.org_unit_id},
    )
    await db.commit()
    return APIResponse(
        data=AccountCreated(**UserInfo.from_user(account).model_dump(), org_name=organization.name),
        trace_id=getattr(request.state, "trace_id", None),
    )


class TenantSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=50)
    rerank_top_k: Optional[int] = Field(None, ge=1, le=50)
    no_evidence_threshold: Optional[float] = Field(None, ge=0.05, le=1)
    exclude_expired_by_default: Optional[bool] = None
    activist_training_days: Optional[int] = Field(None, ge=1, le=3650)
    probationary_period_days: Optional[int] = Field(None, ge=1, le=3650)


@router.get("/admin/config", response_model=APIResponse[dict], summary="租户有效配置")
async def read_config(
    request: Request, user: User = Depends(_require_config), db: AsyncSession = Depends(get_db)
) -> APIResponse[dict[str, Any]]:
    await tenant_config.load(db, str(user.tenant_id))
    return APIResponse(
        data={
            key: tenant_config.get(str(user.tenant_id), key) for key in TenantSettings.model_fields
        },
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.patch("/admin/config", response_model=APIResponse[dict], summary="保存租户配置")
async def update_config(
    body: TenantSettings,
    request: Request,
    user: User = Depends(_require_config),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(status_code=422, detail="必须提供非空配置值")
    old = {key: tenant_config.get(str(user.tenant_id), key) for key in values}
    try:
        await tenant_config.save(db, str(user.tenant_id), values)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit_operation(
        db,
        request,
        user,
        action="update",
        resource_type="tenant_config",
        resource_id=str(user.tenant_id),
        old_value=old,
        new_value=values,
    )
    await db.commit()
    return await read_config(request, user, db)


async def _audit_filters(
    action: Optional[str] = Query(None, max_length=50, description="按动作筛选"),
    resource_type: Optional[str] = Query(None, max_length=50, description="按对象类型筛选"),
    user_id: Optional[str] = Query(None, max_length=36, description="按操作人编号筛选"),
    resource_id: Optional[str] = Query(None, max_length=200, description="按对象编号筛选"),
    data_level: Optional[DataLevel] = Query(None, description="按数据级别筛选"),
    result: Optional[str] = Query(
        None, pattern="^(success|failed|denied)$", description="按结果筛选"
    ),
    anonymous: bool = Query(False, description="仅平台系统管理员：查询未登录 / 匿名事件"),
    tenant_id: Optional[str] = Query(
        None, max_length=36, description="查看其他租户仅平台管理员可用"
    ),
    start_at: Optional[datetime] = Query(None, description="起始时间（含）"),
    end_at: Optional[datetime] = Query(None, description="结束时间（含）"),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> AuditQuery:
    """审计筛选条件：时间口径、匿名分支与租户边界收口在一处，查询与导出共用"""
    start = as_utc_naive(start_at)
    end = as_utc_naive(end_at)
    if start and end and start > end:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    if anonymous:
        if tenant_id:
            raise HTTPException(422, "匿名事件查询不能与按租户检索同时使用")
        if not await is_platform_admin(db, user):
            raise HTTPException(403, "匿名认证审计仅供真实平台系统管理员查询")
        return AuditQuery(
            tenant_id=ANONYMOUS_TENANT,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            data_level=data_level.value if data_level else None,
            result=result,
            start_at=start,
            end_at=end,
        )
    # 显式指定租户才走身份管理口径（校验租户存在且仅平台管理员可用）；未指定沿用本人租户，
    # 避免改变既有查询行为。
    effective = (
        str((await IdentityService(db, user).tenant(tenant_id)).id)
        if tenant_id
        else str(user.tenant_id)
    )
    return AuditQuery(
        tenant_id=effective,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_level=data_level.value if data_level else None,
        result=result,
        start_at=start,
        end_at=end,
    )


@router.get("/admin/audit-logs", response_model=APIResponse[dict], summary="审计日志查询")
async def read_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    query: AuditQuery = Depends(_audit_filters),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict[str, Any]]:
    """按筛选条件分页查询审计日志；跨租户与匿名事件仅平台管理员可用。"""
    with bypass_tenant_filter() if query.tenant_id == ANONYMOUS_TENANT else nullcontext():
        total = (await db.execute(query.count_statement())).scalar_one()
        rows = (
            (await db.execute(query.statement().offset((page - 1) * page_size).limit(page_size)))
            .scalars()
            .all()
        )
    return APIResponse(
        data={
            "items": [audit_view(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "scope_note": query.scope_note(),
        },
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.get(
    "/admin/audit-logs/export",
    response_model=None,
    summary="导出审计日志（对账包）",
    description=(
        "按当前筛选导出审计对账包：台账 CSV + 导出说明 + manifest（含筛选口径 / 条数 / 导出人）；"
        "导出动作写入审计，超出行数上限时提示分批导出。"
    ),
)
async def export_audit_logs(
    request: Request,
    query: AuditQuery = Depends(_audit_filters),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出对账包：台账按时间正序（对账按时间轴读），页面列表按最新在前。"""
    with bypass_tenant_filter() if query.tenant_id == ANONYMOUS_TENANT else nullcontext():
        total = (await db.execute(query.count_statement())).scalar_one()
        if total > MAX_EXPORT_ROWS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": ErrorCode.BUSINESS_ERROR,
                    "message": (
                        f"当前条件共 {total} 条，超过单次导出上限 {MAX_EXPORT_ROWS} 条："
                        "请缩小时间范围或按动作 / 对象分批导出，避免生成打不开的大文件。"
                    ),
                },
            )
        rows = (
            (
                await db.execute(
                    query.statement()
                    .order_by(None)
                    .order_by(AuditLog.created_at.asc())
                    .limit(MAX_EXPORT_ROWS)
                )
            )
            .scalars()
            .all()
        )
    scope_note = query.scope_note()
    content = build_audit_package(
        rows,
        scope_note=scope_note,
        exported_by=f"{user.name}（{user.username}）",
    )
    # 审计内容可能含敏感操作明细，导出按 sensitive 落审计（导出本身也要可追溯）
    await audit_operation(
        db,
        request,
        user,
        action="export",
        resource_type="audit_log",
        data_level="sensitive",
        new_value={"rows": len(rows), "scope": scope_note},
    )
    await db.commit()
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="audit-logs.zip"',
            "Cache-Control": "no-store",
        },
    )
