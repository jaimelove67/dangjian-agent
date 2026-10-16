"""知识文档服务

实现框架文档 5.2/5.3 的入库流程：元数据校验 → 文件解析 → 章条切分 → 落库。

切分得到的片段写入 ``embedding_chunks``；**涉密材料不入向量库**（仅保留文档记录，
走人工归档）。向量化（embedding）由检索链路（开发者B）后续补齐。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    DocumentAuthority,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentValidity,
    DocumentVisibility,
    is_review_due,
)
from app.core.tenant import get_tenant_id
from app.llm.base import DataLevel
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.exceptions import ParseError
from app.rag.loader import ParserRegistry, default_registry, empty_text_reason
from app.rag.privacy import content_level
from app.rag.splitter import ChapterArticleSplitter
from app.rules.document_metadata import MetadataValidationError, validate_document_metadata
from app.services.governance_service import supply_rules
from app.utils.datetime import to_date

logger = logging.getLogger(__name__)

# 未显式标注权威来源时按文档层级推定（T-DATA-05）：
# 中央 / 省级文件属「上级文件」，学校 / 院系文件属「学校制度」。
DEFAULT_AUTHORITY_BY_LEVEL: dict[str, str] = {
    "central": DocumentAuthority.SUPERIOR_DOCUMENT.value,
    "provincial": DocumentAuthority.SUPERIOR_DOCUMENT.value,
    "school": DocumentAuthority.SCHOOL_POLICY.value,
    "department": DocumentAuthority.SCHOOL_POLICY.value,
}


class DocumentNotFoundError(Exception):
    """文档不存在"""


class DocumentConflictError(Exception):
    """文档标识冲突"""


class DocumentReviewError(Exception):
    """审核状态或操作非法"""


class DocumentMaintenanceError(Exception):
    """复核确认操作非法（例如对非现行有效条目登记复核）"""


def default_authority(level: str) -> str:
    """按层级给出默认权威来源；未知层级按非权威参考资料处理。"""
    return DEFAULT_AUTHORITY_BY_LEVEL.get(level, DocumentAuthority.REFERENCE.value)


def sync_validity_status(status: str, validity: str) -> tuple[str, str]:
    """效力状态与运行状态在「废止」处对齐

    ``validity`` 是维护人员确认的效力状态，``status`` 是按日期自动判定的运行
    状态。两者互相独立，但「已废止」必须一致：废止即从运行状态上失效，反之
    运行状态标为废止时效力状态也随之记载为废止。
    """
    if validity == DocumentValidity.REPEALED.value:
        return DocumentStatus.ABOLISHED.value, validity
    if status == DocumentStatus.ABOLISHED.value:
        return status, DocumentValidity.REPEALED.value
    return status, validity


def reopen_review(document: KnowledgeDoc) -> bool:
    """把已发布的公共可见内容重新置为待审

    正文或可见范围发生变化后，旧审核结论不再适用（T-KB-12）：必须重新审核，
    否则等于用旧结论放行了新内容。返回是否发生了重新待审。
    """
    if document.visibility != DocumentVisibility.PUBLIC.value:
        return False
    if document.review_status != DocumentReviewStatus.PUBLISHED.value:
        return False
    document.review_status = DocumentReviewStatus.PENDING.value
    document.reviewed_by = None
    document.reviewed_at = None
    document.review_note = None
    return True


def sync_review_schedule(document: KnowledgeDoc, *, review_cycle_days: int | None) -> date | None:
    """按更新周期排定下次复核日期（T-KB-13）

    基准取「最近一次复核确认 / 内容更新」，没有复核记录时取生效日期。周期为空
    表示该条目不受周期约束（例如未登记供给机制的参考资料），此时不排日程。

    日程在排定后**不**随机制调整回溯改写：已排定的复核计划是条目级的承诺，
    悄悄改期会让"到期"失去可追溯性；机制变更自下次复核起生效。
    """
    if not review_cycle_days:
        document.next_review_at = None
        return None
    base = document.maintained_at.date() if document.maintained_at else document.effective_date
    if base is None:
        document.next_review_at = None
        return None
    document.next_review_at = base + timedelta(days=review_cycle_days)
    return document.next_review_at


def review_due(document: KnowledgeDoc, *, today: date | None = None) -> bool:
    """是否已到复核期限（T-KB-13）

    判定规则委托给 :func:`app.core.constants.is_review_due`，与出参字段同源，
    避免列表徽标与接口字段各判一套。这只是维护信号，**不**参与检索依据判定。
    """
    return is_review_due(
        document.next_review_at,
        status=document.status,
        validity=document.validity,
        today=today,
    )


async def supply_cycle(db: AsyncSession, *, tenant_id: str, authority: str | None) -> int | None:
    """条目所属权威来源的更新周期（天）；学校未登记该类别机制时为 None"""
    if not tenant_id or not authority:
        return None
    rules = await supply_rules(db, tenant_id)
    cycle = (rules.get(authority) or {}).get("review_cycle_days")
    return int(cycle) if cycle else None


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
        raise ParseError(empty_text_reason(parsed))
    # 3. 落库文档
    level = str(metadata["level"])
    visibility = str(metadata["visibility"])
    authority = str(metadata.get("authority") or default_authority(level))
    validity = str(metadata.get("validity") or DocumentValidity.EFFECTIVE.value)
    status, validity = sync_validity_status(
        str(metadata.get("status") or DocumentStatus.EFFECTIVE.value), validity
    )
    # 公共可见内容须经审核发布（T-KB-12）：入库即待审，审核通过后才进入检索范围；
    # 非公共内容不需要审核，直接发布。
    review_status = (
        DocumentReviewStatus.PENDING.value
        if visibility == DocumentVisibility.PUBLIC.value
        else DocumentReviewStatus.PUBLISHED.value
    )
    field_levels = metadata.get("field_levels")
    document = KnowledgeDoc(
        tenant_id=tenant_id,
        doc_id=doc_id,
        file_name=str(metadata["file_name"]),
        title=str(metadata["title"]),
        issuer=str(metadata["issuer"]),
        doc_number=metadata.get("doc_number"),
        level=level,
        visibility=visibility,
        security_level=str(metadata["security_level"]),
        effective_date=to_date(metadata["effective_date"]),
        expiration_date=to_date(metadata.get("expiration_date")),
        status=status,
        authority=authority,
        validity=validity,
        review_status=review_status,
        field_levels=dict(field_levels) if field_levels else None,
        summary=metadata.get("summary"),
        file_path=metadata.get("file_path"),
        file_size=len(content) if content is not None else metadata.get("file_size"),
        doc_metadata={
            "org_unit_id": metadata.get("org_unit_id"),
            "page_count": page_count,
            "uploaded_by": metadata.get("uploaded_by"),
        },
    )
    # tags 为 ARRAY(String) 列，SQLAlchemy 类型插件将其推导为 Sequence[_T]（自由类型变量），
    # 无法用具体类型标注匹配，故在构造后通过属性赋值注入。
    setattr(document, "tags", [str(tag) for tag in metadata["tags"]])
    # 供给机制（T-KB-13）：按权威来源带出复核周期并排定下次复核日程。
    sync_review_schedule(
        document,
        review_cycle_days=await supply_cycle(
            db, tenant_id=str(tenant_id or get_tenant_id() or ""), authority=authority
        ),
    )
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
            "authority": document.authority,
            "review_status": document.review_status,
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
        raise ParseError(empty_text_reason(parsed))
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
    # 公共可见内容换了正文就必须重新审核：已发布状态回到待审，避免用旧审核结论
    # 放行新内容（T-KB-12）。
    if reopen_review(document):
        logger.info("knowledge_document_review_reopened", extra={"doc_id": doc_id})
    # 正文更新即一次复核确认（T-KB-13）：法规修订后同步更新知识库，日程以本次
    # 更新为基准重排，而不是继续沿用旧内容的到期日。
    document.maintained_at = datetime.utcnow()
    sync_review_schedule(
        document,
        review_cycle_days=await supply_cycle(db, tenant_id=tenant_id, authority=document.authority),
    )
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
    # 删除即退出使用，效力状态同步记为「已废止」，避免留下废止文件仍标现行有效。
    document.status = DocumentStatus.ABOLISHED.value
    document.validity = DocumentValidity.REPEALED.value
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


async def confirm_maintenance(
    db: AsyncSession,
    *,
    doc_id: str,
    tenant_id: str,
    reviewer_id: str,
    note: Optional[str] = None,
) -> KnowledgeDoc:
    """登记一次复核确认（T-KB-13）

    确认人已核对条目仍然现行有效，或已随法规修订同步更新。确认时间成为下次复核
    日程的基准；下一次的周期按**当前**供给机制计算，因此机制调整自下次复核生效，
    已排定的日程不被回溯改写。

    Args:
        db: 数据库会话
        doc_id: 文档标识
        tenant_id: 归属租户
        reviewer_id: 复核人（账号 id，用于日志与审计）
        note: 复核说明（写入审计，不落库到条目）

    Returns:
        更新后的文档对象

    Raises:
        DocumentNotFoundError: 文档不存在
        DocumentMaintenanceError: 对非现行有效条目登记复核
    """
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
    if (
        document.status != DocumentStatus.EFFECTIVE.value
        or document.validity != DocumentValidity.EFFECTIVE.value
    ):
        raise DocumentMaintenanceError(
            "该条目当前不是现行有效，无需复核；如已恢复效力，请先更新效力状态"
        )
    document.maintained_at = datetime.utcnow()
    sync_review_schedule(
        document,
        review_cycle_days=await supply_cycle(db, tenant_id=tenant_id, authority=document.authority),
    )
    await db.flush()

    logger.info(
        "knowledge_document_maintained",
        extra={
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "reviewer_id": reviewer_id,
            "next_review_at": str(document.next_review_at),
            "note": note,
        },
    )
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
    old_validity = document.validity
    if (
        new_status != DocumentStatus.ABOLISHED.value
        and document.validity == DocumentValidity.REPEALED.value
    ):
        # 显式把运行状态改回有效 / 失效，视为恢复效力：否则会留下
        # 「运行状态已恢复、效力状态仍废止」的矛盾记载。
        document.validity = DocumentValidity.EFFECTIVE.value
    document.status, document.validity = sync_validity_status(
        new_status, str(document.validity or "")
    )
    await db.flush()

    logger.info(
        "knowledge_document_status_changed",
        extra={
            "doc_id": doc_id,
            "old_status": old_status,
            "new_status": document.status,
            "old_validity": old_validity,
            "new_validity": document.validity,
            "changed_by": changed_by,
        },
    )
    return document


async def review_document(
    db: AsyncSession,
    *,
    doc_id: str,
    tenant_id: str,
    decision: str,
    reviewer_id: str,
    note: Optional[str] = None,
) -> KnowledgeDoc:
    """审核公共可见内容（T-KB-12）

    批准后条目进入检索范围；退回则退出检索范围并要求修正后重新提交。退回必须
    填写审核意见，便于内容供给人知道问题所在。

    Raises:
        ValueError: 审核决定取值非法
        DocumentNotFoundError: 文档不存在
        DocumentReviewError: 内容不需要审核，或当前状态不允许该操作
    """
    if decision not in {"approve", "reject"}:
        raise ValueError(f"非法审核决定: {decision}（应为 approve / reject）")
    if decision == "reject" and not (note or "").strip():
        raise DocumentReviewError("退回必须填写审核意见")

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
        raise DocumentNotFoundError(f"文档不存在: {doc_id}")
    if document.visibility != DocumentVisibility.PUBLIC.value:
        raise DocumentReviewError("非公共可见内容不需要审核")
    if decision == "approve" and document.review_status == DocumentReviewStatus.PUBLISHED.value:
        raise DocumentReviewError("该内容已发布，无需重复审核")
    if decision == "reject" and document.review_status == DocumentReviewStatus.REJECTED.value:
        raise DocumentReviewError("该内容已退回，请修正后重新提交")

    document.review_status = (
        DocumentReviewStatus.PUBLISHED.value
        if decision == "approve"
        else DocumentReviewStatus.REJECTED.value
    )
    document.reviewed_by = reviewer_id
    document.reviewed_at = datetime.utcnow()
    document.review_note = (note or "").strip() or None
    await db.flush()

    logger.info(
        "knowledge_document_reviewed",
        extra={
            "doc_id": doc_id,
            "decision": decision,
            "review_status": document.review_status,
            "reviewer_id": reviewer_id,
        },
    )
    return document
