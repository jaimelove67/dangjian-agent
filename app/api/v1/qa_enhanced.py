"""增强的知识问答接口

提供完整的6阶段问答链路：
1. 预处理：查询理解与改写
2. 检索：混合检索
3. 重排：Reranker优化
4. 生成：LLM生成答案
5. 核验：引用核验
6. 输出：结构化响应

支持流式和非流式两种模式。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.user import User
from app.rag.enhanced_rag_service import EnhancedRAGService
from app.schemas.common import APIResponse

router = APIRouter()

# 问答需要基本的查询权限
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)


class EnhancedQuestionRequest(BaseModel):
    """增强的问答请求"""

    question: str = Field(..., description="用户问题", min_length=1, max_length=500)
    data_level: str = Field(
        "public",
        description="数据级别：public/internal/sensitive",
    )
    use_reranker: bool = Field(True, description="是否使用重排模型")
    top_k: int = Field(10, description="检索结果数量", ge=1, le=50)
    context_top_k: int = Field(5, description="上下文片段数量", ge=1, le=20)
    temperature: float = Field(0.3, description="LLM温度参数", ge=0.0, le=2.0)
    stream: bool = Field(False, description="是否使用流式输出")


class CitationSchema(BaseModel):
    """引用"""

    title: str
    issuer: str
    doc_number: Optional[str] = None
    article: Optional[str] = None
    content: str
    score: float


class EnhancedQuestionResponse(BaseModel):
    """增强的问答响应"""

    answer: str = Field(..., description="生成的答案")
    citations: list[CitationSchema] = Field(..., description="引用列表")
    retrieved_count: int = Field(..., description="检索到的片段数量")
    used_count: int = Field(..., description="用于生成答案的片段数量")
    has_sufficient_evidence: bool = Field(..., description="是否有足够的依据")
    metadata: dict = Field(default_factory=dict, description="元数据")


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


@router.post(
    "/qa/enhanced",
    response_model=APIResponse[EnhancedQuestionResponse],
    summary="增强的知识问答",
    description="基于知识库的RAG问答，支持完整的6阶段处理流程",
    tags=["知识问答"],
)
async def ask_question_enhanced(
    body: EnhancedQuestionRequest,
    request: Request,
    user: User = Depends(_require_query),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """增强的知识问答（支持流式和非流式）"""

    # 解析数据级别
    data_level_map = {
        "public": DataLevel.PUBLIC,
        "internal": DataLevel.INTERNAL,
        "sensitive": DataLevel.SENSITIVE,
    }
    data_level = data_level_map.get(body.data_level.lower(), DataLevel.PUBLIC)

    # 创建增强的RAG服务
    rag_service = EnhancedRAGService(
        db,
        data_level=data_level,
        retrieval_top_k=body.top_k,
        context_top_k=body.context_top_k,
        use_reranker=body.use_reranker,
    )

    # 构建过滤条件
    filters = {"tenant_id": tenant_id, "status": "effective"}

    # 流式输出
    if body.stream:
        async def generate():
            async for chunk in rag_service.ask_stream(
                body.question,
                filters=filters,
                temperature=body.temperature,
            ):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type="text/plain; charset=utf-8",
        )

    # 非流式输出
    rag_response = await rag_service.ask(
        body.question,
        filters=filters,
        temperature=body.temperature,
    )

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

    return APIResponse(
        data=EnhancedQuestionResponse(
            answer=rag_response.answer,
            citations=citations,
            retrieved_count=rag_response.retrieved_count,
            used_count=rag_response.used_count,
            has_sufficient_evidence=rag_response.has_sufficient_evidence,
            metadata=rag_response.metadata,
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/qa/health",
    summary="问答服务健康检查",
    description="检查问答服务是否正常",
    tags=["知识问答"],
)
async def qa_health_check(
    db: AsyncSession = Depends(get_db),
):
    """问答服务健康检查"""
    # 检查数据库连接
    try:
        await db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # TODO: 检查模型服务连接

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "timestamp": "2026-10-09T18:00:00Z",
    }
