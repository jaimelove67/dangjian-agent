"""All mutations lock the target user, so failed/concurrent changes cannot spend a grant."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.core.tenant import bypass_tenant_filter
from app.models.account_security import PasswordChange, PasswordRequest
from app.models.user import User, UserRole
from app.services.default_password import approved_reset_password
from app.services.identity_service import IdentityService, masked_username

SELF_ROLES = {UserRole.BRANCH_SECRETARY, UserRole.ORGANIZER, UserRole.MEMBER, UserRole.APPLICANT}


async def lock_account(db: AsyncSession, tenant_id: str, user_id: str) -> User:
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(User)
                .where(User.id == user_id, User.tenant_id == tenant_id, User.is_deleted.is_(False))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
    if row is None or not row.is_active:
        raise HTTPException(409, "账号不存在或已停用")
    return row


async def history(
    db: AsyncSession, tenant_id: str, user_id: str | None = None
) -> list[PasswordRequest]:
    with bypass_tenant_filter():
        stmt = select(PasswordRequest).where(
            PasswordRequest.tenant_id == tenant_id, PasswordRequest.is_deleted.is_(False)
        )
        if user_id:
            stmt = stmt.where(PasswordRequest.user_id == user_id)
        return list((await db.execute(stmt.order_by(PasswordRequest.created_at.desc()))).scalars())


async def used(db: AsyncSession, tenant_id: str, user_id: str) -> bool:
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(PasswordChange.id)
                .where(PasswordChange.tenant_id == tenant_id, PasswordChange.user_id == user_id)
                .limit(1)
            )
        ).first()
    return row is not None


async def request_payload(db: AsyncSession, row: PasswordRequest) -> dict[str, Any]:
    with bypass_tenant_filter():
        user = (
            await db.execute(
                select(User).where(User.id == row.user_id, User.tenant_id == row.tenant_id)
            )
        ).scalar_one_or_none()
        reviewer = (
            (await db.execute(select(User).where(User.id == row.reviewed_by))).scalar_one_or_none()
            if row.reviewed_by
            else None
        )
    result = row.dict()
    result.update(
        name=user.name if user else "已停用账号",
        username=masked_username(user.username) if user else "",
        role=user.role if user else None,
        reviewer_name=reviewer.name if reviewer else None,
    )
    return result


async def own_state(db: AsyncSession, user: User) -> dict[str, Any]:
    if user.role not in SELF_ROLES:
        raise HTTPException(403, "当前角色不开放自主修改密码")
    rows = await history(db, str(user.tenant_id), str(user.id))
    has_used = await used(db, str(user.tenant_id), str(user.id))
    payloads = [await request_payload(db, row) for row in rows]
    pending = next((r for r in payloads if r["status"] == "pending"), None)
    approved = next((r for r in payloads if r["status"] == "approved"), None)
    return {
        "used": has_used,
        "pending": pending,
        "approved": approved,
        "canChange": not has_used or bool(approved),
        "history": payloads,
    }


async def apply(db: AsyncSession, user: User, reason: str) -> PasswordRequest:
    user = await lock_account(db, str(user.tenant_id), str(user.id))
    state = await own_state(db, user)
    if not state["used"]:
        raise HTTPException(409, "首次修改可直接办理，无需申请")
    if state["pending"] or state["approved"]:
        raise HTTPException(409, "已有待审核或已批准的申请")
    row = PasswordRequest(tenant_id=user.tenant_id, user_id=user.id, reason=reason)
    db.add(row)
    await db.flush()
    return row


async def change(db: AsyncSession, user: User, current: str, password: str) -> None:
    user = await lock_account(db, str(user.tenant_id), str(user.id))
    state = await own_state(db, user)
    if not state["canChange"]:
        raise HTTPException(409, "自主修改次数已用完，请先申请一次修改授权")
    if not verify_password(current, user.password_hash):
        raise HTTPException(422, "当前密码不正确")
    if verify_password(password, user.password_hash):
        raise HTTPException(422, "新密码不能与当前密码相同")
    grant = None
    if state["used"]:
        grant = next(
            r
            for r in await history(db, str(user.tenant_id), str(user.id))
            if r.status == "approved"
        )
        grant.status = "consumed"
        grant.consumed_at = datetime.utcnow()
        grant.version += 1
    user.password_hash = hash_password(password)
    user.updated_at = datetime.utcnow()
    db.add(
        PasswordChange(
            tenant_id=user.tenant_id, user_id=user.id, request_id=grant.id if grant else None
        )
    )
    await db.flush()


async def review(
    db: AsyncSession,
    actor: User,
    tenant_id: str,
    request_id: str,
    decision: str,
    comment: str,
    version: int,
) -> PasswordRequest:
    if actor.role != UserRole.SYSTEM_ADMIN:
        raise HTTPException(403, "仅平台管理员可以审核改密申请")
    tenant = await IdentityService(db, actor).tenant(tenant_id)
    rows = await history(db, str(tenant.id))
    row = next((r for r in rows if r.id == request_id), None)
    if row is None:
        raise HTTPException(404, "申请不存在")
    target = await lock_account(db, str(tenant.id), str(row.user_id))
    # Re-read after obtaining the common account lock.
    with bypass_tenant_filter():
        await db.refresh(row)
    if row.version != version or row.status != "pending":
        raise HTTPException(409, "申请已处理，请刷新后重试")
    if target.role not in SELF_ROLES or not await used(db, str(tenant.id), str(target.id)):
        raise HTTPException(409, "该账号当前不适用再次改密流程")
    if decision == "approved":
        # Approval is a temporary-password reset, not the consumption of the
        # one-use self-change grant. Generate the password only in this server
        # process; only its hash is persisted or used by authentication.
        try:
            reset_password = approved_reset_password(tenant.name, target.name)
        except ValueError as exc:
            raise HTTPException(409, "账号资料不完整，暂时无法生成默认密码，请先完善学校名称和姓名") from exc
        target.password_hash = hash_password(reset_password)
        target.updated_at = datetime.utcnow()
    row.status, row.review_comment, row.reviewed_by = decision, comment, actor.id
    row.reviewed_at = datetime.utcnow()
    row.version += 1
    await db.flush()
    return row


async def cancel_requests(db: AsyncSession, tenant_id: str, user_id: str) -> None:
    for row in await history(db, tenant_id, user_id):
        if row.status in {"pending", "approved"}:
            row.status = "cancelled"
            row.version += 1
