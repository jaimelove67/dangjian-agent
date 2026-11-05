"""外部党建资料抓取、审核与知识库发布。

只抓取配置白名单内的公开页面，不执行登录、不绕过访问控制。抓取结果先进入
待审核台账，人工审核通过后才写入知识库，供三会一课议程草稿引用。
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import tenant_config
from app.models.external import ExternalFetchState, ExternalUpdate
from app.models.knowledge import KnowledgeDoc
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User

#: 仅允许官方公开来源。新增来源必须同时加入域名白名单，不能接受任意 URL。
EXTERNAL_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("共产党员网", "https://www.12371.cn/", "12371.cn"),
    ("求是网", "https://www.qstheory.cn/", "qstheory.cn"),
)

#: 学校可维护的资料关注方向。抓取和推荐都按本校关注方向筛选，避免所有学校
#: 都收到同一批资料。标签只影响公开资料的筛选，不改变审核和引用规则。
FOCUS_TOPICS: dict[str, tuple[str, ...]] = {
    "理论武装": ("习近平", "总书记", "重要讲话", "全会", "理论", "思想", "党性", "长征"),
    "全面从严治党": ("全面从严治党", "管党治党", "党纪", "纪律", "作风", "反腐", "廉政"),
    "基层组织建设": ("基层", "支部", "组织建设", "组织力", "党员队伍", "治理"),
    "发展党员": ("发展党员", "入党", "积极分子", "预备党员", "党员发展"),
    "师德师风": ("师德", "教师", "育人", "教育", "学校"),
    "科技创新": ("科技", "创新", "人工智能", "新质生产力", "高质量发展"),
    "生态文明": ("生态", "绿色", "黄河", "环境", "低碳"),
}
DEFAULT_FOCUS_TOPICS: tuple[str, ...] = (
    "理论武装",
    "全面从严治党",
    "基层组织建设",
    "发展党员",
)
SOURCE_MAP: dict[str, tuple[str, str]] = {
    name: (url, domain) for name, url, domain in EXTERNAL_SOURCES
}
DEFAULT_SOURCE_NAMES: tuple[str, ...] = tuple(SOURCE_MAP)

MAX_ITEMS_PER_SOURCE = 10
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_SUMMARY_CHARS = 1200
USER_AGENT = "party-agent/1.0 (+official-source-review)"
DATE_IN_URL = re.compile(r"/(20\d{2})[-/]?(\d{2})[-/]?(\d{2})(?:/|[^0-9])")
ANCHOR = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
META_DESCRIPTION = re.compile(
    r'<meta[^>]+(?:name=["\']description["\']|property=["\']og:description["\'])[^>]+content=["\']([^"\']*)["\']',
    re.I | re.S,
)
PAGE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
SKIP_TITLE = {
    "首页",
    "更多",
    "下一页",
    "上一页",
    "登录",
    "注册",
    "网站地图",
    "关于我们",
    "联系我们",
    "返回顶部",
    "设为首页",
    "收藏本站",
}


def _clean_text(value: str) -> str:
    return SPACE.sub(" ", html.unescape(TAG.sub(" ", value or ""))).strip()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _published_date(url: str) -> datetime | None:
    match = DATE_IN_URL.search(url)
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups()))
    except ValueError:
        return None


def normalize_focus_topics(value: Any) -> list[str]:
    """把租户配置收敛为受支持的关注方向，未知标签不参与筛选。"""
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_FOCUS_TOPICS)
    topics: list[str] = []
    for item in value:
        topic = str(item).strip()
        if topic in FOCUS_TOPICS and topic not in topics:
            topics.append(topic)
    return topics[: len(FOCUS_TOPICS)]


def normalize_external_sources(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_SOURCE_NAMES)
    sources: list[str] = []
    for item in value:
        name = str(item).strip()
        if name in SOURCE_MAP and name not in sources:
            sources.append(name)
    return sources


async def get_external_sources(db: AsyncSession, tenant_id: str) -> list[str]:
    tenant = (
        await db.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if tenant is None:
        return list(DEFAULT_SOURCE_NAMES)
    value = (tenant.config or {}).get("external_source_names")
    return normalize_external_sources(value) if value is not None else list(DEFAULT_SOURCE_NAMES)


async def set_external_sources(db: AsyncSession, tenant_id: str, names: list[str]) -> list[str]:
    clean = normalize_external_sources(names)
    unknown = [name for name in names if name not in SOURCE_MAP]
    if unknown:
        raise HTTPException(422, f"存在不支持的外部资料来源：{'、'.join(unknown)}")
    await tenant_config.save(db, tenant_id, {"external_source_names": clean})
    return clean


async def get_focus_topics(
    db: AsyncSession,
    tenant_id: str,
    org_unit_id: str | None = None,
) -> list[str]:
    """读取有效关注方向；组织可覆盖学校默认，未覆盖时逐级继承。"""
    tenant = (
        await db.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if tenant is None:
        return list(DEFAULT_FOCUS_TOPICS)
    config = tenant.config or {}
    value = config.get("external_focus_topics")
    school_topics = (
        normalize_focus_topics(value) if value is not None else list(DEFAULT_FOCUS_TOPICS)
    )
    if not org_unit_id:
        return school_topics
    overrides = config.get("external_focus_by_org") or {}
    if not isinstance(overrides, dict):
        return school_topics
    current: str | None = org_unit_id
    visited: set[str] = set()
    while current and current not in visited and len(visited) < 12:
        visited.add(current)
        if current in overrides:
            return normalize_focus_topics(overrides[current])
        current = await db.scalar(
            select(OrgUnit.parent_id).where(
                OrgUnit.id == current,
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.is_deleted.is_(False),
            )
        )
    return school_topics


async def set_focus_topics(
    db: AsyncSession,
    tenant_id: str,
    topics: list[str],
    org_unit_id: str | None = None,
) -> list[str]:
    """保存学校默认或指定组织的关注方向，保留未修改的上级配置。"""
    if len(topics) != len(set(topics)):
        raise HTTPException(422, "关注方向不能重复")
    unknown = [item for item in topics if item not in FOCUS_TOPICS]
    if unknown:
        raise HTTPException(422, f"存在不支持的关注方向：{'、'.join(unknown)}")
    clean = normalize_focus_topics(topics)
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
        raw_overrides = (tenant.config or {}).get("external_focus_by_org")
        overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}
        overrides[str(org_unit_id)] = clean
        await tenant_config.save(db, tenant_id, {"external_focus_by_org": overrides})
    else:
        await tenant_config.save(db, tenant_id, {"external_focus_topics": clean})
    return clean


def matches_focus(text: str, topics: list[str]) -> bool:
    """空关注方向表示不筛选；否则标题或摘要命中一个方向即可。"""
    if not topics:
        return True
    normalized = " ".join(str(text or "").split())
    return any(keyword in normalized for topic in topics for keyword in FOCUS_TOPICS.get(topic, ()))


def _allowed_url(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if host != domain and not host.endswith("." + domain):
        return False
    if not DATE_IN_URL.search(parsed.path):
        return False
    return parsed.path.lower().endswith((".shtml", ".html", ".htm"))


def _title_from_page(html_text: str, fallback: str) -> str:
    match = PAGE_TITLE.search(html_text)
    if not match:
        return fallback
    title = _clean_text(match.group(1))
    for suffix in ("_共产党员网", "- 求是网", "-求是网", "_求是网"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title or fallback


def _summary_from_page(html_text: str) -> str:
    match = META_DESCRIPTION.search(html_text)
    if match:
        return _clean_text(match.group(1))[:MAX_SUMMARY_CHARS]
    text = SCRIPT_STYLE.sub(" ", html_text)
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", text, re.I | re.S)
    return _clean_text(" ".join(paragraphs))[:MAX_SUMMARY_CHARS]


def _links(html_text: str, base: str, domain: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for match in ANCHOR.finditer(html_text):
        url = urljoin(base, html.unescape(match.group(1)).strip())
        title = _clean_text(match.group(2))
        if (
            not title
            or title in SKIP_TITLE
            or len(title) < 6
            or len(title) > 120
            or not _allowed_url(url, domain)
        ):
            continue
        found.setdefault(
            url,
            {
                "title": title,
                "url": url,
                "published_at": _published_date(url),
            },
        )
        if len(found) >= MAX_ITEMS_PER_SOURCE:
            break
    return list(found.values())


async def _get(client: httpx.AsyncClient, url: str, domain: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    final_host = (response.url.host or "").lower()
    if final_host != domain and not final_host.endswith("." + domain):
        raise ValueError("页面重定向到非白名单来源")
    if len(response.content) > MAX_PAGE_BYTES:
        raise ValueError("页面内容超过抓取上限")
    return response.text


async def _article(
    client: httpx.AsyncClient, item: dict[str, Any], semaphore: asyncio.Semaphore
) -> dict[str, Any]:
    async with semaphore:
        try:
            page = await _get(client, item["url"], item["domain"])
        except Exception:
            page = ""
    title = _title_from_page(page, item["title"]) if page else item["title"]
    summary = _summary_from_page(page) if page else ""
    return {
        **item,
        "title": title,
        "summary": summary or title,
    }


async def _record_fetch_state(
    db: AsyncSession,
    tenant_id: str,
    started_at: datetime,
    *,
    added: int,
    skipped: int,
    filtered: int,
    errors: list[dict[str, str]],
) -> None:
    state = (
        await db.execute(
            select(ExternalFetchState)
            .where(
                ExternalFetchState.tenant_id == tenant_id,
                ExternalFetchState.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    finished_at = _now()
    if state is None:
        state = ExternalFetchState(tenant_id=tenant_id)
        db.add(state)
    state.last_started_at = started_at
    state.last_finished_at = finished_at
    if not errors:
        state.last_success_at = finished_at
    state.last_added = added
    state.last_skipped = skipped
    state.last_filtered = filtered
    state.last_error = "；".join(f"{item['source']}：{item['message']}" for item in errors)[:2000]
    await db.flush()


async def fetch_updates(db: AsyncSession, user: User) -> dict[str, Any]:
    """抓取白名单来源，保存尚未见过的公开条目为待审核资料。"""

    started_at = _now()
    tenant_id = str(user.tenant_id)
    focus_topics = await get_focus_topics(db, tenant_id)
    enabled_sources = await get_external_sources(db, tenant_id)
    source_entries = [(name, *SOURCE_MAP[name]) for name in enabled_sources if name in SOURCE_MAP]
    existing = set(
        (
            await db.execute(
                select(ExternalUpdate.content_hash).where(
                    ExternalUpdate.tenant_id == tenant_id,
                    ExternalUpdate.is_deleted.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    errors: list[dict[str, str]] = []
    fetched: list[dict[str, Any]] = []
    if not source_entries:
        errors.append({"source": "资料来源", "message": "当前未启用任何外部资料来源"})
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for source_name, source_url, domain in source_entries:
            try:
                page = await _get(client, source_url, domain)
                items = _links(page, source_url, domain)
            except Exception as exc:
                errors.append({"source": source_name, "message": str(exc)[:200]})
                continue
            fetched.extend({**item, "source_name": source_name, "domain": domain} for item in items)
        semaphore = asyncio.Semaphore(4)
        articles = await asyncio.gather(
            *[_article(client, item, semaphore) for item in fetched[:40]]
        )

    added = 0
    skipped = 0
    filtered = 0
    now = _now()
    for item in articles:
        if focus_topics and not matches_focus(f"{item['title']} {item['summary']}", focus_topics):
            filtered += 1
            continue
        digest = hashlib.sha256(item["url"].encode()).hexdigest()
        if digest in existing:
            skipped += 1
            continue
        existing.add(digest)
        db.add(
            ExternalUpdate(
                tenant_id=tenant_id,
                title=item["title"][:300],
                source_name=item["source_name"],
                source_url=item["url"][:1000],
                summary=item["summary"],
                published_at=item["published_at"],
                fetched_at=now,
                content_hash=digest,
                status="pending",
            )
        )
        added += 1
    await db.flush()
    await _record_fetch_state(
        db,
        tenant_id,
        started_at,
        added=added,
        skipped=skipped,
        filtered=filtered,
        errors=errors,
    )
    return {
        "added": added,
        "skipped": skipped,
        "filtered": filtered,
        "sources": len(source_entries),
        "focus_topics": focus_topics,
        "errors": errors,
    }


async def _publish_knowledge_doc(
    db: AsyncSession, row: ExternalUpdate, user: User, note: str
) -> KnowledgeDoc:
    doc_id = f"external-{str(user.tenant_id)[:8]}-{row.content_hash[:24]}"
    existing = (
        await db.execute(
            select(KnowledgeDoc).where(
                KnowledgeDoc.tenant_id == str(user.tenant_id),
                KnowledgeDoc.doc_id == doc_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    published = row.published_at.date() if row.published_at else date.today()
    doc = KnowledgeDoc(
        tenant_id=str(user.tenant_id),
        doc_id=doc_id,
        file_name="外部资料链接",
        title=row.title,
        issuer=row.source_name,
        level="central",
        visibility="public",
        security_level="public",
        effective_date=published,
        status="effective",
        authority="reference",
        validity="effective",
        review_status="published",
        reviewed_by=str(user.id),
        reviewed_at=_now(),
        review_note=(note or "外部官方来源审核通过")[:500],
        summary=row.summary or row.title,
        doc_metadata={
            "external": True,
            "source_name": row.source_name,
            "source_url": row.source_url,
            "external_update_id": str(row.id),
            "disclaimer": "外部公开资料，仅作学习参考；正式表述请核对原文。",
        },
        tags=["最新资料", "外部资料"],
    )
    db.add(doc)
    await db.flush()
    return doc


async def review_update(
    db: AsyncSession,
    user: User,
    update_id: str,
    decision: str,
    note: str,
) -> tuple[ExternalUpdate, KnowledgeDoc | None]:
    row = (
        await db.execute(
            select(ExternalUpdate)
            .where(
                ExternalUpdate.id == update_id,
                ExternalUpdate.tenant_id == str(user.tenant_id),
                ExternalUpdate.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "外部资料不存在")
    if row.status != "pending":
        raise HTTPException(409, "该资料已审核，不能重复处理")
    doc = None
    if decision == "approve":
        doc = await _publish_knowledge_doc(db, row, user, note)
        row.status = "approved"
        row.knowledge_doc_id = doc.doc_id
    else:
        row.status = "rejected"
    row.reviewed_by = str(user.id)
    row.reviewed_at = _now()
    row.review_note = note[:2000]
    await db.flush()
    return row, doc


async def review_updates_batch(
    db: AsyncSession,
    user: User,
    update_ids: list[str],
    decision: str,
    note: str,
) -> list[tuple[ExternalUpdate, KnowledgeDoc | None]]:
    """按输入顺序批量审核；任一资料已处理时整体回滚，避免半批状态。"""
    unique_ids = list(dict.fromkeys(update_ids))
    existing = (
        (
            await db.execute(
                select(ExternalUpdate).where(
                    ExternalUpdate.id.in_(unique_ids),
                    ExternalUpdate.tenant_id == str(user.tenant_id),
                    ExternalUpdate.is_deleted.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(existing) != len(unique_ids):
        raise HTTPException(404, "部分外部资料不存在")
    rows: list[tuple[ExternalUpdate, KnowledgeDoc | None]] = []
    for update_id in unique_ids:
        rows.append(await review_update(db, user, update_id, decision, note))
    return rows
