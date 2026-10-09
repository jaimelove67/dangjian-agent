"""本地向量化模型提供者

使用 Sentence Transformers 加载本地向量化模型。
"""

from typing import List, Optional
import numpy as np
from sentence_transformers import SentenceTransformer

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


class LocalEmbeddingProvider(BaseModelProvider):
    """本地向量化模型提供者

    使用 Sentence Transformers 加载本地模型进行向量化。
    """

    def __init__(self, config: ModelConfig):
        """初始化

        Args:
            config: 模型配置
        """
        super().__init__(config)

        if not config.model_path:
            raise ValueError("model_path is required for local embedding")

        try:
            # 加载模型
            logger.info(
                "loading_embedding_model",
                model_id=config.model_id,
                model_path=config.model_path
            )

            self.model = SentenceTransformer(config.model_path)
            self.dimensions = self.model.get_sentence_embedding_dimension()

            logger.info(
                "embedding_model_loaded",
                model_id=config.model_id,
                dimensions=self.dimensions
            )

        except Exception as e:
            logger.error(
                "embedding_model_load_failed",
                model_id=config.model_id,
                model_path=config.model_path,
                error=str(e)
            )
            raise

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
                - batch_size: 批次大小
                - normalize_embeddings: 是否归一化向量

        Returns:
            向量化响应
        """
        try:
            batch_size = kwargs.get('batch_size', 32)
            normalize = kwargs.get('normalize_embeddings', True)

            # 向量化
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=normalize,
                show_progress_bar=False,
            )

            # 转换为列表格式
            embeddings_list = embeddings.tolist()

            logger.info(
                "embedding_success",
                model_id=self.config.model_id,
                num_texts=len(texts),
                dimensions=self.dimensions
            )

            return EmbeddingResponse(
                embeddings=embeddings_list,
                model_id=self.config.model_id,
                dimensions=self.dimensions,
            )

        except Exception as e:
            logger.error(
                "embedding_failed",
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
            # 尝试向量化一个简单的文本
            test_text = ["健康检查"]
            self.model.encode(test_text, show_progress_bar=False)

            logger.info(
                "embedding_health_check_success",
                model_id=self.config.model_id
            )
            return True

        except Exception as e:
            logger.error(
                "embedding_health_check_failed",
                model_id=self.config.model_id,
                error=str(e)
            )
            return False

    def get_dimensions(self) -> int:
        """获取向量维度

        Returns:
            向量维度
        """
        return self.dimensions


def create_local_embedding_provider(
    model_id: str = "bge-large-zh",
    model_path: str = "/models/bge-large-zh-v1.5",
) -> LocalEmbeddingProvider:
    """创建本地向量化提供者

    Args:
        model_id: 模型ID
        model_path: 模型路径

    Returns:
        本地向量化提供者实例
    """
    config = ModelConfig(
        model_id=model_id,
        model_name=model_id,
        model_type=ModelType.EMBEDDING,
        deployment_type=DeploymentType.LOCAL,
        provider="sentence-transformers",
        model_path=model_path,
    )

    return LocalEmbeddingProvider(config)
