"""鉴权相关出入参"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.core.desensitization import mask_email, mask_phone


class LoginRequest(BaseModel):
    """登录请求（租户从账号解析，不接受前端传入）"""
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class TokenResponse(BaseModel):
    """令牌响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="访问令牌有效期（秒）")


class UserInfo(BaseModel):
    """当前用户信息（敏感字段脱敏）"""
    id: str
    username: str
    name: str
    role: str
    tenant_id: str
    org_unit_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    @classmethod
    def from_user(cls, user: Any) -> "UserInfo":
        return cls(
            id=str(user.id),
            username=user.username,
            name=user.name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            tenant_id=str(user.tenant_id),
            org_unit_id=str(user.org_unit_id) if user.org_unit_id else None,
            email=mask_email(user.email) if user.email else None,
            phone=mask_phone(user.phone) if user.phone else None,
        )
