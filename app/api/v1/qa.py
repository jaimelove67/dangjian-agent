"""知识问答接口"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.chains.session import SessionStore
from app.chains.workflow_interfaces import sensitive_check
from app.core.cache import CacheService, redis_manager
from app.core.config import settings, tenant_config
from app.core.constants import XLSX_MEDIA_TYPE
from app.core.security import Permission
from app.core.timeutil import as_utc_naive
from app.core.versions import version_fingerprint
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.qa_session import QASession
from app.models.user import User
from app.rag.rag_service import RAGService
from app.rag.retrieval.access import knowledge_filters
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.wf import SensitiveCheckRequest
from app.services.identity_service import IdentityService
from app.services.qa_record_io import build_qa_records
from app.services.qa_record_service import (
    MAX_EXPORT_ROWS,
    QaRecordFilters,
    QaRecordRow,
    count_qa_records,
    fetch_qa_records,
)
from app.services.qa_session_service import create_session, list_sessions, soft_delete_session

router = APIRouter()
logger = logging.getLogger(__name__)

# 问答需要基本的查询权限
_require_query = require_permissions(Permission.QA_ASK)
# 问答记录集中查看属治理与审计能力（T-SYS-06）：与"本人档案口径"分开授权
_require_audit = require_permissions(Permission.AUDIT_QUERY)


class QuestionRequest(BaseModel):
    """问答请求"""

    question: str = Field(..., description="用户问题", min_length=1, max_length=500)
    data_level: Optional[DataLevel] = Field(
        None,
        description="内容分级提示；服务端会提高至登录态及实际依据所需级别，涉密内容拒绝处理",
    )
    use_reranker: bool = Field(True, description="是否使用重排模型")
    top_k: Optional[int] = Field(None, description="检索结果数量，省略时使用租户配置", ge=1, le=50)
    session_id: Optional[str] = Field(
        None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    include_expired: Optional[bool] = Field(
        None, description="是否检索历史文件，省略时使用租户配置（回答会提示失效风险）"
    )


class CitationSchema(BaseModel):
    """引用"""

    title: str
    issuer: str
    doc_number: Optional[str] = None
    article: Optional[str] = None
    content: str
    score: float
    index: int
    doc_id: str
    file_name: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    visibility: Optional[str] = None
    security_level: Optional[str] = None
    level: Optional[str] = None
    chunk_id: Optional[str] = None
    content_revision: Optional[int] = None


class QuestionResponse(BaseModel):
    """问答响应"""

    answer: str = Field(..., description="生成的答案")
    citations: list[CitationSchema] = Field(..., description="引用列表")
    retrieved_count: int = Field(..., description="检索到的片段数量")
    used_count: int = Field(..., description="用于生成答案的片段数量")
    has_sufficient_evidence: bool = Field(..., description="是否有足够的依据")
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str
    refused: bool
    session_id: Optional[str] = None
    # 版本指纹（SEC-11 / T-SEC-11）：这条答案由哪个提示词版本、哪个工作流契约版本产出。
    # 写入问答记录后即可事后追溯；引用条各自带 content_revision 说明引的是哪一版。
    versions: dict[str, Any] = Field(
        default_factory=dict, description="本次回答的版本指纹（提示词与工作流契约版本）"
    )


class QASessionItem(QuestionResponse):
    id: str
    question: str
    data_level: DataLevel
    created_at: datetime

    @classmethod
    def from_record(cls, record: QASession) -> "QASessionItem":
        # 003/004 已保存的引用可能没有本地新增的编号和文档标识。
        citations = []
        for index, citation in enumerate(record.citations or [], 1):
            values = {"index": index, "doc_id": "", "score": 0, "content": "", **citation}
            citations.append(CitationSchema(**values))
        warnings = list(record.warnings or [])
        if any(not citation.doc_id for citation in citations):
            warnings.append("部分历史引用未包含文件标识，请核对原文。")
        return cls(
            id=str(record.id),
            question=record.question,
            data_level=DataLevel(record.data_level),
            created_at=record.created_at,
            answer=record.answer,
            citations=citations,
            retrieved_count=record.retrieved_count,
            used_count=record.used_count,
            has_sufficient_evidence=record.has_sufficient_evidence,
            warnings=warnings,
            disclaimer=record.disclaimer,
            refused=record.refused,
            session_id=record.session_id,
            # 本功能上线前的历史记录没有版本指纹，返回空字典，界面显示"未留痕"
            versions=dict(record.versions or {}),
        )


class QASessionListResponse(BaseModel):
    items: list[QASessionItem]
    total: int
    page: int
    page_size: int


class QARecordItem(BaseModel):
    """治理与审计视图的一行问答记录（含提问人标识与依据情况）"""

    id: str
    user_id: str
    asker: str
    username: str
    question: str
    answer: str
    data_level: str
    refused: bool
    has_sufficient_evidence: bool
    retrieved_count: int
    used_count: int
    citation_count: int
    warning_count: int
    is_deleted: bool
    created_at: datetime
    session_id: Optional[str] = None
    #: 版本指纹（SEC-11）：提示词 / 工作流契约版本；上线前的记录为空字典
    versions: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, row: QaRecordRow) -> "QARecordItem":
        """显式逐字段映射：新增行字段时不会静默漏出对外契约。"""
        return cls(
            id=row.id,
            user_id=row.user_id,
            asker=row.asker,
            username=row.username,
            question=row.question,
            answer=row.answer,
            data_level=row.data_level,
            refused=row.refused,
            has_sufficient_evidence=row.has_sufficient_evidence,
            retrieved_count=row.retrieved_count,
            used_count=row.used_count,
            citation_count=row.citation_count,
            warning_count=row.warning_count,
            is_deleted=row.is_deleted,
            created_at=row.created_at,
            session_id=row.session_id,
            versions=dict(row.versions or {}),
        )


class QARecordListResponse(BaseModel):
    items: list[QARecordItem]
    total: int
    page: int
    page_size: int
    #: 当前筛选口径（导出与列表共用一个说法，避免"导出了什么"说不清）
    scope_note: str


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _session_store(user: User) -> SessionStore:
    return SessionStore(
        CacheService(redis_manager.client),
        owner_id=str(user.id),
        ttl_seconds=settings.SESSION_TTL_SECONDS,
        max_turns=settings.SESSION_MAX_TURNS,
    )


async def _qa_record_filters(
    user_id: Optional[str] = Query(None, max_length=36, description="按提问人编号筛选"),
    keyword: Optional[str] = Query(None, max_length=100, description="按问题或回答内容模糊匹配"),
    data_level: Optional[DataLevel] = Query(None, description="按数据级别筛选"),
    refused: Optional[bool] = Query(None, description="true 仅看无依据拒答"),
    has_evidence: Optional[bool] = Query(None, description="false 仅看无足够依据"),
    start_at: Optional[datetime] = Query(None, description="起始时间（含）"),
    end_at: Optional[datetime] = Query(None, description="结束时间（含）"),
    include_deleted: bool = Query(False, description="是否包含提问人已软删除的记录"),
    tenant_id: Optional[str] = Query(
        None, max_length=36, description="查看其他租户仅平台管理员可用"
    ),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> QaRecordFilters:
    """集中查看的筛选条件：时间范围校验 + 租户边界收口在一处，两个接口共用"""
    start = as_utc_naive(start_at)
    end = as_utc_naive(end_at)
    if start and end and start > end:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    # 跨租户查看仅平台管理员；其余账号一律锁在自己的租户内（复用身份管理口径）
    target = await IdentityService(db, user).tenant(tenant_id)
    return QaRecordFilters(
        tenant_id=str(target.id),
        user_id=user_id,
        keyword=keyword.strip() if keyword and keyword.strip() else None,
        data_level=data_level.value if data_level else None,
        refused=refused,
        has_evidence=has_evidence,
        start_at=start,
        end_at=end,
        include_deleted=include_deleted,
    )


@router.post(
    "/qa",
    response_model=APIResponse[QuestionResponse],
    summary="知识问答",
    description="基于知识库的RAG问答",
    tags=["知识问答"],
)
async def ask_question(
    body: QuestionRequest,
    request: Request,
    user: User = Depends(_require_query),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QuestionResponse]:
    """知识问答"""

    # 账号角色仅决定资料访问上限，不能把管理员的普通问题都判为敏感。
    # WF-04 标准入口（T-WF02-13）：给出判定级别、命中原因与可执行出路，这里只负责拒绝方式。
    decision = sensitive_check(
        SensitiveCheckRequest(
            text=body.question,
            declared_level=body.data_level.value if body.data_level else None,
        )
    )
    logger.info(
        "qa_sensitive_decision",
        extra={
            "tenant_id": tenant_id,
            "workflow": decision.workflow,
            "workflow_version": decision.version,
            "level": decision.level,
            "cloud_allowed": decision.cloud_allowed,
            "reasons": decision.reasons,
        },
    )
    if not decision.cloud_allowed:
        # 出处写进 detail：只报“无法处理”等于让用户无从下手（可执行出路见 WF-04 契约）
        raise HTTPException(status_code=403, detail=decision.guidance)
    data_level = DataLevel(decision.level)

    top_k = body.top_k or tenant_config.get(tenant_id, "retrieval_top_k")
    context_top_k = min(tenant_config.get(tenant_id, "rerank_top_k"), top_k)
    include_expired = (
        body.include_expired
        if body.include_expired is not None
        else not tenant_config.get(tenant_id, "exclude_expired_by_default")
    )
    # 创建 RAG 服务
    rag_service = RAGService(
        db,
        data_level=data_level,
        retrieval_top_k=top_k,
        context_top_k=context_top_k,
        use_reranker=body.use_reranker,
        session=_session_store(user) if body.session_id else None,
        context={"tenant_id": tenant_id, "user_id": str(user.id), "request_id": _trace_id(request)},
        no_evidence_threshold=tenant_config.get(tenant_id, "no_evidence_threshold"),
    )

    # 执行问答
    filters = knowledge_filters(user, include_expired=include_expired)
    rag_response = await rag_service.ask(body.question, filters=filters, session_id=body.session_id)

    # 转换响应
    citations = [CitationSchema(**asdict(c)) for c in rag_response.citations]
    response = QuestionResponse(
        answer=rag_response.answer,
        citations=citations,
        retrieved_count=rag_response.retrieved_count,
        used_count=rag_response.used_count,
        has_sufficient_evidence=rag_response.has_sufficient_evidence,
        warnings=rag_response.warnings,
        disclaimer=rag_response.disclaimer,
        refused=rag_response.refused,
        session_id=body.session_id,
        # 版本留痕（SEC-11）：在"回答产生的那一刻"记下当时的提示词与工作流契约版本，
        # 而不是事后按当前配置倒推——配置随时可改，倒推会把旧答案说成新版本的产物。
        versions=version_fingerprint(tenant_id),
    )
    try:
        # 历史是可降级能力；SAVEPOINT 防止写历史失败破坏问答审计所在事务。
        async with db.begin_nested():
            await create_session(
                db,
                tenant_id=str(user.tenant_id),
                user_id=str(user.id),
                question=body.question,
                data_level=data_level.value,
                response=response.model_dump(mode="json"),
            )
    except SQLAlchemyError as exc:
        logger.warning(
            "qa_history_write_failed",
            extra={"request_id": _trace_id(request), "error_type": type(exc).__name__},
        )
        response.warnings.append("问答历史保存失败，本次回答仍可使用。")
    await audit_operation(
        db,
        request,
        user,
        action="qa_ask",
        resource_type="qa",
        data_level=data_level.value,
        new_value={
            "refused": rag_response.refused,
            "citations": [c.doc_id for c in rag_response.citations],
            "session_id": body.session_id,
        },
    )
    await db.commit()

    return APIResponse(
        data=response,
        trace_id=_trace_id(request),
    )


@router.get(
    "/qa/sessions",
    response_model=APIResponse[QASessionListResponse],
    summary="当前用户的长期问答记录",
    tags=["知识问答"],
)
async def list_qa_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QASessionListResponse]:
    records, total = await list_sessions(
        db,
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        page=page,
        page_size=page_size,
    )
    return APIResponse(
        data=QASessionListResponse(
            items=[QASessionItem.from_record(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
        ),
        trace_id=_trace_id(request),
    )


@router.get("/qa/history", response_model=APIResponse[list[dict]], summary="当前用户的会话历史")
async def read_history(
    request: Request,
    session_id: str = Query(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    user: User = Depends(_require_query),
) -> APIResponse[list[dict]]:
    history = await _session_store(user).get_history(str(user.tenant_id), session_id)
    return APIResponse(data=[asdict(turn) for turn in history], trace_id=_trace_id(request))


@router.get(
    "/qa/records",
    response_model=APIResponse[QARecordListResponse],
    summary="问答记录集中查看（治理与审计）",
    description=(
        "按提问人、关键词、数据级别、结果、依据与时间范围查看本租户问答记录；"
        "默认不含提问人已软删除的记录，跨租户查看仅平台管理员可用。"
    ),
    tags=["知识问答"],
)
async def list_qa_records(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    filters: QaRecordFilters = Depends(_qa_record_filters),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QARecordListResponse]:
    """学校治理视图：本人档案口径之外的集中查看（T-SYS-06）。"""
    total = await count_qa_records(db, filters)
    rows = await fetch_qa_records(db, filters, offset=(page - 1) * page_size, limit=page_size)
    return APIResponse(
        data=QARecordListResponse(
            items=[QARecordItem.from_record(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            scope_note=filters.scope_note(),
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/qa/records/export",
    response_model=None,
    summary="导出问答记录（Excel）",
    description=(
        "按当前筛选导出问答记录台账，附导出说明（筛选口径 / 条数 / 导出人）；"
        "导出动作写入审计，超出行数上限时提示分批导出。"
    ),
    tags=["知识问答"],
)
async def export_qa_records(
    request: Request,
    filters: QaRecordFilters = Depends(_qa_record_filters),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
) -> Response:
    total = await count_qa_records(db, filters)
    if total > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": (
                    f"当前条件共 {total} 条，超过单次导出上限 {MAX_EXPORT_ROWS} 条："
                    "请缩小时间范围或按提问人分批导出，避免生成打不开的大文件。"
                ),
            },
        )
    rows = await fetch_qa_records(db, filters, offset=0, limit=MAX_EXPORT_ROWS)
    content = build_qa_records(
        rows,
        scope_note=filters.scope_note(),
        exported_by=f"{user.name}（{user.username}）",
    )
    await audit_operation(
        db,
        request,
        user,
        action="export",
        resource_type="qa_record",
        data_level="internal",
        new_value={"rows": len(rows), "scope": filters.scope_note()},
    )
    await db.commit()
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="qa-records.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.delete(
    "/qa/sessions/{session_record_id}",
    response_model=APIResponse[dict],
    summary="删除本人一条长期问答记录",
    tags=["知识问答"],
)
async def delete_qa_session(
    session_record_id: str,
    request: Request,
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """软删除本人记录：他人记录、跨租户与不存在的记录都返回同一结果。"""
    removed = await soft_delete_session(
        db,
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        session_record_id=session_record_id,
    )
    if not removed:
        await db.rollback()
        raise HTTPException(404, "问答记录不存在或无权删除")
    await audit_operation(
        db,
        request,
        user,
        action="delete",
        resource_type="qa_session",
        resource_id=session_record_id,
        data_level="internal",
        new_value={"is_deleted": True},
    )
    await db.commit()
    return APIResponse(data={"id": session_record_id, "deleted": True}, trace_id=_trace_id(request))
