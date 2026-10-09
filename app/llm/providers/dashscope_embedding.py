"""阿里云 DashScope 向量化模型提供者

使用阿里云 DashScope 的文本向量化服务。
支持 Qwen 系列向量化模型。
"""

from typing import List
import dashscope
from dashscope import TextEmbedding

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


class DashScopeEmbeddingProvider(BaseModelProvider):
    """阿里云 DashScope 向量化模型提供者"""

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
            "dashscope_embedding_provider_initialized",
            model_id=config.model_id,
            model_name=config.model_name
        )

    async def generate(
        self,
        prompt: str,
        **kwargs
    ) -> ModelResponse:
        """生成文本

        向量化模型不支持文本生成。

        Args:
            prompt: 输入提示词
            **kwargs: 额外参数

        Raises:
            NotImplementedError: 不支持文本生成
        """
        raise NotImplementedError(
            "Embedding model does not support text generation"
        )

    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> EmbeddingResponse:
        """文本向量化

        Args:
            texts: 文本列表
            **kwargs: 额外参数

        Returns:
            向量化响应
        """
        try:
            # 调用 DashScope 文本向量化 API
            response = TextEmbedding.call(
                model=self.config.model_name,
                input=texts
            )

            if response.status_code == 200:
                output = response.output
                embeddings_data = output.get('embeddings', [])

                # 提取向量
                embeddings = [item['embedding'] for item in embeddings_data]

                # 获取维度
                dimensions = len(embeddings[0]) if embeddings else 0

                logger.info(
                    "dashscope_embed_success",
                    model_id=self.config.model_id,
                    num_texts=len(texts),
                    dimensions=dimensions
                )

                return EmbeddingResponse(
                    embeddings=embeddings,
                    model_id=self.config.model_id,
                    dimensions=dimensions,
                )
            else:
                error_msg = f"DashScope Embedding API error: {response.code} - {response.message}"
                logger.error(
                    "dashscope_embed_error",
                    model_id=self.config.model_id,
                    error=error_msg
                )
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(
                "dashscope_embed_exception",
                model_id=self.config.model_id,
                num_texts=len(texts),
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
            response = TextEmbedding.call(
                model=self.config.model_name,
                input=["健康检查"]
            )

            is_healthy = response.status_code == 200

            logger.info(
                "dashscope_embedding_health_check",
                model_id=self.config.model_id,
                healthy=is_healthy
            )

            return is_healthy

        except Exception as e:
            logger.error(
                "dashscope_embedding_health_check_failed",
                model_id=self.config.model_id,
                error=str(e)
            )
            return False


def create_dashscope_embedding_provider(
    model_id: str = "qwen-embedding",
    model_name: str = "qwen3.7-text-embedding-flash",
    api_key: str = None,
) -> DashScopeEmbeddingProvider:
    """创建阿里云DashScope向量化提供者

    Args:
        model_id: 模型ID
        model_name: 模型名称（如qwen3.7-text-embedding-flash）
        api_key: DashScope API Key

    Returns:
        DashScope向量化提供者实例
    """
    config = ModelConfig(
        model_id=model_id,
        model_name=model_name,
        model_type=ModelType.EMBEDDING,
        deployment_type=DeploymentType.EXTERNAL,
        provider="dashscope",
        api_key=api_key,
    )

    return DashScopeEmbeddingProvider(config)
