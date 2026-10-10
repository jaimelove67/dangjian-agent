"""共用电子归档合规门禁；确认只对当前学校租户生效，不继承他校确认。"""

from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import ContentRevision
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.study import ArchivePolicyUpdate
from app.services.meeting_service import utc_now


async def archive_policy(db: AsyncSession, tenant_id: str, *, lock: bool = False) -> dict[str, Any]:
    """每次读取数据库，撤销确认后已归档数据也停止查询和导出。"""
    stmt = select(Tenant).where(Tenant.id == tenant_id, Tenant.is_deleted.is_(False))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    value = (tenant.config or {}).get("electronic_archive", {}) if tenant else {}
    return dict(value) if isinstance(value, dict) else {}


async def require_archive_policy(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """启用、版本、确认人与依据均须有效；配置字符串或残缺配置不能放行。"""
    policy = await archive_policy(db, tenant_id, lock=True)
    if not (
        policy.get("enabled") is True
        and type(policy.get("revision")) is int
        and policy["revision"] > 0
        and policy.get("confirmed_by")
        and policy.get("confirmed_at")
        and policy.get("evidence")
    ):
        raise HTTPException(
            403, "学校组织部门尚未确认电子记录效力，归档、历史归档查询及导出暂不可用"
        )
    return policy


async def save_archive_policy(
    db: AsyncSession, user: User, body: ArchivePolicyUpdate
) -> dict[str, Any]:
    """调用方校验学校权限；确认记录和历次撤销/重新确认永久保留。"""
    tenant = (
        await db.execute(
            select(Tenant)
            .where(Tenant.id == str(user.tenant_id), Tenant.is_deleted.is_(False))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(404, "请先登记当前学校租户")
    if tenant.tenant_type != "school":
        raise HTTPException(422, "电子记录效力确认必须登记在学校租户")
    current = (tenant.config or {}).get("electronic_archive", {})
    revision = current.get("revision", 0) if isinstance(current, dict) else 0
    if revision != body.expected_revision:
        raise HTTPException(409, "归档确认已变化，请刷新后重新确认")
    policy = jsonable_encoder(
        {
            "enabled": body.enabled,
            "revision": revision + 1,
            "confirmed_by": str(user.id),
            "confirmed_at": utc_now(),
            "evidence": body.evidence,
        }
    )
    tenant.config = {**(tenant.config or {}), "electronic_archive": policy}
    db.add(
        ContentRevision(
            tenant_id=str(user.tenant_id),
            resource_type="archive_policy",
            resource_id=str(user.tenant_id),
            revision=revision + 1,
            action="confirm" if body.enabled else "revoke",
            actor_id=str(user.id),
            reason=body.evidence,
            snapshot=policy,
        )
    )
    await db.flush()
    return policy
