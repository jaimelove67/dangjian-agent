"""用户信息接口"""
from fastapi import APIRouter, Depends, Request

from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import UserInfo
from app.schemas.common import APIResponse

router = APIRouter()


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


@router.get(
    "/user/info",
    response_model=APIResponse[UserInfo],
    summary="获取用户信息",
    description="返回当前登录用户的详细信息",
    tags=["用户"],
)
async def get_user_info(
    request: Request,
    user: User = Depends(get_current_user),
) -> APIResponse[UserInfo]:
    """获取用户信息"""
    return APIResponse(data=UserInfo.from_user(user), trace_id=_trace_id(request))
