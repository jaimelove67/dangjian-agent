"""本人改密、平台审批和真实登录会话管理。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import identity_stamp
from app.core.tenant import bypass_tenant_filter
from app.db.session import get_db
from app.deps import get_current_user, get_token_payload
from app.models.account_security import LoginSession
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.services import account_security_service as service
from app.services.identity_service import IdentityService, masked_username

router = APIRouter()


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=8, max_length=72)
    confirmation: SecretStr = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def safe_password(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if len(text.encode("utf-8")) > 72 or text.strip() != text:
            raise ValueError("密码不得超过72字节，首尾不得为空白")
        return value


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=300)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approved", "rejected"]
    comment: str = Field(min_length=2, max_length=300)
    version: int = Field(ge=1)


@router.get("/auth/password-state")
async def password_state(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> APIResponse:
    return APIResponse(data=await service.own_state(db, user))


@router.post("/auth/password-change")
async def change_password(
    body: ChangeBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    if body.password.get_secret_value() != body.confirmation.get_secret_value():
        raise HTTPException(422, "两次新密码不一致")
    await service.change(
        db, user, body.current.get_secret_value(), body.password.get_secret_value()
    )
    await audit_operation(
        db, request, user, action="self_password_change", resource_type="password"
    )
    await db.commit()
    return APIResponse(data={"message": "修改成功，请重新登录"})


@router.post("/auth/password-requests")
async def apply_password(
    body: ApplyBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    row = await service.apply(db, user, body.reason)
    await audit_operation(
        db,
        request,
        user,
        action="password_request",
        resource_type="password_request",
        resource_id=row.id,
    )
    payload = await service.request_payload(db, row)
    await db.commit()
    return APIResponse(data=payload)


async def platform_tenant(db: AsyncSession, user: User, tenant_id: str | None) -> Tenant:
    from app.services.identity_service import is_platform_admin

    if not await is_platform_admin(db, user):
        raise HTTPException(403, "仅平台管理员可以审核改密申请")
    return await IdentityService(db, user).tenant(tenant_id)


@router.get("/admin/password-requests")
async def requests(
    tenant_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    tenant = await platform_tenant(db, user, tenant_id)
    rows = await service.history(db, str(tenant.id))
    return APIResponse(data={"items": [await service.request_payload(db, r) for r in rows]})


@router.post("/admin/password-requests/{record_id}/review")
async def review_password(
    record_id: str,
    body: ReviewBody,
    request: Request,
    tenant_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    tenant = await platform_tenant(db, user, tenant_id)
    row = await service.review(
        db, user, str(tenant.id), record_id, body.decision, body.comment, body.version
    )
    await audit_operation(
        db,
        request,
        user,
        action="password_request_" + body.decision,
        resource_type="password_request",
        resource_id=row.id,
    )
    payload = await service.request_payload(db, row)
    await db.commit()
    return APIResponse(data=payload)


async def managed_tenant(db: AsyncSession, user: User, tenant_id: str | None) -> Tenant:
    if user.role not in {UserRole.SYSTEM_ADMIN, UserRole.SCHOOL_ADMIN}:
        raise HTTPException(403, "无会话管理权限")
    return await IdentityService(db, user).tenant(tenant_id)


@router.get("/admin/login-sessions")
async def sessions(
    tenant_id: str | None = None,
    user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    tenant = await managed_tenant(db, user, tenant_id)
    with bypass_tenant_filter():
        rows = (
            await db.execute(
                select(LoginSession, User)
                .join(User, User.id == LoginSession.user_id)
                .where(LoginSession.tenant_id == tenant.id, User.tenant_id == tenant.id)
                .order_by(LoginSession.created_at.desc())
                .limit(500)
            )
        ).all()
    return APIResponse(
        data={
            "items": [
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "user_id": row.user_id,
                    "username": masked_username(account.username),
                    "client_label": row.client_label,
                    "ip": row.ip_address,
                    "last_seen_at": row.updated_at,
                    "created_at": row.created_at,
                    "expires_at": row.expires_at,
                    "is_current": row.id == payload.get("sid"),
                    "is_active": tenant.is_active
                    and not row.is_deleted
                    and not row.revoked_at
                    and row.expires_at > datetime.utcnow()
                    and account.is_active
                    and not account.is_deleted
                    and row.identity_stamp == identity_stamp(account),
                }
                for row, account in rows
            ]
        }
    )


@router.post("/admin/login-sessions/{record_id}/revoke")
async def revoke_session(
    record_id: str,
    request: Request,
    tenant_id: str | None = None,
    user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    tenant = await managed_tenant(db, user, tenant_id)
    if record_id == payload.get("sid"):
        raise HTTPException(409, "请从头像菜单退出当前会话")
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(LoginSession)
                .where(LoginSession.id == record_id, LoginSession.tenant_id == tenant.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "会话不存在")
    row.revoked_at = row.revoked_at or datetime.utcnow()
    await audit_operation(
        db,
        request,
        user,
        action="revoke_session",
        resource_type="login_session",
        resource_id=row.id,
    )
    await db.commit()
    return APIResponse(data={"message": "会话已撤销"})
