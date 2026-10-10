"""FastAPI 依赖注入

提供鉴权、租户上下文与权限校验依赖：

- ``get_token_payload`` / ``get_current_user``：解析并校验 JWT，加载当前用户；
- ``get_current_tenant``：从登录态获取租户 ID（不接受前端传入）；
- ``require_roles`` / ``require_permissions``：路由级权限装饰（依赖工厂）。

认证成功后会在请求生命周期内写入租户上下文（供数据访问层自动过滤），
请求结束后清理，避免上下文泄漏。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import tenant_config
from app.core.security import (
    Permission,
    TokenError,
    TokenType,
    decode_token,
    has_permission,
    resolve_data_level,
)
from app.core.tenant import clear_tenant_context, set_tenant_context
from app.core.token_revocation import get_token_revocation_store
from app.db.session import get_db
from app.models.user import User, UserRole

# auto_error=False：由本模块返回统一的中文错误，而非 FastAPI 默认英文
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "未认证") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_token_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """解析并校验访问令牌，返回载荷"""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("缺少访问令牌")
    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
        await get_token_revocation_store().assert_active(payload)
        return payload
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc


async def get_current_user(
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[User, None]:
    """获取当前用户，并在请求期间注入租户上下文"""
    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id or not tenant_id:
        raise _unauthorized("令牌缺少必要声明（sub / tenant_id）")

    # 先写入租户上下文，使加载用户时自动受租户过滤保护
    set_tenant_context(str(tenant_id), user_id=str(user_id))
    try:
        result = await db.execute(select(User).where(User.id == str(user_id)))
        user = result.scalar_one_or_none()
        if user is None or user.is_deleted or str(user.tenant_id) != str(tenant_id):
            raise _unauthorized("用户不存在或不属于当前租户")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

        # 数据级别由角色推导（不接受前端传入）
        role = user.role or UserRole.MEMBER
        set_tenant_context(
            str(tenant_id),
            user_id=str(user_id),
            data_level=resolve_data_level(role).value,
        )
        await tenant_config.load(db, str(tenant_id))
        from app.services.org_scope import knowledge_org_ids

        user.knowledge_org_ids = await knowledge_org_ids(db, user)
        yield user
    finally:
        clear_tenant_context()


async def get_current_tenant(
    payload: dict = Depends(get_token_payload),
) -> str:
    """从登录态获取租户 ID"""
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise _unauthorized("令牌缺少租户声明")
    return str(tenant_id)


def require_roles(*roles: UserRole) -> Callable[..., Any]:
    """依赖工厂：要求当前用户属于指定角色之一"""
    allowed = set(roles)

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _checker


def require_permissions(*permissions: Permission) -> Callable[..., Any]:
    """依赖工厂：要求当前用户具备全部指定权限点"""
    required = list(permissions)

    async def _checker(user: User = Depends(get_current_user)) -> User:
        role = user.role or UserRole.MEMBER
        missing = [p.value for p in required if not has_permission(role, p)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：缺少 {', '.join(missing)}",
            )
        return user

    return _checker
