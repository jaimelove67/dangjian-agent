"""鉴权接口

- ``POST /api/v1/auth/login``：账号密码登录，签发访问 / 刷新令牌；
- ``GET  /api/v1/auth/me``：返回当前登录用户信息（敏感字段脱敏）。

租户标识从账号记录解析，**不接受前端传入**（框架文档 8.2）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.token_revocation import get_token_revocation_store
from app.db.session import get_db
from app.deps import get_current_user, get_token_payload
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
    if (
        user is None
        or user.is_deleted
        or not verify_password(body.password, user.password_hash or "")
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

    await get_token_revocation_store().ensure_available()
    session_id = uuid.uuid4().hex
    access_token = create_access_token(
        subject=str(user.id),
        tenant_id=user.tenant_id,
        role=user.role,
        extra_claims={"sid": session_id},
    )
    refresh_token = create_refresh_token(
        subject=str(user.id),
        tenant_id=user.tenant_id,
        role=user.role,
        extra_claims={"sid": session_id},
    )
    await audit_operation(db, request, user, action="login", resource_type="auth")
    await db.commit()
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


@router.post(
    "/auth/refresh",
    response_model=APIResponse[TokenResponse],
    summary="刷新令牌",
    description="使用刷新令牌获取新的访问令牌",
    tags=["鉴权"],
)
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TokenResponse]:
    """刷新访问令牌"""
    # 从Authorization header获取refresh token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的授权头")

    refresh_token_str = auth_header[len("Bearer ") :]

    try:
        payload = decode_token(refresh_token_str, expected_type=TokenType.REFRESH)
        await get_token_revocation_store().assert_active(payload)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效或已过期"
        ) from exc

    # 验证用户是否存在且活跃
    user_id = payload.get("sub")
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == payload.get("tenant_id"))
    )
    user = result.scalar_one_or_none()

    if not user or user.is_deleted or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")

    await get_token_revocation_store().consume_refresh(payload)
    # 保留会话 ID，使退出能够同时吊销刷新前后签发的访问令牌。
    access_token = create_access_token(
        subject=str(user.id),
        tenant_id=user.tenant_id,
        role=user.role,
        extra_claims={"sid": payload["sid"]},
    )
    new_refresh_token = create_refresh_token(
        subject=str(user.id),
        tenant_id=user.tenant_id,
        role=user.role,
        extra_claims={"sid": payload["sid"]},
    )
    await audit_operation(db, request, user, action="refresh", resource_type="auth")
    await db.commit()

    return APIResponse(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/auth/logout",
    response_model=APIResponse[dict],
    summary="退出登录",
    description="退出当前登录状态",
    tags=["鉴权"],
)
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """退出登录"""
    await get_token_revocation_store().revoke_session(payload)
    await audit_operation(db, request, user, action="logout", resource_type="auth")
    await db.commit()
    return APIResponse(
        data={"message": "退出成功"},
        trace_id=_trace_id(request),
    )


@router.get(
    "/auth/codes",
    response_model=APIResponse[list[str]],
    summary="获取用户权限码",
    description="返回当前用户的权限码列表",
    tags=["鉴权"],
)
async def get_access_codes(
    request: Request,
    user: User = Depends(get_current_user),
) -> APIResponse[list[str]]:
    """获取用户权限码"""
    from app.core.security import get_role_profile

    # 获取用户角色的权限列表
    profile = get_role_profile(user.role)
    codes = [perm.value for perm in profile.permissions]

    return APIResponse(
        data=codes,
        trace_id=_trace_id(request),
    )
