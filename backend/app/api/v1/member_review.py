"""民主评议党员 API（模块3 / T-ORG-11）：按年度发起、录入程序与等次、送审与审核、汇总。

权限沿用组织生活口径：查询 ``meeting.query``；发起、录入与修订 ``meeting.manage``；
审核 ``meeting.review``。录入者与审核者必须是不同的人（``apply_review`` 校验）。

本人查看自己的评议结果走 ``member.self_query``，见 ``app/api/v1/member_self.py``：
普通党员看不到别人的评议结果。
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
from app.schemas.member_review import (
    ReviewCreate,
    ReviewDecision,
    ReviewLaunch,
    ReviewSubmit,
    ReviewUpdate,
)
from app.services.member_review_service import MemberReviewService

router = APIRouter()
_query = require_permissions(Permission.MEETING_QUERY)
_manage = require_permissions(Permission.MEETING_MANAGE)
_review = require_permissions(Permission.MEETING_REVIEW)


async def review_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> MemberReviewService:
    """鉴权依赖与服务共用同一请求事务。"""
    return await MemberReviewService(db, user).initialize()


async def respond(
    request: Request,
    service: MemberReviewService,
    data: dict[str, Any],
    action: str,
    resource_id: str | None = None,
) -> APIResponse[dict]:
    """审计只留编号、年度、版本与数量，不复制评议意见正文。"""
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type="member_review",
        resource_id=resource_id,
        data_level="sensitive",
        new_value={
            key: data[key] for key in ("revision", "year", "created", "total") if key in data
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/meeting/member-reviews/workspace", response_model=APIResponse[dict])
async def workspace(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """某年度（可指定支部）的评议进度、应评议名单与汇总。"""
    data = await service.workspace(year=year, org_unit_id=org_unit_id)
    return await respond(request, service, data, "read_member_reviews")


@router.post(
    "/meeting/member-reviews/launch",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def launch(
    request: Request,
    body: ReviewLaunch,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """按年度发起：为支部在册党员建立评议草稿，已有记录不覆盖。"""
    data = await service.launch(body)
    return await respond(request, service, data, "launch_member_reviews")


@router.post(
    "/meeting/member-reviews",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def create_review(
    request: Request,
    body: ReviewCreate,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """为一名党员单独建立本年度评议记录。"""
    row = await service.create(body)
    data = {"id": str(row.id), "year": row.year, "revision": row.revision}
    return await respond(request, service, data, "create_member_review", str(row.id))


@router.get("/meeting/member-reviews/{review_id}", response_model=APIResponse[dict])
async def review_detail(
    request: Request,
    review_id: str,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """单条评议明细：程序、等次、缺项提示与只追加修订记录。"""
    data = await service.detail(review_id)
    return await respond(request, service, data, "read_member_review", review_id)


@router.patch(
    "/meeting/member-reviews/{review_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def update_review(
    request: Request,
    review_id: str,
    body: ReviewUpdate,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """修订程序或等次；修改后回到草稿，须重新送审。"""
    row = await service.update(review_id, body)
    data = {"id": str(row.id), "revision": row.revision, "review_status": row.review_status}
    return await respond(request, service, data, "update_member_review", review_id)


@router.post(
    "/meeting/member-reviews/{review_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def submit_review(
    request: Request,
    review_id: str,
    body: ReviewSubmit,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """送审：必填项缺一项都不放行。"""
    row = await service.submit(review_id, body)
    data = {"id": str(row.id), "revision": row.revision, "review_status": row.review_status}
    return await respond(request, service, data, "submit_member_review", review_id)


@router.post(
    "/meeting/member-reviews/{review_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_review)],
)
async def review_review(
    request: Request,
    review_id: str,
    body: ReviewDecision,
    service: MemberReviewService = Depends(review_service),
) -> APIResponse[dict]:
    """人工审核：提交人不能审核自己的版本。"""
    row = await service.review(review_id, body)
    data = {"id": str(row.id), "revision": row.revision, "review_status": row.review_status}
    return await respond(request, service, data, "review_member_review", review_id)
