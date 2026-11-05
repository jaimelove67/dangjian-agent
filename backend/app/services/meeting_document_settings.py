"""学校会议文书设置：抬头、通知要求和记录说明。

设置只影响之后生成的草稿和导出文书，不追溯改写已审核归档记录。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import tenant_config


def get_meeting_document_settings(tenant_id: str) -> dict[str, str]:
    return {
        "header": str(tenant_config.get(tenant_id, "meeting_document_header", "") or ""),
        "notice_footer": str(tenant_config.get(tenant_id, "meeting_notice_footer", "") or ""),
        "record_footer": str(tenant_config.get(tenant_id, "meeting_record_footer", "") or ""),
    }


async def save_meeting_document_settings(
    db: AsyncSession, tenant_id: str, values: dict[str, Any]
) -> dict[str, str]:
    await tenant_config.save(
        db,
        tenant_id,
        {
            "meeting_document_header": str(values.get("header", "") or "").strip(),
            "meeting_notice_footer": str(values.get("notice_footer", "") or "").strip(),
            "meeting_record_footer": str(values.get("record_footer", "") or "").strip(),
        },
    )
    return get_meeting_document_settings(tenant_id)


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
