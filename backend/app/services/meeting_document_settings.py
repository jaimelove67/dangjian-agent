"""学校会议文书设置：抬头、通知要求和记录说明。

学校设置作为默认值，院系或支部可覆盖；设置只影响之后生成的草稿和导出文书，
不追溯改写已审核归档记录。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import tenant_config
from app.models.org import OrgUnit
from app.models.tenant import Tenant

FIELDS = ("header", "notice_footer", "record_footer")


def _from_config(config: dict[str, Any]) -> dict[str, str]:
    return {
        "header": str(config.get("meeting_document_header", "") or ""),
        "notice_footer": str(config.get("meeting_notice_footer", "") or ""),
        "record_footer": str(config.get("meeting_record_footer", "") or ""),
    }


async def get_meeting_document_settings(
    db: AsyncSession, tenant_id: str, org_unit_id: str | None = None
) -> dict[str, str]:
    tenant = (
        await db.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if tenant is None:
        return {field: "" for field in FIELDS}
    config = tenant.config or {}
    settings = _from_config(config)
    if not org_unit_id:
        return settings
    overrides = config.get("meeting_document_by_org") or {}
    if not isinstance(overrides, dict):
        return settings
    current: str | None = org_unit_id
    visited: set[str] = set()
    while current and current not in visited and len(visited) < 12:
        visited.add(current)
        value = overrides.get(current)
        if isinstance(value, dict):
            return {**settings, **{field: str(value.get(field, "") or "") for field in FIELDS}}
        current = await db.scalar(
            select(OrgUnit.parent_id).where(
                OrgUnit.id == current,
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.is_deleted.is_(False),
            )
        )
    return settings


async def save_meeting_document_settings(
    db: AsyncSession,
    tenant_id: str,
    values: dict[str, Any],
    org_unit_id: str | None = None,
) -> dict[str, str]:
    clean = {field: str(values.get(field, "") or "").strip() for field in FIELDS}
    if org_unit_id:
        tenant = (
            await db.execute(
                select(Tenant).where(
                    Tenant.id == tenant_id,
                    Tenant.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise LookupError("当前账号所属租户尚未登记")
        raw_overrides = (tenant.config or {}).get("meeting_document_by_org")
        overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}
        overrides[str(org_unit_id)] = clean
        await tenant_config.save(db, tenant_id, {"meeting_document_by_org": overrides})
    else:
        await tenant_config.save(
            db,
            tenant_id,
            {
                "meeting_document_header": clean["header"],
                "meeting_notice_footer": clean["notice_footer"],
                "meeting_record_footer": clean["record_footer"],
            },
        )
    return await get_meeting_document_settings(db, tenant_id, org_unit_id)


def apply_document_settings(
    text: str,
    settings: dict[str, str],
    *,
    footer: str = "",
) -> str:
    header = settings.get("header", "").strip()
    footer_text = settings.get(footer, "").strip() if footer else ""
    parts = []
    if header:
        parts.append(header)
    parts.append(text)
    if footer_text:
        parts.append(footer_text)
    return "\n".join(part for part in parts if part)
