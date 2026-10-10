"""阿里云 DashScope 重排模型提供者

使用 DashScope 文本重排 HTTP 接口（``qwen3.7-text-rerank`` 系列）。
说明：dashscope SDK 1.14.1 不含 TextRerank，故直连 HTTP 端点；
返回结构与 ``app/rag/retrieval/hybrid.py::_rerank`` 消费方对齐
（``results[n].index`` / ``results[n].relevance_score``）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import httpx
import structlog

from app.llm.base import (
    BaseModelProvider,
    ModelConfig,
    ModelResponse,
    EmbeddingResponse,
    DeploymentType,
    ModelType,
)

logger = structlog.get_logger(__name__)

# DashScope 文本重排服务端点
RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


@dataclass
class RerankResult:
    """单条重排结果"""
    index: int
    relevance_score: float
    text: str = ""


@dataclass
class RerankResponse:
    """重排响应（与 hybrid._rerank 消费的 response.results 形状一致）"""
    results: List[RerankResult] = field(default_factory=list)
    usage: Optional[dict] = None


class DashScopeRerankerProvider(BaseModelProvider):
    """阿里云 DashScope 重排模型提供者"""

    def __init__(self, config: ModelConfig):
        """初始化

        Args:
            config: 模型配置
        """
        super().__init__(config)
        if not config.api_key:
            raise ValueError("DashScope API Key is required")
        logger.info(
            "dashscope_reranker_provider_initialized",
            model_id=config.model_id,
            model_name=config.model_name,
        )

    async def generate(
        self,
        prompt: str,
        **kwargs
    ) -> ModelResponse:
        """重排模型不支持文本生成"""
        raise NotImplementedError(
            "Reranker model does not support text generation"
        )

    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> EmbeddingResponse:
        """重排模型不支持向量化"""
        raise NotImplementedError(
            "Reranker model does not support embedding"
        )

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
        **kwargs
    ) -> RerankResponse:
        """文本重排

        Args:
            query: 查询文本
            documents: 候选文档列表
            top_n: 返回前 N 条（缺省为全部）

        Returns:
            RerankResponse（results 含 index / relevance_score）
        """
        if not documents:
            return RerankResponse()

        # 调用方（ModelService.rerank）传的是 top_k，此处兼容 top_n / top_k
        limit = top_n or kwargs.get("top_k") or len(documents)

        payload = {
            "model": self.config.model_name,
            "input": {"query": query, "documents": documents},
            "parameters": {
                "top_n": limit,
                "return_documents": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    RERANK_URL,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            logger.error(
                "dashscope_rerank_http_error",
                model_id=self.config.model_id,
                error=str(exc),
            )
            raise RuntimeError(f"DashScope Rerank 请求失败: {exc}") from exc

        if resp.status_code != 200:
            logger.error(
                "dashscope_rerank_error",
                model_id=self.config.model_id,
                status=resp.status_code,
                body=resp.text[:200],
            )
            raise RuntimeError(
                f"DashScope Rerank API error: {resp.status_code} - {resp.text[:200]}"
            )

        data = resp.json()
        output = data.get("output") or {}
        results = [
            RerankResult(
                index=int(item.get("index", 0)),
                relevance_score=float(item.get("relevance_score", 0.0)),
                text=(item.get("document") or {}).get("text", ""),
            )
            for item in (output.get("results") or [])
        ]

        logger.info(
            "dashscope_rerank_success",
            model_id=self.config.model_id,
            query_length=len(query),
            num_documents=len(documents),
            num_results=len(results),
        )
        return RerankResponse(results=results, usage=data.get("usage"))

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.rerank(
                query="健康检查",
                documents=["测试文档"],
                top_n=1,
            )
            return len(response.results) > 0
        except Exception as exc:
            logger.error(
                "dashscope_reranker_health_check_failed",
                model_id=self.config.model_id,
                error=str(exc),
            )
            return False


def create_dashscope_reranker_provider(
    model_id: str = "qwen-reranker",
    model_name: str = "qwen3.7-text-rerank",
    api_key: Optional[str] = None,
) -> DashScopeRerankerProvider:
    """创建阿里云DashScope重排提供者

    Args:
        model_id: 模型ID
        model_name: 模型名称（如 qwen3.7-text-rerank）
        api_key: DashScope API Key

    Returns:
        DashScope重排提供者实例
    """
    config = ModelConfig(
        model_id=model_id,
        model_name=model_name,
        model_type=ModelType.RERANKER,
        deployment_type=DeploymentType.EXTERNAL,
        provider="dashscope",
        api_key=api_key,
    )

    return DashScopeRerankerProvider(config)