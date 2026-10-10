"""党员发展接口（资格校验 / 流转建议 / 待办建议）

- ``POST /member/qualification-check``：资格校验（材料 + 时限）；
- ``POST /member/transition-suggestion``：流转建议（**不写入阶段字段**）；
- ``POST /member/todo-suggestions``：待办建议（预留接口）。
- ``GET /member/roster``：按组织范围分页查询真实台账；
- ``POST /member/roster``：组织人员人工登记台账。

权限：支部书记及以上（``member.query``）。阶段流转为人工操作，接口只给建议。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.chains.member_flow import MemberFlow
from app.core.config import tenant_config
from app.core.security import BS_ALL, Permission, get_role_profile
from app.db.session import get_db
from app.deps import require_permissions
from app.models.member import MemberProfile
from app.models.user import User
from app.rules.member_stages import MemberStage
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.member import (
    DECISION_BOUNDARY_NOTE,
    MemberCreateRequest,
    MemberOrgOption,
    MemberRosterItem,
    MemberRosterResponse,
    QualificationCheckRequest,
    QualificationResult,
    TodoItem,
    TodoSuggestionsRequest,
    TodoSuggestionsResponse,
    TransitionSuggestion,
    TransitionSuggestionRequest,
)
from app.services.org_scope import accessible_org_units

router = APIRouter()

# 规则加载一次（可配置）
_flow = MemberFlow()
_require_member = require_permissions(Permission.MEMBER_QUERY)
_require_member_manage = require_permissions(Permission.STAGE_TRANSITION)


def _flow_for(user: User) -> MemberFlow:
    """租户配置作用于进度提醒；资格最短时限仍由业务规则控制。"""
    tenant_id = str(user.tenant_id)
    return MemberFlow(
        _flow.rules,
        reminder_limits={
            MemberStage.ACTIVIST: tenant_config.get(tenant_id, "activist_training_days"),
            MemberStage.PROBATIONARY: tenant_config.get(tenant_id, "probationary_period_days"),
        },
    )


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _invalid_stage(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": ErrorCode.BUSINESS_ERROR, "message": f"非法阶段: {exc}"},
    )


@router.get(
    "/member/org-units",
    response_model=APIResponse[list[MemberOrgOption]],
    summary="可登记培养对象的组织",
    tags=["党员发展"],
)
async def member_org_units(
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[MemberOrgOption]]:
    organizations = await accessible_org_units(db, user)
    return APIResponse(
        data=[
            MemberOrgOption(id=str(org.id), name=org.name, org_type=org.org_type)
            for org in organizations
        ],
        trace_id=_trace_id(request),
    )


@router.get(
    "/member/roster",
    response_model=APIResponse[MemberRosterResponse],
    summary="培养对象名册",
    tags=["党员发展"],
)
async def member_roster(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterResponse]:
    conditions = [
        MemberProfile.tenant_id == str(user.tenant_id),
        MemberProfile.is_deleted.is_(False),
        MemberProfile.is_active.is_(True),
    ]
    if get_role_profile(user.role).business_scope != BS_ALL:
        organizations = await accessible_org_units(db, user)
        conditions.append(MemberProfile.org_unit_id.in_([org.id for org in organizations]))
    total = (await db.execute(select(func.count(MemberProfile.id)).where(*conditions))).scalar_one()
    statement = (
        select(MemberProfile)
        .where(*conditions)
        .order_by(MemberProfile.created_at.desc(), MemberProfile.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    profiles = (await db.execute(statement)).scalars().all()
    await audit_operation(
        db,
        request,
        user,
        action="read_roster",
        resource_type="member",
        data_level="sensitive",
        new_value={"total": total, "page": page},
    )
    await db.commit()
    return APIResponse(
        data=MemberRosterResponse(
            items=[MemberRosterItem.from_profile(profile) for profile in profiles],
            total=total,
            page=page,
            page_size=page_size,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/roster",
    response_model=APIResponse[MemberRosterItem],
    summary="登记培养对象",
    tags=["党员发展"],
)
async def create_member(
    body: MemberCreateRequest,
    request: Request,
    user: User = Depends(_require_member_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterItem]:
    org_id = body.org_unit_id or user.org_unit_id
    organizations = await accessible_org_units(db, user)
    organization = next((org for org in organizations if str(org.id) == org_id), None)
    if organization is None:
        raise HTTPException(status_code=403, detail="请选择权限范围内的有效组织")
    profile = MemberProfile(
        tenant_id=str(user.tenant_id),
        name=body.name,
        org_unit_id=str(organization.id),
        org_name=organization.name,
        current_stage=body.current_stage.value,
        stage_joined_on=body.stage_joined_on or date.today(),
        materials=body.materials,
        pending=body.pending,
    )
    db.add(profile)
    await db.flush()
    await audit_operation(
        db,
        request,
        user,
        action="create",
        resource_type="member",
        resource_id=str(profile.id),
        data_level="sensitive",
        new_value={"org_unit_id": profile.org_unit_id, "stage": profile.current_stage},
    )
    await db.commit()
    return APIResponse(data=MemberRosterItem.from_profile(profile), trace_id=_trace_id(request))


@router.post(
    "/member/qualification-check",
    response_model=APIResponse[QualificationResult],
    summary="资格校验",
    description="核对材料齐全性与阶段时限，输出阻断项（不修改任何阶段）。",
    tags=["党员发展"],
)
async def qualification_check(
    body: QualificationCheckRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QualificationResult]:
    try:
        outcome = _flow.check_qualification(
            current_stage=body.current_stage,
            target_stage=body.target_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="qualification_check",
        resource_type="member",
        new_value={
            "current_stage": body.current_stage,
            "target_stage": body.target_stage,
            "eligible": outcome.eligible,
            "blocker_count": len(outcome.blockers),
        },
    )
    await db.commit()
    return APIResponse(
        data=QualificationResult(
            eligible=outcome.eligible,
            blockers=outcome.blockers,
            missing_materials=outcome.missing_materials,
            present_materials=outcome.present_materials,
            min_days=outcome.min_days,
            days_in_stage=outcome.days_in_stage,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/transition-suggestion",
    response_model=APIResponse[TransitionSuggestion],
    summary="流转建议",
    description="给出拟转入阶段与应履行程序；阶段流转仍须人工接口完成。",
    tags=["党员发展"],
)
async def transition_suggestion(
    body: TransitionSuggestionRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TransitionSuggestion]:
    try:
        outcome = _flow.suggest_transition(
            current_stage=body.current_stage,
            target_stage=body.target_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="transition_suggestion",
        resource_type="member",
        new_value={
            "current_stage": body.current_stage,
            "target_stage": body.target_stage,
            "eligible": outcome.eligible,
        },
    )
    await db.commit()
    return APIResponse(
        data=TransitionSuggestion(
            current_stage=outcome.current_stage,
            suggested_target=outcome.suggested_target,
            eligible=outcome.eligible,
            procedures=outcome.procedures,
            blockers=outcome.blockers,
            note=DECISION_BOUNDARY_NOTE,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/todo-suggestions",
    response_model=APIResponse[TodoSuggestionsResponse],
    summary="待办建议（预留）",
    description="生成待补材料/建议安排会议等待办建议，供前端展示与后续调度接入。",
    tags=["党员发展"],
)
async def todo_suggestions(
    body: TodoSuggestionsRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TodoSuggestionsResponse]:
    try:
        todos = _flow_for(user).generate_todos(
            current_stage=body.current_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="todo_suggestions",
        resource_type="member",
        new_value={"current_stage": body.current_stage, "todo_count": len(todos)},
    )
    await db.commit()
    return APIResponse(
        data=TodoSuggestionsResponse(
            todos=[TodoItem(category=category, content=content) for category, content in todos],
            note=DECISION_BOUNDARY_NOTE,
        ),
        trace_id=_trace_id(request),
    )
