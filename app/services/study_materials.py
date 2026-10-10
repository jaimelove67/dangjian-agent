"""从真实授权知识库选取学习材料，历史资料在读取时再次检查权限。"""

import hashlib
import re
from datetime import date
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.org import OrgUnit
from app.models.user import User
from app.rag.retrieval.access import (
    apply_knowledge_access,
    execute_knowledge_query,
    knowledge_filters,
)


async def _org_ancestors(db: AsyncSession, user: User, org_id: str) -> list[str]:
    ancestors: list[str] = []
    while org_id and org_id not in ancestors:
        org = (
            await db.execute(
                select(OrgUnit).where(
                    OrgUnit.id == org_id,
                    OrgUnit.tenant_id == str(user.tenant_id),
                    OrgUnit.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            break
        ancestors.append(str(org.id))
        org_id = org.parent_id
    return ancestors


async def material_statement(
    db: AsyncSession, user: User, org_id: str, *, historical: bool = False, on: date | None = None
) -> Select:
    """同时满足操作者可见范围及计划目标组织的适用范围。"""
    stmt = apply_knowledge_access(
        select(KnowledgeDoc), knowledge_filters(user, include_expired=historical), chunks=False
    )
    ancestors = await _org_ancestors(db, user, org_id)
    stmt = stmt.where(
        or_(
            KnowledgeDoc.visibility.in_(["public", "school"]),
            KnowledgeDoc.doc_metadata["org_unit_id"].as_string().in_(ancestors),
        )
    )
    if not historical and on:
        stmt = stmt.where(
            KnowledgeDoc.effective_date <= on,
            or_(KnowledgeDoc.expiration_date.is_(None), KnowledgeDoc.expiration_date >= on),
        )
    return stmt


async def source_snapshots(db: AsyncSession, documents: list[KnowledgeDoc]) -> list[dict[str, Any]]:
    """保存确切文件版本与原文摘录，后续生成只使用这些真实字段。"""
    chunks_by_doc: dict[str, Any] = {}
    if documents:
        # 文档已通过授权；片段仍需与文档租户一致，不读取失效的旧片段。
        stmt = (
            select(EmbeddingChunk)
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(
                KnowledgeDoc.id.in_([document.id for document in documents]),
                EmbeddingChunk.tenant_id == KnowledgeDoc.tenant_id,
                EmbeddingChunk.is_deleted.is_(False),
            )
            .distinct(EmbeddingChunk.doc_id)
            .order_by(EmbeddingChunk.doc_id, EmbeddingChunk.sequence, EmbeddingChunk.id)
        )
        chunks = (await execute_knowledge_query(db, stmt)).scalars().all()
        for chunk in chunks:
            chunks_by_doc.setdefault(chunk.doc_id, chunk)
    sources = []
    for document in documents:
        chunk = chunks_by_doc.get(document.id)
        excerpt = chunk.content[:2000] if chunk else (document.summary or "")[:2000]
        sources.append(
            jsonable_encoder(
                {
                    "doc_id": document.doc_id,
                    "title": document.title,
                    "issuer": document.issuer,
                    "file_name": document.file_name,
                    "doc_number": document.doc_number,
                    "effective_date": document.effective_date,
                    "expiration_date": document.expiration_date,
                    "visibility": document.visibility,
                    "level": document.level,
                    "security_level": document.security_level,
                    "status": document.status,
                    "org_unit_id": (document.doc_metadata or {}).get("org_unit_id"),
                    "content_revision": (document.doc_metadata or {}).get("content_revision", 1),
                    "summary": document.summary or "",
                    "excerpt": excerpt,
                    "chunk_id": chunk.chunk_id if chunk else None,
                    "article": chunk.article if chunk else None,
                    "start": 0,
                    "end": len(excerpt),
                    "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                }
            )
        )
    return sources


async def selected_sources(
    db: AsyncSession, user: User, org_id: str, doc_ids: list[str], *, on: date | None = None
) -> list[dict[str, Any]]:
    """不可通过提交伪造的标题、引用或跨组织文档绕过选择器。"""
    ids = list(dict.fromkeys(doc_ids))
    if not ids:
        return []
    stmt = await material_statement(db, user, org_id, on=on)
    documents = (
        (await execute_knowledge_query(db, stmt.where(KnowledgeDoc.doc_id.in_(ids))))
        .scalars()
        .all()
    )
    by_id = {document.doc_id: document for document in documents}
    if set(by_id) != set(ids):
        raise HTTPException(422, "所选材料含无权限、已失效、未生效或不适用的文件，请重新选择")
    return await source_snapshots(db, [by_id[doc_id] for doc_id in ids])


async def recommend_sources(
    db: AsyncSession,
    user: User,
    org_id: str,
    topics: list[str],
    *,
    on: date,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """按真实文件标题、摘要及标签匹配，缺少依据时返回空列表。"""
    terms = [
        part
        for text in ([query] if query else topics)
        for part in re.split(r"[\s,，、;；]+", text or "")
        if part
    ][:12]
    if not terms:
        return []
    stmt = await material_statement(db, user, org_id, on=on)
    conditions = []
    for term in terms:
        conditions.extend(
            (
                KnowledgeDoc.title.contains(term, autoescape=True),
                KnowledgeDoc.summary.contains(term, autoescape=True),
                KnowledgeDoc.tags.any(term),
            )
        )
    documents = (
        (
            await execute_knowledge_query(
                db,
                stmt.where(or_(*conditions))
                .order_by(KnowledgeDoc.effective_date.desc(), KnowledgeDoc.doc_id)
                .limit(20),
            )
        )
        .scalars()
        .all()
    )
    return await source_snapshots(db, list(documents))


async def visible_sources(
    db: AsyncSession, user: User, org_id: str, saved: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """读取历史快照前复核当前权限；资料降权/删除后不得泄露旧摘录。"""
    if not saved:
        return [], ["政策依据待补"], False
    stmt = await material_statement(db, user, org_id, historical=True)
    ids = [source["doc_id"] for source in saved]
    documents = (
        (await execute_knowledge_query(db, stmt.where(KnowledgeDoc.doc_id.in_(ids))))
        .scalars()
        .all()
    )
    current = {document.doc_id: document for document in documents}
    visible, warnings, restricted = [], [], False
    for source in saved:
        document = current.get(source["doc_id"])
        if document is None:
            restricted = True
            warnings.append("关联资料已删除、不适用或当前无权访问；原有内容需重新核验")
            continue
        copy = dict(source)
        copy["current_status"] = document.status
        copy["current_revision"] = (document.doc_metadata or {}).get("content_revision", 1)
        if document.status != "effective" or (
            document.expiration_date and document.expiration_date < date.today()
        ):
            warnings.append(f"{document.title}已失效或废止，仅作历史依据")
        if copy["current_revision"] != copy["content_revision"]:
            warnings.append(f"{document.title}已更新，当前展示历史版本 {copy['content_revision']}")
        visible.append(copy)
    return visible, list(dict.fromkeys(warnings)), restricted
