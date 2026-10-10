"""鉴权接口

- ``POST /api/v1/auth/login``：账号密码登录，签发访问 / 刷新令牌；
- ``GET  /api/v1/auth/me``：返回当前登录用户信息（敏感字段脱敏）。

租户标识从账号记录解析，**不接受前端传入**（框架文档 8.2）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_safe
from app.core.config import settings
from app.core.constants import AuditAction, AuditResult
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
    await write_audit_safe(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user_name=user.username,
        action=AuditAction.LOGIN,
        resource_type="auth",
        request_id=getattr(request.state, "trace_id", "-"),
        result=AuditResult.SUCCESS,
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
    from fastapi import Header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的授权头"
        )

    refresh_token_str = auth_header.replace("Bearer ", "")

    try:
        from app.core.security import decode_token, TokenType
        payload = decode_token(refresh_token_str, expected_type=TokenType.REFRESH)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌无效或已过期"
        )

    # 验证用户是否存在且活跃
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用"
        )

    # 签发新的访问令牌和刷新令牌
    access_token = create_access_token(
        subject=str(user.id), tenant_id=user.tenant_id, role=user.role
    )
    new_refresh_token = create_refresh_token(
        subject=str(user.id), tenant_id=user.tenant_id, role=user.role
    )

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
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """退出登录"""
    # TODO: 将token加入黑名单（需要Redis支持）
    await write_audit_safe(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user_name=user.username,
        action=AuditAction.LOGOUT,
        resource_type="auth",
        request_id=getattr(request.state, "trace_id", "-"),
        result=AuditResult.SUCCESS,
    )
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
