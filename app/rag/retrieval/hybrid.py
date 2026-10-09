"""混合检索模块

融合向量检索和关键词检索结果。
"""
from typing import List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.rag.retrieval.vector import VectorRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.schemas.retrieval import RetrievalFilters, RetrievalResult

logger = structlog.get_logger(__name__)


class HybridRetriever:
    """混合检索器

    使用RRF（Reciprocal Rank Fusion）算法融合多路检索结果。
    """

    def __init__(
        self,
        vector_retriever: VectorRetriever,
        keyword_retriever: KeywordRetriever,
        k: int = 60,  # RRF参数
    ):
        """初始化

        Args:
            vector_retriever: 向量检索器
            keyword_retriever: 关键词检索器
            k: RRF常数，通常取60
        """
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.k = k

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        filters: RetrievalFilters,
        top_k: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[RetrievalResult]:
        """混合检索

        Args:
            db: 数据库会话
            query: 查询文本
            filters: 过滤条件
            top_k: 返回结果数量
            vector_weight: 向量检索权重
            keyword_weight: 关键词检索权重

        Returns:
            融合后的检索结果列表
        """
        # 1. 并行执行向量检索和关键词检索
        # 注意：这里先后执行，如果需要真正并行可以用asyncio.gather
        vector_results = await self.vector_retriever.retrieve(
            db=db,
            query=query,
            filters=filters,
            top_k=top_k * 2,  # 多取一些，融合后再截断
        )

        keyword_results = await self.keyword_retriever.retrieve(
            db=db,
            query=query,
            filters=filters,
            top_k=top_k * 2,
        )

        # 2. 使用RRF融合
        fused_results = self._rrf_fusion(
            vector_results=vector_results,
            keyword_results=keyword_results,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )

        # 3. 取top_k
        final_results = fused_results[:top_k]

        logger.info(
            "hybrid_retrieval_completed",
            query_length=len(query),
            vector_count=len(vector_results),
            keyword_count=len(keyword_results),
            fused_count=len(fused_results),
            final_count=len(final_results),
            tenant_id=filters.tenant_id,
        )

        return final_results

    def _rrf_fusion(
        self,
        vector_results: List[RetrievalResult],
        keyword_results: List[RetrievalResult],
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[RetrievalResult]:
        """RRF融合算法

        RRF score = Σ weight / (k + rank)

        Args:
            vector_results: 向量检索结果
            keyword_results: 关键词检索结果
            vector_weight: 向量权重
            keyword_weight: 关键词权重

        Returns:
            融合后的结果列表
        """
        # 构建chunk_id到结果的映射
        chunk_map: Dict[str, RetrievalResult] = {}
        scores: Dict[str, float] = {}

        # 处理向量检索结果
        for rank, result in enumerate(vector_results):
            chunk_id = result.chunk_id
            chunk_map[chunk_id] = result

            # RRF分数
            rrf_score = vector_weight / (self.k + rank + 1)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + rrf_score

        # 处理关键词检索结果
        for rank, result in enumerate(keyword_results):
            chunk_id = result.chunk_id

            # 如果已存在，使用向量检索的结果（包含更完整的metadata）
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = result

            # 累加RRF分数
            rrf_score = keyword_weight / (self.k + rank + 1)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + rrf_score

        # 按融合分数排序
        sorted_chunk_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        # 构建最终结果
        fused_results: List[RetrievalResult] = []
        for chunk_id in sorted_chunk_ids:
            result = chunk_map[chunk_id]
            # 更新分数为融合分数
            result.score = scores[chunk_id]
            fused_results.append(result)

        return fused_results
