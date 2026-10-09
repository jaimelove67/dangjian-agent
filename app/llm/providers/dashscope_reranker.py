"""阿里云 DashScope 重排模型提供者

使用阿里云 DashScope 的文本重排服务。
支持 Qwen 系列重排模型。
"""

from typing import List, Tuple
import dashscope

from app.llm.base import (
    BaseModelProvider,
    ModelConfig,
    ModelResponse,
    EmbeddingResponse,
    DeploymentType,
    ModelType,
)
import structlog

logger = structlog.get_logger(__name__)


class DashScopeRerankerProvider(BaseModelProvider):
    """阿里云 DashScope 重排模型提供者"""

    def __init__(self, config: ModelConfig):
        """初始化

        Args:
            config: 模型配置
        """
        super().__init__(config)

        # 设置 API Key
        if config.api_key:
            dashscope.api_key = config.api_key
        else:
            raise ValueError("DashScope API Key is required")

        logger.info(
            "dashscope_reranker_provider_initialized",
            model_id=config.model_id,
            model_name=config.model_name
        )

    async def generate(
        self,
        prompt: str,
        **kwargs
    ) -> ModelResponse:
        """生成文本

        重排模型不支持文本生成。

        Args:
            prompt: 输入提示词
            **kwargs: 额外参数

        Raises:
            NotImplementedError: 不支持文本生成
        """
        raise NotImplementedError(
            "Reranker model does not support text generation"
        )

    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> EmbeddingResponse:
        """文本向量化

        重排模型不支持向量化。

        Args:
            texts: 文本列表
            **kwargs: 额外参数

        Raises:
            NotImplementedError: 不支持向量化
        """
        raise NotImplementedError(
            "Reranker model does not support embedding"
        )

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int = None,
        **kwargs
    ) -> List[Tuple[int, float]]:
        """文本重排

        Args:
            query: 查询文本
            documents: 候选文档列表
            top_n: 返回前N个结果
            **kwargs: 额外参数

        Returns:
            [(文档索引, 分数), ...] 按分数降序排列
        """
        try:
            # 调用 DashScope 重排 API
            # 注意：需要根据实际API调整
            from dashscope import TextRerank

            response = TextRerank.call(
                model=self.config.model_name,
                query=query,
                documents=documents,
                top_n=top_n,
                **kwargs
            )

            if response.status_code == 200:
                output = response.output
                results = output.get('results', [])

                # 提取索引和分数
                reranked = [
                    (item['index'], item['relevance_score'])
                    for item in results
                ]

                logger.info(
                    "dashscope_rerank_success",
                    model_id=self.config.model_id,
                    query_length=len(query),
                    num_documents=len(documents),
                    num_results=len(reranked)
                )

                return reranked
            else:
                error_msg = f"DashScope Rerank API error: {response.code} - {response.message}"
                logger.error(
                    "dashscope_rerank_error",
                    model_id=self.config.model_id,
                    error=error_msg
                )
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(
                "dashscope_rerank_exception",
                model_id=self.config.model_id,
                num_documents=len(documents),
                error=str(e)
            )
            raise

    async def health_check(self) -> bool:
        """健康检查

        Returns:
            是否健康
        """
        try:
            # 发送一个简单的请求测试连接
            result = await self.rerank(
                query="健康检查",
                documents=["测试文档"],
                top_n=1
            )

            is_healthy = len(result) > 0

            logger.info(
                "dashscope_reranker_health_check",
                model_id=self.config.model_id,
                healthy=is_healthy
            )

            return is_healthy

        except Exception as e:
            logger.error(
                "dashscope_reranker_health_check_failed",
                model_id=self.config.model_id,
                error=str(e)
            )
            return False


def create_dashscope_reranker_provider(
    model_id: str = "qwen-reranker",
    model_name: str = "qwen3.7-text-rerank",
    api_key: str = None,
) -> DashScopeRerankerProvider:
    """创建阿里云DashScope重排提供者

    Args:
        model_id: 模型ID
        model_name: 模型名称（如qwen3.7-text-rerank）
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
