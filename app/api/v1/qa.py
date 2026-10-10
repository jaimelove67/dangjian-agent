"""知识问答接口"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.chains.session import SessionStore
from app.core.cache import CacheService, redis_manager
from app.core.config import settings, tenant_config
from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.qa_session import QASession
from app.models.user import User
from app.rag.privacy import content_level, require_cloud_eligible
from app.rag.rag_service import RAGService
from app.rag.retrieval.access import knowledge_filters
from app.schemas.common import APIResponse
from app.services.qa_session_service import create_session, list_sessions

router = APIRouter()
logger = logging.getLogger(__name__)

# 问答需要基本的查询权限
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)


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
            data_level=record.data_level,
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
        )


class QASessionListResponse(BaseModel):
    items: list[QASessionItem]
    total: int
    page: int
    page_size: int


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _session_store(user: User) -> SessionStore:
    return SessionStore(
        CacheService(redis_manager.client),
        owner_id=str(user.id),
        ttl_seconds=settings.SESSION_TTL_SECONDS,
        max_turns=settings.SESSION_MAX_TURNS,
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

    if body.data_level == DataLevel.CLASSIFIED:
        raise HTTPException(status_code=403, detail="涉密数据禁止进行 AI 处理")
    # 账号角色仅决定资料访问上限，不能把管理员的普通问题都判为敏感。
    data_level = content_level(body.question, body.data_level)
    require_cloud_eligible(data_level)

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
