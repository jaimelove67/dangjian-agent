"""百炼 Qwen 文本重排，返回检索器使用的标准结果结构。"""

import math

from app.llm.base import DeploymentType, ModelConfig, ModelType, RerankResponse, RerankResult
from app.llm.errors import ModelUnavailableError
from app.llm.providers.cloud_http import CloudHTTPProvider, cloud_endpoint


class DashScopeRerankerProvider(CloudHTTPProvider):
    async def rerank(
        self, query: str, documents: list[str], top_k: int = None, top_n: int = None, **kwargs
    ) -> RerankResponse:
        count = min(
            len(documents),
            top_k if top_k is not None else top_n if top_n is not None else len(documents),
        )
        if not documents or count <= 0:
            return RerankResponse(model_id=self.config.model_id, results=[])
        body = await self._post(
            {
                "model": self.config.model_name,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": count, "return_documents": False},
            }
        )
        try:
            rows = body["output"]["results"]
            if not isinstance(rows, list) or not rows or len(rows) > count:
                raise ValueError
            seen = set()
            results = []
            for row in rows:
                index, score = row["index"], row["relevance_score"]
                if (
                    type(index) is not int
                    or not 0 <= index < len(documents)
                    or index in seen
                    or type(score) not in (int, float)
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                ):
                    raise ValueError
                seen.add(index)
                results.append(RerankResult(index=index, relevance_score=score))
            return RerankResponse(
                model_id=self.config.model_id,
                results=sorted(results, key=lambda result: result.relevance_score, reverse=True),
            )
        except (KeyError, TypeError, ValueError):
            raise ModelUnavailableError("重排模型返回索引或分数异常") from None

    async def health_check(self) -> bool:
        try:
            await self.rerank("健康检查", ["测试文档"], top_k=1)
            return True
        except Exception:
            return False


def create_dashscope_reranker_provider(
    model_id: str = "cloud-reranker",
    model_name: str = "qwen3.7-text-rerank",
    api_key: str = None,
) -> DashScopeRerankerProvider:
    return DashScopeRerankerProvider(
        ModelConfig(
            model_id=model_id,
            model_name=model_name,
            model_type=ModelType.RERANKER,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
            endpoint=cloud_endpoint("/api/v1/services/rerank/text-rerank/text-rerank"),
            api_key=api_key,
        )
    )
