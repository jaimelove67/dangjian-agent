"""检索服务

整合混合检索、重排、过滤等功能。
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.rag.retrieval.vector import VectorRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.retrieval.reranker import Reranker
from app.rag.retrieval.no_evidence import has_evidence
from app.schemas.retrieval import RetrievalFilters, RetrievalResponse, RetrievalResult
from app.llm.base import DataLevel
from app.core.security import resolve_data_level, UserRole
from app.core.config import settings

logger = structlog.get_logger(__name__)


def _build_visibility_levels(data_level: DataLevel) -> List[str]:
    """根据数据级别构建可见范围列表

    Args:
        data_level: 数据级别

    Returns:
        可见范围列表
    """
    # 数据级别越高，可见范围越小
    if data_level == DataLevel.PUBLIC:
        return ["public"]
    elif data_level == DataLevel.INTERNAL:
        return ["public", "school"]
    elif data_level == DataLevel.SENSITIVE:
        return ["public", "school", "department"]
    else:  # CLASSIFIED
        return ["public", "school", "department", "branch"]


def _build_security_levels(data_level: DataLevel) -> List[str]:
    """根据数据级别构建保密级别列表

    Args:
        data_level: 数据级别

    Returns:
        允许访问的保密级别列表
    """
    if data_level == DataLevel.PUBLIC:
        return ["public"]
    elif data_level == DataLevel.INTERNAL:
        return ["public", "internal"]
    elif data_level == DataLevel.SENSITIVE:
        return ["public", "internal", "sensitive"]
    else:  # CLASSIFIED
        return ["public", "internal", "sensitive", "classified"]


class RetrievalService:
    """检索服务

    整合混合检索、重排、过滤的完整检索流程。
    """

    def __init__(self):
        """初始化检索服务"""
        self.vector_retriever = VectorRetriever()
        self.keyword_retriever = KeywordRetriever()
        self.hybrid_retriever = HybridRetriever(
            vector_retriever=self.vector_retriever,
            keyword_retriever=self.keyword_retriever,
        )
        self.reranker = Reranker()

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        tenant_id: str,
        data_level: DataLevel,
        user_role: Optional[UserRole] = None,
        top_k: int = None,
        use_rerank: bool = True,
        retrieval_method: str = "hybrid",
    ) -> RetrievalResponse:
        """执行检索

        Args:
            db: 数据库会话
            query: 查询文本
            tenant_id: 租户ID
            data_level: 数据级别（由用户角色推导）
            user_role: 用户角色（可选，用于日志）
            top_k: 返回结果数量（默认使用配置）
            use_rerank: 是否使用重排
            retrieval_method: 检索方法 (vector/keyword/hybrid)

        Returns:
            检索响应
        """
        if top_k is None:
            top_k = settings.RERANK_TOP_K if use_rerank else settings.RETRIEVAL_TOP_K

        # 构建过滤条件
        filters = RetrievalFilters(
            tenant_id=tenant_id,
            data_level=data_level,
            visibility_levels=_build_visibility_levels(data_level),
            exclude_expired=settings.EXCLUDE_EXPIRED_BY_DEFAULT,
            security_levels=_build_security_levels(data_level),
        )

        # 1. 执行检索
        if retrieval_method == "vector":
            results = await self.vector_retriever.retrieve(
                db=db,
                query=query,
                filters=filters,
                top_k=settings.RETRIEVAL_TOP_K if use_rerank else top_k,
            )
        elif retrieval_method == "keyword":
            results = await self.keyword_retriever.retrieve(
                db=db,
                query=query,
                filters=filters,
                top_k=settings.RETRIEVAL_TOP_K if use_rerank else top_k,
            )
        else:  # hybrid
            results = await self.hybrid_retriever.retrieve(
                db=db,
                query=query,
                filters=filters,
                top_k=settings.RETRIEVAL_TOP_K if use_rerank else top_k,
            )

        # 2. 重排（如果启用）
        if use_rerank and len(results) > top_k:
            results = await self.reranker.rerank(
                query=query,
                candidates=results,
                top_k=top_k,
            )

        # 3. 无依据判定
        has_ev = has_evidence(
            results=results,
            threshold=settings.NO_EVIDENCE_THRESHOLD,
        )

        logger.info(
            "retrieval_completed",
            query_length=len(query),
            tenant_id=tenant_id,
            data_level=data_level.value,
            user_role=user_role.value if user_role else None,
            retrieval_method=retrieval_method,
            use_rerank=use_rerank,
            results_count=len(results),
            has_evidence=has_ev,
        )

        return RetrievalResponse(
            results=results,
            has_evidence=has_ev,
            total_count=len(results),
            retrieval_method=retrieval_method,
            metadata={
                "threshold": settings.NO_EVIDENCE_THRESHOLD,
                "top_k": top_k,
                "reranked": use_rerank,
            },
        )


# 全局检索服务实例
_retrieval_service: Optional[RetrievalService] = None


def get_retrieval_service() -> RetrievalService:
    """获取检索服务单例

    Returns:
        检索服务实例
    """
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
