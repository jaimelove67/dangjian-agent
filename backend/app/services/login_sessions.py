"""Persistent revocation supplements Redis refresh replay protection."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError
from app.models.account_security import LoginSession


async def assert_active_session(db: AsyncSession, payload: dict) -> None:
    if not payload.get("sid"):
        return
    row = (
        await db.execute(
            select(LoginSession).where(
                LoginSession.id == payload["sid"],
                LoginSession.tenant_id == payload["tenant_id"],
                LoginSession.user_id == payload["sub"],
                LoginSession.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at or row.expires_at <= datetime.utcnow():
        raise TokenError("登录会话已失效，请重新登录")
