"""发展党员全流程 API：批次、档案、材料记录、人工流转、提醒、培养、投票、评分与档案检查。

权限：查询 ``member.query``；登记、流转、材料审核与档案检查 ``member.stage_transition``；
评分 ``member.scoring``。所有建议与评分均不自动形成组织认定。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.member_ext import (
    ArchiveCheckRun,
    BatchCreate,
    CultivationCreate,
    MaterialCreate,
    MaterialReview,
    ProfileUpdate,
    ReminderResolve,
    ScoringRequest,
    TransitionRequest,
    VoteBatch,
)
from app.services.member_service import DECISION_BOUNDARY, MemberDevelopment, row_data

router = APIRouter()
_query = require_permissions(Permission.MEMBER_QUERY)
_transition = require_permissions(Permission.STAGE_TRANSITION)
_scoring = require_permissions(Permission.SCORING)


async def member_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> MemberDevelopment:
    return await MemberDevelopment(db, user).initialize()


async def respond(
    request: Request,
    service: MemberDevelopment,
    data: dict[str, Any],
    action: str,
    resource_type: str = "member",
    resource_id: str | None = None,
) -> APIResponse[dict]:
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_level="sensitive",
        new_value={key: data[key] for key in ("total", "year", "stage", "batch_no") if key in data},
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


def bind(body: Any, **extra: Any) -> dict[str, Any]:
    return {**body.model_dump(), **extra}


@router.get("/member-full/stats", response_model=APIResponse[dict])
async def roster_stats(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    batch_no: str | None = Query(None, max_length=20),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.roster_stats(year=year, batch_no=batch_no),
        "read_roster_stats",
    )


@router.get("/member-full/batches", response_model=APIResponse[dict])
async def batches(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.list_batches(
            year=year, org_unit_id=org_unit_id, page=page, page_size=page_size
        ),
        "read_batches",
        "member_batch",
    )


@router.post("/member-full/batches", response_model=APIResponse[dict], dependencies=[Depends(_transition)])
async def create_batch(
    body: BatchCreate, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    batch = await service.create_batch(body)
    return await respond(
        request,
        service,
        row_data(batch),
        "create",
        "member_batch",
        str(batch.id),
    )


@router.get("/member-full/profiles/{profile_id}", response_model=APIResponse[dict])
async def profile_detail(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    profile = await service.profile(profile_id)
    data = row_data(profile)
    data["materials"] = await service.list_materials(profile_id)
    data["stage_history"] = await service.stage_history(profile_id)
    data["cultivation"] = await service.cultivation(profile_id)
    data["boundary"] = DECISION_BOUNDARY
    return await respond(
        request, service, data, "read", "member", profile_id
    )


@router.patch(
    "/member-full/profiles/{profile_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    profile = await service.update_profile(profile_id, body)
    return await respond(
        request, service, row_data(profile), "revise", "member", profile_id
    )


@router.post(
    "/member-full/profiles/{profile_id}/transition",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def transition(
    profile_id: str,
    body: TransitionRequest,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    profile = await service.transition(profile_id, body)
    data = row_data(profile)
    data["stage_history"] = await service.stage_history(profile_id)
    data["boundary"] = DECISION_BOUNDARY
    return await respond(
        request, service, data, "transition", "member", profile_id
    )


@router.get("/member-full/profiles/{profile_id}/materials", response_model=APIResponse[dict])
async def materials(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        {"items": await service.list_materials(profile_id)},
        "read_materials",
        "member",
        profile_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/materials",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def add_material(
    profile_id: str,
    body: MaterialCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    material = await service.add_material(profile_id, body)
    return await respond(
        request,
        service,
        row_data(material),
        "create_material",
        "member_material",
        str(material.id),
    )


@router.post(
    "/member-full/materials/{material_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def review_material(
    material_id: str,
    body: MaterialReview,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    material = await service.review_material(material_id, body)
    return await respond(
        request,
        service,
        row_data(material),
        "review_material",
        "member_material",
        material_id,
    )


@router.get("/member-full/reminders", response_model=APIResponse[dict])
async def reminders(
    request: Request,
    org_unit_id: str | None = Query(None, max_length=36),
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.reminders(
            org_unit_id=org_unit_id, status=status, page=page, page_size=page_size
        ),
        "read_reminders",
        "member_reminder",
    )


@router.post(
    "/member-full/profiles/{profile_id}/sync-reminders",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def sync_reminders(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    """按业务规则生成该对象的提醒；重复执行不重复写入。"""
    profile = await service.profile(profile_id)
    created = await service.sync_reminders(profile)
    return await respond(
        request,
        service,
        {"profile_id": profile_id, "created": len(created), "notice": "提醒按阶段规则生成，重复执行不重复"},
        "sync_reminders",
        "member_reminder",
        profile_id,
    )


@router.post("/member-full/reminders/{reminder_id}/resolve", response_model=APIResponse[dict])
async def resolve_reminder(
    reminder_id: str,
    body: ReminderResolve,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    reminder = await service.resolve_reminder(reminder_id, body)
    return await respond(
        request,
        service,
        row_data(reminder),
        "resolve_reminder",
        "member_reminder",
        reminder_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/cultivation",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def add_cultivation(
    profile_id: str,
    body: CultivationCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    record = await service.add_cultivation(body, profile_id=profile_id)
    return await respond(
        request,
        service,
        row_data(record),
        "create_cultivation",
        "member_cultivation",
        str(record.id),
    )


@router.post(
    "/member-full/votes", response_model=APIResponse[dict], dependencies=[Depends(_scoring)]
)
async def submit_votes(
    body: VoteBatch, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.submit_votes(body),
        "submit_votes",
        "member_vote",
    )


@router.get("/member-full/votes/summary", response_model=APIResponse[dict])
async def vote_summary(
    request: Request,
    batch_no: str = Query(min_length=1, max_length=20),
    round_no: int = Query(ge=1, le=20),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.vote_summary(batch_no, round_no),
        "read_vote_summary",
        "member_vote",
    )


@router.post("/member-full/scoring", response_model=APIResponse[dict], dependencies=[Depends(_scoring)])
async def scoring(
    body: ScoringRequest, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.scoring(body),
        "scoring",
        "member",
        body.profile_id,
    )


@router.post(
    "/member-full/archive-check",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def archive_check(
    body: ArchiveCheckRun,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.archive_check(body),
        "archive_check",
        "member",
        body.profile_id,
    )
