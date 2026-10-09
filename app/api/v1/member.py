"""党员发展接口（资格校验 / 流转建议 / 待办建议）

- ``POST /member/qualification-check``：资格校验（材料 + 时限）；
- ``POST /member/transition-suggestion``：流转建议（**不写入阶段字段**）；
- ``POST /member/todo-suggestions``：待办建议（预留接口）。

权限：支部书记及以上（``member.query``）。阶段流转为人工操作，接口只给建议。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.chains.member_flow import MemberFlow
from app.core.security import Permission
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.member import (
    DECISION_BOUNDARY_NOTE,
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
