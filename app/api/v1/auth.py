"""鉴权接口

- ``POST /api/v1/auth/login``：账号密码登录，签发访问 / 刷新令牌；
- ``GET  /api/v1/auth/me``：返回当前登录用户信息（敏感字段脱敏）。

租户标识从账号记录解析，**不接受前端传入**（框架文档 8.2）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserInfo
from app.schemas.common import APIResponse

router = APIRouter()


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


@router.post(
    "/auth/login",
    response_model=APIResponse[TokenResponse],
    summary="登录",
    description="账号密码登录，成功返回访问令牌与刷新令牌。",
    tags=["鉴权"],
)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TokenResponse]:
    """登录并签发令牌"""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    # 统一的错误信息，避免用户名枚举
    if user is None or not verify_password(body.password, user.password_hash or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用"
        )

    access_token = create_access_token(
        subject=str(user.id), tenant_id=user.tenant_id, role=user.role
    )
    refresh_token = create_refresh_token(
        subject=str(user.id), tenant_id=user.tenant_id, role=user.role
    )
    return APIResponse(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/auth/me",
    response_model=APIResponse[UserInfo],
    summary="当前用户信息",
    description="返回当前登录用户信息，邮箱与手机号自动脱敏。",
    tags=["鉴权"],
)
async def read_me(
    request: Request,
    user: User = Depends(get_current_user),
) -> APIResponse[UserInfo]:
    """获取当前用户信息"""
    return APIResponse(data=UserInfo.from_user(user), trace_id=_trace_id(request))
