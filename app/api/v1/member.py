"""党员发展接口（资格校验 / 流转建议 / 待办建议）

- ``POST /member/qualification-check``：资格校验（材料 + 时限）；
- ``POST /member/transition-suggestion``：流转建议（**不写入阶段字段**）；
- ``POST /member/todo-suggestions``：待办建议（预留接口）。

权限：支部书记及以上（``member.query``）。阶段流转为人工操作，接口只给建议。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.member_flow import MemberFlow
from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.models.member import MemberProfile
from app.models.user import User
from app.rules.member_stages import MemberStage
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.member import (
    DECISION_BOUNDARY_NOTE,
    MemberCreateRequest,
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

router = APIRouter()

# 规则加载一次（可配置）
_flow = MemberFlow()
_require_member = require_permissions(Permission.MEMBER_QUERY)


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _invalid_stage(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": ErrorCode.BUSINESS_ERROR, "message": f"非法阶段: {exc}"},
    )


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
) -> APIResponse[TodoSuggestionsResponse]:
    try:
        todos = _flow.generate_todos(
            current_stage=body.current_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    return APIResponse(
        data=TodoSuggestionsResponse(
            todos=[TodoItem(category=category, content=content) for category, content in todos],
            note=DECISION_BOUNDARY_NOTE,
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/member/roster",
    response_model=APIResponse[MemberRosterResponse],
    summary="培养对象名册",
    description="查询当前租户的培养对象及其阶段台账（在阶段天数按日期实时计算）。",
    tags=["党员发展"],
)
async def member_roster(
    request: Request,
    user: User = Depends(_require_member),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterResponse]:
    """培养对象名册"""
    result = await db.execute(
        select(MemberProfile)
        .where(
            MemberProfile.tenant_id == tenant_id,
            MemberProfile.is_deleted.is_(False),
            MemberProfile.is_active.is_(True),
        )
        .order_by(MemberProfile.created_at.desc())
    )
    profiles = list(result.scalars().all())
    today = date.today()
    items = [MemberRosterItem.from_profile(p, today=today) for p in profiles]
    return APIResponse(
        data=MemberRosterResponse(total=len(items), items=items),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/roster",
    response_model=APIResponse[MemberRosterItem],
    summary="新增培养对象",
    description="登记一名培养对象（属数据录入，不构成组织认定）。阶段须为合法取值。",
    tags=["党员发展"],
)
async def create_member(
    body: MemberCreateRequest,
    request: Request,
    user: User = Depends(_require_member),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterItem]:
    """新增培养对象"""
    try:
        stage = MemberStage(body.current_stage)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": f"非法阶段: {body.current_stage}",
            },
        ) from exc

    profile = MemberProfile(
        tenant_id=tenant_id,
        name=body.name.strip(),
        org_name=body.org_name.strip(),
        org_unit_id=body.org_unit_id,
        current_stage=stage.value,
        stage_joined_on=body.stage_joined_on or date.today(),
        materials=body.materials,
        pending=body.pending,
        is_active=True,
    )
    db.add(profile)
    await db.commit()

    return APIResponse(
        data=MemberRosterItem.from_profile(profile),
        trace_id=_trace_id(request),
    )
