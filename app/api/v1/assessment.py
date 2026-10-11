"""年度考核API：当前角色、组织及资料权限校验，操作成功/失败均留审计。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.audit import write_audit
from app.core.security import Permission, has_permission
from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.assessment import (
    AnnualScope,
    AssessmentWorkspace,
    EvidenceCreate,
    IndicatorCreate,
    PlanCreate,
    PolicyUpdate,
    ReminderHandle,
    ReviewRequest,
    TaskCreate,
    TaskUpdate,
)
from app.schemas.common import APIResponse
from app.services.assessment_service import AssessmentService, row_view, run_view

router = APIRouter(prefix="/assessment", tags=["年度考核"])


@asynccontextmanager
async def assessment_operation(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    permission: Permission,
    action: str,
    resource_id: str | None = None,
) -> AsyncIterator[AssessmentService]:
    """失败先回滚业务，再独立提交不含正文的失败摘要。"""
    actor_id, actor_name, tenant_id = str(user.id), user.username, str(user.tenant_id)
    try:
        if not has_permission(user.role, permission):
            raise HTTPException(403, "无年度考核操作权限")
        service = AssessmentService(db, user)
        yield service
        if service.audit_changes:
            for change in service.audit_changes:
                await audit_operation(
                    db, request, user, action=action, data_level="sensitive", **change
                )
        else:
            await audit_operation(
                db,
                request,
                user,
                action=action,
                resource_type="assessment",
                resource_id=resource_id,
                data_level="sensitive",
            )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        await write_audit(
            db,
            tenant_id=tenant_id,
            user_id=actor_id,
            user_name=actor_name,
            action=action,
            resource_type="assessment",
            resource_id=resource_id,
            request_id=getattr(request.state, "trace_id", "unknown"),
            result=(
                "denied"
                if isinstance(exc, HTTPException) and exc.status_code in {403, 404}
                else "failed"
            ),
            data_level="sensitive",
            error_message=(
                "权限或业务校验未通过" if isinstance(exc, HTTPException) else "业务操作失败"
            ),
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()
        raise


def envelope(request: Request, data: Any) -> APIResponse:
    """与既有接口保持同一响应包裹体。"""
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/org-units", response_model=APIResponse[list[dict]], summary="考核组织范围")
async def organizations(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_QUERY, action="assessment_orgs"
    ) as service:
        data = [
            {"id": str(org.id), "name": org.name, "org_type": org.org_type}
            for org in await service.organizations()
        ]
    return envelope(request, data)


@router.get(
    "/workspace", response_model=APIResponse[AssessmentWorkspace], summary="工作台、进度及实时缺项"
)
async def workspace(
    request: Request,
    org_unit_id: str = Query(min_length=1, max_length=36),
    year: int = Query(ge=2000, le=2100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_QUERY, action="assessment_read"
    ) as service:
        data = AssessmentWorkspace.model_validate(await service.workspace(org_unit_id, year))
    return envelope(request, data)


@router.post("/indicators", response_model=APIResponse[dict], summary="追加学校年度指标版本")
async def indicator(
    body: IndicatorCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_CONFIGURE,
        action="assessment_rule_version",
    ) as service:
        data = row_view(await service.create_indicator(body))
    return envelope(request, data)


@router.post("/tasks", response_model=APIResponse[dict], summary="创建年度任务")
async def create_task(
    body: TaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_MANAGE, action="assessment_task_create"
    ) as service:
        data = row_view(await service.save_task(body))
        await service.sync_reminders(body.org_unit_id, body.year)
    return envelope(request, data)


@router.put("/tasks/{task_id}", response_model=APIResponse[dict], summary="修订年度任务并重新审核")
async def update_task(
    task_id: str,
    body: TaskUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_MANAGE,
        action="assessment_task_update",
        resource_id=task_id,
    ) as service:
        data = row_view(await service.save_task(body, task_id))
        await service.sync_reminders(body.org_unit_id, body.year)
    return envelope(request, data)


@router.post("/evidence", response_model=APIResponse[dict], summary="绑定真实文件版本作为指标佐证")
async def evidence(
    body: EvidenceCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_MANAGE,
        action="assessment_evidence_link",
    ) as service:
        data = (await service._evidence_views([await service.add_evidence(body)]))[0]
    return envelope(request, data)


@router.post(
    "/recalculate", response_model=APIResponse[dict], summary="幂等归集并保留规则和来源快照"
)
async def recalculate(
    body: AnnualScope,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_MANAGE, action="assessment_recalculate"
    ) as service:
        run = await service.recalculate(body.org_unit_id, body.year)
        data = {**run_view(run), "results": run.results}
    return envelope(request, data)


@router.get(
    "/runs/{run_id}", response_model=APIResponse[dict], summary="读取仍符合当前权限的归集结果"
)
async def run_detail(
    run_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_QUERY,
        action="assessment_run_read",
        resource_id=run_id,
    ) as service:
        data = await service.historical_run(run_id)
    return envelope(request, data)


@router.post(
    "/{kind}/{record_id}/review",
    response_model=APIResponse[dict],
    summary="人工通过或退回任务、佐证、归集及计划",
)
async def review(
    kind: Literal["tasks", "evidence", "runs", "plans"],
    record_id: str,
    body: ReviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_REVIEW,
        action="assessment_review",
        resource_id=record_id,
    ) as service:
        record = await service.review(kind, record_id, body)
        data = run_view(record) if kind == "runs" else row_view(record)
        if kind == "evidence":
            data = (await service._evidence_views([record]))[0]
    return envelope(request, data)


@router.post("/plans", response_model=APIResponse[dict], summary="生成或人工修订年度计划草案")
async def plan(
    body: PlanCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_MANAGE, action="assessment_plan_version"
    ) as service:
        data = row_view(await service.create_plan(body))
    return envelope(request, data)


@router.put("/policy", response_model=APIResponse[dict], summary="学校确认电子归档及提醒配置")
async def policy(
    body: PolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_CONFIGURE,
        action="assessment_policy_confirm",
    ) as service:
        data = row_view(await service.update_policy(body))
    return envelope(request, data)


@router.post(
    "/reminders/sync", response_model=APIResponse[dict], summary="补偿扫描并去重生成站内提醒"
)
async def reminders(
    body: AnnualScope,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_QUERY,
        action="assessment_reminders_scan",
    ) as service:
        data = {"count": len(await service.sync_reminders(body.org_unit_id, body.year))}
    return envelope(request, data)


@router.post(
    "/reminders/{record_id}/handle",
    response_model=APIResponse[dict],
    summary="责任人登记提醒处理结果",
)
async def handle(
    record_id: str,
    body: ReminderHandle,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_QUERY,
        action="assessment_reminder_handle",
        resource_id=record_id,
    ) as service:
        data = row_view(await service.handle_reminder(record_id, body.note))
    return envelope(request, data)


@router.post(
    "/runs/{run_id}/archive",
    response_model=APIResponse[dict],
    summary="人工审核及合规确认后归档佐证目录",
)
async def archive(
    run_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_MANAGE,
        action="assessment_archive",
        resource_id=run_id,
    ) as service:
        data = row_view(await service.archive(run_id))
    return envelope(request, data)


@router.post("/runs/{run_id}/export", summary="按当前权限导出指标表、任务及佐证目录ZIP")
async def export(
    run_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    async with assessment_operation(
        db,
        request,
        user,
        permission=Permission.ASSESSMENT_EXPORT,
        action="assessment_export",
        resource_id=run_id,
    ) as service:
        content, summary = await service.export(run_id)
        await audit_operation(
            db,
            request,
            user,
            action="assessment_export_manifest",
            resource_type="assessment",
            resource_id=run_id,
            data_level="sensitive",
            new_value=summary,
        )
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="assessment-{run_id}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/sources/{source}/{record_id}",
    response_model=APIResponse[dict],
    summary="授权钻取单个统计源记录",
)
async def source_detail(
    source: str,
    record_id: str,
    request: Request,
    org_unit_id: str = Query(min_length=1, max_length=36),
    year: int = Query(ge=2000, le=2100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    async with assessment_operation(
        db, request, user, permission=Permission.ASSESSMENT_QUERY, action="assessment_source_read"
    ) as service:
        collected = await service.collect(org_unit_id, year)
        references = [
            reference for result in collected["results"] for reference in result["sources"]
        ]
        data = next(
            (
                reference
                for reference in references
                if reference["source"] == source and reference["record_id"] == record_id
            ),
            None,
        )
        if data is None:
            raise HTTPException(404, "源记录不在当前授权统计范围")
    return envelope(request, data)
