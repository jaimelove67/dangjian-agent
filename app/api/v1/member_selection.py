"""选优结论与团组织推优 API（模块2 / `T-MEM-13`、`T-MEM-06`）。

权限沿用党员发展口径：查询 ``member.query``；登记 / 修订 / 送审与推优登记 ``member.scoring``；
**审核 ``member.stage_transition``**——结论生效后是阶段流转的认定依据，所以审核走"能办阶段
流转"这个权限点（登记只需 ``member.scoring``，两个权限点分开，将来把登记与审核分给不同
角色时不用改代码）。

需要说清的是：今天能登记的组织角色同时也有审核权限，因此**真正拦住"一个人说了算"的不是
权限点，而是自审禁入**——``apply_review`` 校验"送审人不得审核自己的版本"，加上
``expected_revision`` 拒绝覆盖别人已改的版本，两处都在接口层面，绕不过去。
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
from app.schemas.member_selection import (
    LeagueRecommendationCreate,
    LeagueRecommendationRevoke,
    SelectionCreate,
    SelectionDecision,
    SelectionSubmit,
    SelectionUpdate,
)
from app.services.member_selection_service import MAX_PAGE_SIZE, MemberSelectionService

router = APIRouter()
_query = require_permissions(Permission.MEMBER_QUERY)
_manage = require_permissions(Permission.SCORING)
_review = require_permissions(Permission.STAGE_TRANSITION)


async def selection_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> MemberSelectionService:
    """鉴权依赖与服务共用同一请求事务。"""
    return await MemberSelectionService(db, user).initialize()


async def respond(
    request: Request,
    service: MemberSelectionService,
    data: dict[str, Any],
    action: str,
    resource_type: str = "member_selection",
    resource_id: str | None = None,
) -> APIResponse[dict]:
    """审计只留编号、版本、状态与数量，不复制名单正文与结论依据。"""
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_level="sensitive",
        new_value={
            key: data[key]
            for key in (
                "revision",
                "review_status",
                "batch_no",
                "round_no",
                "total",
                "candidate_count",
            )
            if key in data
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


# ==================== 选优结论（拟推荐名单） ====================


@router.get("/member-full/selections", response_model=APIResponse[dict])
async def list_selections(
    request: Request,
    batch_no: str | None = Query(None, max_length=20),
    round_no: int | None = Query(None, ge=1, le=20),
    review_status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """选优结论台账：按批次 / 轮次 / 状态筛选，附状态汇总。"""
    data = await service.list_selections(
        batch_no=batch_no,
        round_no=round_no,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )
    return await respond(request, service, data, "read_member_selections")


@router.post(
    "/member-full/selections", response_model=APIResponse[dict], dependencies=[Depends(_manage)]
)
async def create_selection(
    request: Request,
    body: SelectionCreate,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """登记一份拟推荐名单（草稿）：名单与依据必须由人给出，系统不替人出结论。"""
    data = await service.create_selection(body)
    return await respond(request, service, data, "create_member_selection", resource_id=data["id"])


@router.get("/member-full/selections/{selection_id}", response_model=APIResponse[dict])
async def selection_detail(
    request: Request,
    selection_id: str,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """单条结论明细：名单、依据、辅助材料快照、缺项提示与只追加修订记录。"""
    data = await service.selection_detail(selection_id)
    return await respond(request, service, data, "read_member_selection", resource_id=selection_id)


@router.patch(
    "/member-full/selections/{selection_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def update_selection(
    request: Request,
    selection_id: str,
    body: SelectionUpdate,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """修订结论：改后回到草稿，必须重新送审。"""
    data = await service.update_selection(selection_id, body)
    return await respond(
        request, service, data, "update_member_selection", resource_id=selection_id
    )


@router.post(
    "/member-full/selections/{selection_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def submit_selection(
    request: Request,
    selection_id: str,
    body: SelectionSubmit,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """送审：名单、依据缺一项都不放行。"""
    data = await service.submit_selection(selection_id, body)
    return await respond(
        request, service, data, "submit_member_selection", resource_id=selection_id
    )


@router.post(
    "/member-full/selections/{selection_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_review)],
)
async def review_selection(
    request: Request,
    selection_id: str,
    body: SelectionDecision,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """第二位组织人员审核：提交人不能审核自己的版本（接口层面拦）。"""
    data = await service.review_selection(selection_id, body)
    return await respond(
        request, service, data, "review_member_selection", resource_id=selection_id
    )


# ==================== 团组织推优台账 ====================


@router.get("/member-full/league-recommendations", response_model=APIResponse[dict])
async def list_league_recommendations(
    request: Request,
    profile_id: str | None = Query(None, max_length=36),
    profile_ids: str | None = Query(None, max_length=8000),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """推优台账：按人筛选；给出 ``profile_ids`` 时附带"这些人有没有推优记录"。"""
    data = await service.list_recommendations(
        profile_id=profile_id, profile_ids=profile_ids, page=page, page_size=page_size
    )
    return await respond(
        request,
        service,
        data,
        "read_league_recommendations",
        resource_type="member_league_recommendation",
    )


@router.post(
    "/member-full/league-recommendations",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def create_league_recommendation(
    request: Request,
    body: LeagueRecommendationCreate,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """登记团组织推优：只登记事实，不判断年龄、不阻断选优与阶段流转。"""
    data = await service.create_recommendation(body)
    return await respond(
        request,
        service,
        data,
        "create_league_recommendation",
        resource_type="member_league_recommendation",
        resource_id=data["id"],
    )


@router.post(
    "/member-full/league-recommendations/{recommendation_id}/revoke",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def revoke_league_recommendation(
    request: Request,
    recommendation_id: str,
    body: LeagueRecommendationRevoke,
    service: MemberSelectionService = Depends(selection_service),
) -> APIResponse[dict]:
    """作废一条推优记录（录错 / 未办成）：记录保留、理由必填。"""
    data = await service.revoke_recommendation(recommendation_id, body)
    return await respond(
        request,
        service,
        data,
        "revoke_league_recommendation",
        resource_type="member_league_recommendation",
        resource_id=recommendation_id,
    )
