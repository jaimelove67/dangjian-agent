"""知识文档服务

实现框架文档 5.2/5.3 的入库流程：元数据校验 → 文件解析 → 章条切分 → 落库。

切分得到的片段写入 ``embedding_chunks``；**涉密材料不入向量库**（仅保留文档记录，
走人工归档）。向量化（embedding）由检索链路（开发者B）后续补齐。
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DocumentStatus
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.loader import ParserRegistry, default_registry
from app.rag.splitter import ChapterArticleSplitter
from app.rules.document_metadata import validate_document_metadata
from app.utils.datetime import to_date

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """文档不存在"""


class DocumentConflictError(Exception):
    """文档标识冲突"""


async def get_document(db: AsyncSession, *, doc_id: str) -> Optional[KnowledgeDoc]:
    """按文档标识查询文档"""
    result = await db.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.doc_id == doc_id)
    )
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
                chunk_id=f"{doc_id}-{chunk.sequence}",
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
