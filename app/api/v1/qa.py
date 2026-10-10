"""知识问答接口"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, get_current_user, require_permissions
from app.llm.base import DataLevel
from app.models.user import User
from app.rag.rag_service import RAGService
from app.schemas.common import APIResponse
from app.schemas.qa import QASessionItem, QASessionListResponse
from app.services.qa_session_service import create_session, list_sessions

logger = logging.getLogger(__name__)

router = APIRouter()

# 问答需要基本的查询权限
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)


class QuestionRequest(BaseModel):
    """问答请求"""

    question: str = Field(..., description="用户问题", min_length=1, max_length=500)
    data_level: str = Field(
        "public",
        description="数据级别：public/internal/sensitive",
    )
    use_reranker: bool = Field(True, description="是否使用重排模型")
    top_k: int = Field(10, description="检索结果数量", ge=1, le=50)


class CitationSchema(BaseModel):
    """引用"""

    title: str
    issuer: str
    doc_number: Optional[str] = None
    article: Optional[str] = None
    content: str
    score: float


class QuestionResponse(BaseModel):
    """问答响应"""

    answer: str = Field(..., description="生成的答案")
    citations: list[CitationSchema] = Field(..., description="引用列表")
    retrieved_count: int = Field(..., description="检索到的片段数量")
    used_count: int = Field(..., description="用于生成答案的片段数量")
    has_sufficient_evidence: bool = Field(..., description="是否有足够的依据")


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


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

    # 解析数据级别
    data_level_map = {
        "public": DataLevel.PUBLIC,
        "internal": DataLevel.INTERNAL,
        "sensitive": DataLevel.SENSITIVE,
    }
    data_level = data_level_map.get(body.data_level.lower(), DataLevel.PUBLIC)

    # 创建 RAG 服务
    rag_service = RAGService(
        db,
        data_level=data_level,
        retrieval_top_k=body.top_k,
        context_top_k=min(5, body.top_k),
        use_reranker=body.use_reranker,
    )

    # 执行问答
    filters = {"tenant_id": tenant_id, "status": "effective"}
    rag_response = await rag_service.ask(body.question, filters=filters)

    # 转换响应
    citations = [
        CitationSchema(
            title=c.title,
            issuer=c.issuer,
            doc_number=c.doc_number,
            article=c.article,
            content=c.content,
            score=c.score,
        )
        for c in rag_response.citations
    ]

    # 落库问答历史（尽力而为：历史写入失败不影响本次回答返回）
    try:
        await create_session(
            db,
            tenant_id=tenant_id,
            user_id=user.id,
            question=body.question,
            answer=rag_response.answer,
            citations=[c.model_dump() for c in citations],
            data_level=body.data_level,
            has_sufficient_evidence=rag_response.has_sufficient_evidence,
            retrieved_count=rag_response.retrieved_count,
            used_count=rag_response.used_count,
        )
    except Exception as exc:
        logger.warning("qa_history_save_failed: %s", exc)

    return APIResponse(
        data=QuestionResponse(
            answer=rag_response.answer,
            citations=citations,
            retrieved_count=rag_response.retrieved_count,
            used_count=rag_response.used_count,
            has_sufficient_evidence=rag_response.has_sufficient_evidence,
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/qa/sessions",
    response_model=APIResponse[QASessionListResponse],
    summary="问答历史",
    description="分页查询当前用户在租户内的问答历史（时间倒序）。",
    tags=["知识问答"],
)
async def list_qa_sessions(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QASessionListResponse]:
    """查询当前用户的问答历史"""
    sessions, total = await list_sessions(
        db,
        tenant_id=tenant_id,
        user_id=str(user.id),
        page=page,
        page_size=page_size,
    )
    return APIResponse(
        data=QASessionListResponse(
            total=total,
            items=[QASessionItem.from_model(s) for s in sessions],
        ),
        trace_id=_trace_id(request),
    )
