"""重排模块

使用交叉编码器对候选结果进行精排。
"""
from typing import List
import structlog

from app.schemas.retrieval import RetrievalResult
from app.llm.registry import get_model_registry

logger = structlog.get_logger(__name__)


class Reranker:
    """重排器

    使用交叉编码器模型对候选进行精排。
    """

    def __init__(self, reranker_model_id: str = "qwen-reranker"):
        """初始化

        Args:
            reranker_model_id: 重排模型ID
        """
        self.reranker_model_id = reranker_model_id
        self.registry = get_model_registry()

    async def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """重排

        Args:
            query: 查询文本
            candidates: 候选结果列表
            top_k: 返回前N个结果

        Returns:
            重排后的结果列表
        """
        if not candidates:
            return []

        # 如果候选数量小于等于top_k，直接返回
        if len(candidates) <= top_k:
            return candidates

        try:
            # 获取重排模型
            provider = self.registry.get_provider(self.reranker_model_id)
            if provider is None:
                logger.warning(
                    "reranker_not_found",
                    model_id=self.reranker_model_id,
                    fallback="returning_candidates_as_is",
                )
                return candidates[:top_k]

            # 提取文档内容
            documents = [c.content for c in candidates]

            # 调用重排API
            reranked_indices = await provider.rerank(
                query=query,
                documents=documents,
                top_n=top_k,
            )

            # 重新排序结果
            reranked_results: List[RetrievalResult] = []
            for idx, score in reranked_indices:
                if idx < len(candidates):
                    result = candidates[idx]
                    # 更新分数为重排分数
                    result.score = score
                    reranked_results.append(result)

            logger.info(
                "rerank_completed",
                query_length=len(query),
                candidates_count=len(candidates),
                reranked_count=len(reranked_results),
            )

            return reranked_results

        except Exception as e:
            logger.error(
                "rerank_failed",
                error=str(e),
                candidates_count=len(candidates),
            )
            # 降级：返回原始候选的top_k
            return candidates[:top_k]
