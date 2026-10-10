"""知识文档服务

实现框架文档 5.2/5.3 的入库流程：元数据校验 → 文件解析 → 章条切分 → 落库。

切分得到的片段写入 ``embedding_chunks``；**涉密材料不入向量库**（仅保留文档记录，
走人工归档）。向量化（embedding）由检索链路（开发者B）后续补齐。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DocumentStatus
from app.core.tenant import get_tenant_id
from app.llm.base import DataLevel
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.exceptions import ParseError
from app.rag.loader import ParserRegistry, default_registry
from app.rag.privacy import content_level
from app.rag.splitter import ChapterArticleSplitter
from app.rules.document_metadata import MetadataValidationError, validate_document_metadata
from app.utils.datetime import to_date

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """文档不存在"""


class DocumentConflictError(Exception):
    """文档标识冲突"""


async def get_document(db: AsyncSession, *, doc_id: str) -> Optional[KnowledgeDoc]:
    """按文档标识查询文档"""
    stmt = select(KnowledgeDoc).where(
        KnowledgeDoc.doc_id == doc_id, KnowledgeDoc.is_deleted.is_(False)
    )
    if get_tenant_id():
        stmt = stmt.where(KnowledgeDoc.tenant_id == get_tenant_id())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    *,
    metadata: Mapping[str, Any],
    content: Optional[bytes] = None,
    file_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    parser_registry: Optional[ParserRegistry] = None,
    splitter: Optional[ChapterArticleSplitter] = None,
) -> tuple[KnowledgeDoc, int, Optional[int]]:
    """文档入库

    流程：元数据校验 → 文件解析 → 章条切分 → 落库。

    Args:
        metadata: 文档元数据（含 doc_id 等必填项）
        content: 文件字节流（可选）
        file_name: 文件名（用于选择解析器）
        tenant_id: 归属租户
        parser_registry: 解析器注册表
        splitter: 切分策略

    Returns:
        (文档对象, 生成的片段数, 页数)

    Raises:
        MetadataValidationError: 元数据校验失败
        DocumentConflictError: 文档标识已存在
    """
    # 1. 元数据校验（失败即拒绝入库）
    validation = validate_document_metadata(metadata)

    doc_id = str(metadata["doc_id"])
    if await get_document(db, doc_id=doc_id) is not None:
        raise DocumentConflictError(f"文档标识已存在: {doc_id}")

    # 2. 文件解析
    registry = parser_registry or default_registry
    parsed_text = ""
    page_count: Optional[int] = None
    if content is not None and file_name:
        parser = registry.get(file_name)
        logger.debug(
            "document_parsing_started",
            extra={"doc_id": doc_id, "parser": parser.name, "file_name": file_name},
        )
        parsed = parser.parse(content, file_name=file_name)
        parsed_text = parsed.text
        page_count = parsed.page_count
        logger.debug(
            "document_parsed",
            extra={
                "doc_id": doc_id,
                "text_length": len(parsed_text),
                "page_count": page_count,
            },
        )

    declared_level = DataLevel(metadata["security_level"])
    detected_level = content_level(
        "\n".join(
            [parsed_text]
            + [
                str(metadata.get(key) or "")
                for key in ("title", "issuer", "doc_number", "file_name", "summary")
            ]
        ),
        minimum=declared_level,
    )
    if detected_level != declared_level:
        raise MetadataValidationError(
            [f"文件内容需要至少标注为 {detected_level.value}，不能按低级别入库"]
        )
    if content is not None and validation.embedding_allowed and not parsed_text.strip():
        raise ParseError("文档不包含可解析文本")
    # 3. 落库文档
    document = KnowledgeDoc(
        tenant_id=tenant_id,
        doc_id=doc_id,
        file_name=str(metadata["file_name"]),
        title=str(metadata["title"]),
        issuer=str(metadata["issuer"]),
        doc_number=metadata.get("doc_number"),
        level=str(metadata["level"]),
        visibility=str(metadata["visibility"]),
        security_level=str(metadata["security_level"]),
        effective_date=to_date(metadata["effective_date"]),
        expiration_date=to_date(metadata.get("expiration_date")),
        status=str(metadata.get("status") or DocumentStatus.EFFECTIVE.value),
        summary=metadata.get("summary"),
        file_path=metadata.get("file_path"),
        file_size=len(content) if content is not None else metadata.get("file_size"),
        doc_metadata={"org_unit_id": metadata.get("org_unit_id"), "page_count": page_count},
    )
    # tags 为 ARRAY(String) 列，SQLAlchemy 类型插件将其推导为 Sequence[_T]（自由类型变量），
    # 无法用具体类型标注匹配，故在构造后通过属性赋值注入。
    setattr(document, "tags", [str(tag) for tag in metadata["tags"]])
    db.add(document)
    await db.flush()  # 触发 tenant_id 注入并取得 document.id

    # 4. 切分并写入片段（涉密材料不入向量库）
    chunk_count = 0
    if validation.embedding_allowed and parsed_text.strip():
        active_splitter = splitter or ChapterArticleSplitter()
        chunks = active_splitter.split(parsed_text)
        chunk_count = len(chunks)

        logger.debug(
            "document_chunks_generated",
            extra={"doc_id": doc_id, "chunk_count": chunk_count},
        )

        # 批量插入优化（避免逐条add）
        chunk_records = [
            EmbeddingChunk(
                tenant_id=tenant_id or document.tenant_id,
                doc_id=document.id,
                chunk_id=uuid.uuid4().hex,
                content=chunk.content,
                sequence=chunk.sequence,
                article=chunk.article,
            )
            for chunk in chunks
        ]
        db.add_all(chunk_records)
        await db.flush()

    logger.info(
        "knowledge_document_created",
        extra={
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "level": document.level,
            "chunks": chunk_count,
            "page_count": page_count,
        },
    )
    return document, chunk_count, page_count


async def replace_document_content(
    db: AsyncSession,
    *,
    doc_id: str,
    tenant_id: str,
    content: bytes,
    file_name: str,
    expected_revision: int,
) -> tuple[KnowledgeDoc, int, int]:
    """保留旧片段，新版本重新解析切分，旧向量不再参与检索。"""
    if not tenant_id:
        raise ValueError("文档更新必须提供租户")
    document = (
        await db.execute(
            select(KnowledgeDoc)
            .where(
                KnowledgeDoc.doc_id == doc_id,
                KnowledgeDoc.tenant_id == tenant_id,
                KnowledgeDoc.is_deleted.is_(False),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if document is None:
        raise DocumentNotFoundError("文档不存在")
    metadata = dict(document.doc_metadata or {})
    revision = metadata.get("content_revision", 1)
    if expected_revision != revision:
        raise DocumentConflictError("文件已被更新，请刷新后再试")
    parsed = default_registry.get(file_name).parse(content, file_name=file_name)
    if not parsed.text.strip():
        raise ParseError("文档不包含可解析文本")
    declared_level = DataLevel(document.security_level)
    if content_level(parsed.text, minimum=declared_level) != declared_level:
        raise MetadataValidationError(["更新内容与原文档分级不符，请按保密要求分类归档"])
    chunks = (
        ChapterArticleSplitter().split(parsed.text)
        if document.security_level != "classified"
        else []
    )
    await db.execute(
        update(EmbeddingChunk)
        .where(
            EmbeddingChunk.doc_id == document.id,
            EmbeddingChunk.tenant_id == tenant_id,
            EmbeddingChunk.is_deleted.is_(False),
        )
        .values(is_deleted=True)
    )
    db.add_all(
        [
            EmbeddingChunk(
                tenant_id=tenant_id,
                doc_id=document.id,
                chunk_id=uuid.uuid4().hex,
                content=chunk.content,
                sequence=chunk.sequence,
                article=chunk.article,
            )
            for chunk in chunks
        ]
    )
    document.file_name, document.file_size = file_name, len(content)
    document.file_path = None
    document.doc_metadata = {
        **metadata,
        "page_count": parsed.page_count,
        "content_revision": revision + 1,
    }
    await db.flush()
    return document, len(chunks), revision


async def delete_document(db: AsyncSession, *, doc_id: str, tenant_id: str) -> KnowledgeDoc:
    """软删除同租户文档和全部片段，保留历史版本，调用方负责审计与提交。"""
    statement = (
        select(KnowledgeDoc)
        .where(
            KnowledgeDoc.doc_id == doc_id,
            KnowledgeDoc.tenant_id == tenant_id,
            KnowledgeDoc.is_deleted.is_(False),
        )
        .with_for_update()
    )
    document = (await db.execute(statement)).scalar_one_or_none()
    if document is None:
        raise DocumentNotFoundError("文档不存在")
    document.is_deleted = True
    document.status = DocumentStatus.ABOLISHED.value
    await db.execute(
        update(EmbeddingChunk)
        .where(
            EmbeddingChunk.doc_id == document.id,
            EmbeddingChunk.tenant_id == tenant_id,
            EmbeddingChunk.is_deleted.is_(False),
        )
        .values(is_deleted=True)
    )
    await db.flush()
    return document


async def change_document_status(
    db: AsyncSession,
    *,
    doc_id: str,
    new_status: str,
    changed_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> KnowledgeDoc:
    """变更文档状态（有效 / 已失效 / 已废止）

    Args:
        db: 数据库会话
        doc_id: 文档标识
        new_status: 新状态
        changed_by: 操作人（可选，用于审计）
        reason: 变更原因（可选，用于审计）

    Returns:
        更新后的文档对象

    Raises:
        ValueError: 状态值非法
        DocumentNotFoundError: 文档不存在
    """
    valid = {status.value for status in DocumentStatus}
    if new_status not in valid:
        raise ValueError(f"非法状态: {new_status}（应为 {'/'.join(sorted(valid))}）")

    document = await get_document(db, doc_id=doc_id)
    if document is None:
        raise DocumentNotFoundError(f"文档不存在: {doc_id}")

    old_status = document.status
    document.status = new_status
    await db.flush()

    logger.info(
        "knowledge_document_status_changed",
        extra={
            "doc_id": doc_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": changed_by,
        },
    )
    return document
