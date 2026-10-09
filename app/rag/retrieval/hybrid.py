"""混合检索器

融合向量检索和关键词检索的结果，使用 Reciprocal Rank Fusion (RRF) 算法。
支持集成重排模型进一步优化结果。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.llm.service import get_model_service
from app.rag.retrieval.base import RetrievalResult, Retriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever

logger = logging.getLogger(__name__)


class HybridRetriever(Retriever):
    """混合检索器（向量 + 关键词 + 可选重排）"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        data_level: DataLevel = DataLevel.PUBLIC,
        vector_weight: float = 0.5,
        keyword_weight: float = 0.5,
        use_reranker: bool = True,
        rrf_k: int = 60,
    ) -> None:
        """
        Args:
            db: 数据库会话
            data_level: 数据级别（用于模型路由）
            vector_weight: 向量检索权重
            keyword_weight: 关键词检索权重
            use_reranker: 是否使用重排模型
            rrf_k: RRF 算法的 k 参数（默认 60）
        """
        self.db = db
        self.data_level = data_level
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.use_reranker = use_reranker
        self.rrf_k = rrf_k

        # 初始化子检索器
        self.vector_retriever = VectorRetriever(db, data_level=data_level)
        self.keyword_retriever = KeywordRetriever(db)
        self._model_service = get_model_service()

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """混合检索

        流程：
        1. 并行执行向量检索和关键词检索
        2. 使用 RRF 算法融合结果
        3. 可选：使用重排模型优化排序
        4. 返回 top_k 结果

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件

        Returns:
            检索结果列表，按相关度降序排列
        """
        if not query.strip():
            return []

        # 1. 并行执行两种检索（各取 top_k * 2 保证融合后有足够候选）
        retrieval_top_k = top_k * 2

        vector_results = await self.vector_retriever.retrieve(
            query, top_k=retrieval_top_k, filters=filters
        )
        keyword_results = await self.keyword_retriever.retrieve(
            query, top_k=retrieval_top_k, filters=filters
        )

        logger.debug(
            "retrieval_results_collected",
            extra={
                "query": query[:50],
                "vector_count": len(vector_results),
                "keyword_count": len(keyword_results),
            },
        )

        # 2. RRF 融合
        fused_results = self._reciprocal_rank_fusion(
            vector_results, keyword_results, top_k=top_k * 3
        )

        logger.debug(
            "rrf_fusion_completed",
            extra={
                "query": query[:50],
                "fused_count": len(fused_results),
            },
        )

        # 3. 可选：重排序
        if self.use_reranker and fused_results:
            try:
                reranked_results = await self._rerank(
                    query, fused_results, top_k=top_k
                )
                logger.debug(
                    "reranking_completed",
                    extra={
                        "query": query[:50],
                        "reranked_count": len(reranked_results),
                    },
                )
                return reranked_results
            except Exception as exc:
                logger.warning(
                    "reranking_failed_fallback_to_fused",
                    extra={"query": query[:50], "error": str(exc)},
                )
                # 重排失败时降级到融合结果
                return fused_results[:top_k]

        return fused_results[:top_k]

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[RetrievalResult],
        keyword_results: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Reciprocal Rank Fusion (RRF) 算法融合检索结果

        RRF 公式：score(d) = Σ 1 / (k + rank(d))
        其中 k 是常数（默认 60），rank(d) 是文档在列表中的排名（从1开始）

        Args:
            vector_results: 向量检索结果
            keyword_results: 关键词检索结果
            top_k: 返回结果数量

        Returns:
            融合后的结果列表，按 RRF 分数降序排列
        """
        # 构建 chunk_id -> result 的映射
        chunk_map: dict[str, RetrievalResult] = {}

        # 向量检索结果的排名分数
        for rank, result in enumerate(vector_results, start=1):
            chunk_id = result.chunk_id
            rrf_score = self.vector_weight / (self.rrf_k + rank)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = result
                chunk_map[chunk_id].score = rrf_score
                chunk_map[chunk_id].metadata["rrf_score"] = rrf_score
            else:
                chunk_map[chunk_id].score += rrf_score
                chunk_map[chunk_id].metadata["rrf_score"] += rrf_score

        # 关键词检索结果的排名分数
        for rank, result in enumerate(keyword_results, start=1):
            chunk_id = result.chunk_id
            rrf_score = self.keyword_weight / (self.rrf_k + rank)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = result
                chunk_map[chunk_id].score = rrf_score
                chunk_map[chunk_id].metadata["rrf_score"] = rrf_score
            else:
                chunk_map[chunk_id].score += rrf_score
                chunk_map[chunk_id].metadata["rrf_score"] += rrf_score

        # 按 RRF 分数排序
        fused = sorted(
            chunk_map.values(),
            key=lambda r: r.score,
            reverse=True,
        )

        # 更新元数据标记为混合检索
        for result in fused:
            result.metadata["retrieval_method"] = "hybrid"

        return fused[:top_k]

    async def _rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """使用重排模型优化排序

        Args:
            query: 查询文本
            candidates: 候选结果列表
            top_k: 返回结果数量

        Returns:
            重排后的结果列表
        """
        if not candidates:
            return []

        # 准备文档列表
        documents = [result.content for result in candidates]

        # 调用重排模型
        rerank_response = await self._model_service.rerank(
            query=query,
            documents=documents,
            top_k=top_k,
            data_level=self.data_level,
        )

        # 根据重排结果重新排序
        reranked_results = []
        for rerank_result in rerank_response.results:
            original_result = candidates[rerank_result.index]
            # 保留原始分数，添加重排分数
            original_result.metadata["original_score"] = original_result.score
            original_result.score = rerank_result.relevance_score
            original_result.metadata["rerank_score"] = rerank_result.relevance_score
            original_result.metadata["retrieval_method"] = "hybrid_reranked"
            reranked_results.append(original_result)

        return reranked_results
