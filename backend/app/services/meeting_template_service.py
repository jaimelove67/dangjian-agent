"""会议文书版式模板的读取、草稿保存、发布和继承。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting_template import MeetingDocumentTemplate
from app.models.org import OrgUnit
from app.services.file_store import save_original

SECTION_KEYS = ("notice", "agenda", "sources", "record", "decisions", "footer")
DEFAULT_SECTION_TITLES = {
    "notice": "会议通知",
    "agenda": "会议议题",
    "sources": "学习资料",
    "record": "会议记录",
    "decisions": "决议与表决",
    "footer": "说明",
}
DEFAULT_LABELS = {
    "meeting_time": "会议时间",
    "location": "会议地点",
    "host": "主持人",
    "recorder": "记录人",
    "attendance": "参加人数",
}


def default_schema() -> dict[str, Any]:
    return {
        "sections": [
            {"key": key, "title": DEFAULT_SECTION_TITLES[key], "enabled": True}
            for key in SECTION_KEYS
        ],
        "labels": dict(DEFAULT_LABELS),
    }


def normalize_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return default_schema()
    labels = value.get("labels") if isinstance(value.get("labels"), dict) else {}
    raw_sections = value.get("sections") if isinstance(value.get("sections"), list) else []
    by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for item in raw_sections:
        if not isinstance(item, dict) or item.get("key") not in SECTION_KEYS:
            continue
        key = str(item["key"])
        title = str(item.get("title", "")).strip() or DEFAULT_SECTION_TITLES[key]
        if key not in by_key:
            ordered_keys.append(key)
        by_key[key] = {
            "key": key,
            "title": title[:100],
            "enabled": bool(item.get("enabled", True)),
        }
    for key in SECTION_KEYS:
        if key not in ordered_keys:
            ordered_keys.append(key)
            by_key[key] = {
                "key": key,
                "title": DEFAULT_SECTION_TITLES[key],
                "enabled": True,
            }
    sections = [by_key[key] for key in ordered_keys]
    sections = [item for item in sections if item["key"] != "footer"] + [
        item for item in sections if item["key"] == "footer"
    ]
    sections[-1]["enabled"] = True  # 统一说明固定在最后且不能隐藏
    return {
        "sections": sections,
        "labels": {
            key: str(labels.get(key, DEFAULT_LABELS[key]) or DEFAULT_LABELS[key])[:50]
            for key in DEFAULT_LABELS
        },
    }


def _word_meta(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    value = schema.get("word_template")
    return value if isinstance(value, dict) else None


def _with_meta(schema: dict[str, Any], row: MeetingDocumentTemplate | None) -> dict[str, Any]:
    result = normalize_schema(schema)
    word_template = _word_meta(schema)
    if word_template:
        result["word_template"] = word_template
    result["version"] = row.version if row else 0
    result["template_id"] = str(row.id) if row else ""
    result["org_unit_id"] = row.org_unit_id if row else ""
    return result


async def _word_meta_for_scope(
    db: AsyncSession, tenant_id: str, org_unit_id: str
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(MeetingDocumentTemplate)
            .where(
                MeetingDocumentTemplate.tenant_id == tenant_id,
                MeetingDocumentTemplate.org_unit_id == org_unit_id,
                MeetingDocumentTemplate.is_deleted.is_(False),
            )
            .order_by(MeetingDocumentTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _word_meta(row.schema_data) if row else None


async def _published_for(
    db: AsyncSession, tenant_id: str, org_unit_id: str
) -> MeetingDocumentTemplate | None:
    return (
        await db.execute(
            select(MeetingDocumentTemplate)
            .where(
                MeetingDocumentTemplate.tenant_id == tenant_id,
                MeetingDocumentTemplate.org_unit_id == org_unit_id,
                MeetingDocumentTemplate.status == "published",
                MeetingDocumentTemplate.is_deleted.is_(False),
            )
            .order_by(MeetingDocumentTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_effective_template(
    db: AsyncSession, tenant_id: str, org_unit_id: str | None = None
) -> dict[str, Any]:
    current = org_unit_id or ""
    visited: set[str] = set()
    while current and current not in visited and len(visited) < 12:
        visited.add(current)
        row = await _published_for(db, tenant_id, current)
        if row:
            return _with_meta(row.schema_data, row)
        current = await db.scalar(
            select(OrgUnit.parent_id).where(
                OrgUnit.id == current,
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.is_deleted.is_(False),
            )
        )
    row = await _published_for(db, tenant_id, "")
    return _with_meta(row.schema_data if row else default_schema(), row)


async def get_template_state(
    db: AsyncSession, tenant_id: str, org_unit_id: str = ""
) -> dict[str, Any]:
    published = await _published_for(db, tenant_id, org_unit_id)
    draft = (
        await db.execute(
            select(MeetingDocumentTemplate)
            .where(
                MeetingDocumentTemplate.tenant_id == tenant_id,
                MeetingDocumentTemplate.org_unit_id == org_unit_id,
                MeetingDocumentTemplate.status == "draft",
                MeetingDocumentTemplate.is_deleted.is_(False),
            )
            .order_by(MeetingDocumentTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "draft": _with_meta(draft.schema_data, draft) if draft else None,
        "published": _with_meta(published.schema_data, published) if published else None,
        "effective": await get_effective_template(db, tenant_id, org_unit_id),
        "default_schema": default_schema(),
    }


async def save_draft(
    db: AsyncSession,
    tenant_id: str,
    org_unit_id: str,
    schema: dict[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    normalized = normalize_schema(schema)
    draft = (
        await db.execute(
            select(MeetingDocumentTemplate)
            .where(
                MeetingDocumentTemplate.tenant_id == tenant_id,
                MeetingDocumentTemplate.org_unit_id == org_unit_id,
                MeetingDocumentTemplate.status == "draft",
                MeetingDocumentTemplate.is_deleted.is_(False),
            )
            .order_by(MeetingDocumentTemplate.version.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    word_meta = _word_meta(schema)
    if not word_meta:
        word_meta = (
            _word_meta(draft.schema_data)
            if draft
            else await _word_meta_for_scope(db, tenant_id, org_unit_id)
        )
    if word_meta:
        normalized["word_template"] = word_meta
    if draft:
        draft.schema_data = normalized
        draft.created_by = actor_id
    else:
        max_version = await db.scalar(
            select(func.max(MeetingDocumentTemplate.version)).where(
                MeetingDocumentTemplate.tenant_id == tenant_id,
                MeetingDocumentTemplate.org_unit_id == org_unit_id,
                MeetingDocumentTemplate.is_deleted.is_(False),
            )
        )
        draft = MeetingDocumentTemplate(
            tenant_id=tenant_id,
            org_unit_id=org_unit_id,
            status="draft",
            version=(max_version or 0) + 1,
            schema_data=normalized,
            created_by=actor_id,
        )
        db.add(draft)
    await db.flush()
    return _with_meta(draft.schema_data, draft)


async def publish_template(
    db: AsyncSession,
    tenant_id: str,
    org_unit_id: str,
    schema: dict[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    normalized = normalize_schema(schema)
    word_meta = await _word_meta_for_scope(db, tenant_id, org_unit_id)
    if word_meta:
        normalized["word_template"] = word_meta
    await db.execute(
        update(MeetingDocumentTemplate)
        .where(
            MeetingDocumentTemplate.tenant_id == tenant_id,
            MeetingDocumentTemplate.org_unit_id == org_unit_id,
            MeetingDocumentTemplate.status == "published",
            MeetingDocumentTemplate.is_deleted.is_(False),
        )
        .values(status="superseded")
    )
    max_version = await db.scalar(
        select(func.max(MeetingDocumentTemplate.version)).where(
            MeetingDocumentTemplate.tenant_id == tenant_id,
            MeetingDocumentTemplate.org_unit_id == org_unit_id,
            MeetingDocumentTemplate.is_deleted.is_(False),
        )
    )
    await db.execute(
        delete(MeetingDocumentTemplate).where(
            MeetingDocumentTemplate.tenant_id == tenant_id,
            MeetingDocumentTemplate.org_unit_id == org_unit_id,
            MeetingDocumentTemplate.status == "draft",
        )
    )
    row = MeetingDocumentTemplate(
        tenant_id=tenant_id,
        org_unit_id=org_unit_id,
        status="published",
        version=(max_version or 0) + 1,
        schema_data=normalized,
        created_by=actor_id,
        published_by=actor_id,
        published_at=func.now(),
    )
    db.add(row)
    await db.flush()
    return _with_meta(row.schema_data, row)


async def save_word_template(
    db: AsyncSession,
    tenant_id: str,
    org_unit_id: str,
    content: bytes,
    file_name: str,
    actor_id: str,
) -> dict[str, Any]:
    doc_id = f"meeting-template-{uuid.uuid4().hex}"
    stored = save_original(tenant_id, doc_id, 1, content, file_name)
    metadata = {
        **stored,
        "doc_id": doc_id,
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    state = await get_template_state(db, tenant_id, org_unit_id)
    base = state["draft"] or state["published"] or state["default_schema"]
    schema = normalize_schema(base)
    schema["word_template"] = metadata
    return await save_draft(db, tenant_id, org_unit_id, schema, actor_id)
