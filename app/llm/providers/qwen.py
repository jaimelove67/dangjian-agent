"""通义千问模型提供者

接入阿里云通义千问大模型服务。
"""

from typing import List, Optional
import dashscope
from dashscope import Generation

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


class QwenProvider(BaseModelProvider):
    """通义千问模型提供者"""

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
            raise ValueError("Qwen API Key is required")

        logger.info(
            "qwen_provider_initialized",
            model_id=config.model_id,
            model_name=config.model_name
        )

    async def generate(
        self,
        prompt: str,
        **kwargs
    ) -> ModelResponse:
        """生成文本

        Args:
            prompt: 输入提示词
            **kwargs: 额外参数

        Returns:
            模型响应
        """
        try:
            # 合并参数
            params = {
                'model': self.config.model_name,
                'prompt': prompt,
                'max_tokens': kwargs.get('max_tokens', self.config.max_tokens),
                'temperature': kwargs.get('temperature', self.config.temperature),
            }

            # 调用通义千问 API
            response = Generation.call(**params)

            if response.status_code == 200:
                output = response.output
                content = output.get('text', '')

                # 提取使用情况
                usage = None
                if hasattr(response, 'usage'):
                    usage = {
                        'prompt_tokens': response.usage.get('input_tokens', 0),
                        'completion_tokens': response.usage.get('output_tokens', 0),
                        'total_tokens': response.usage.get('total_tokens', 0),
                    }

                logger.info(
                    "qwen_generate_success",
                    model_id=self.config.model_id,
                    prompt_length=len(prompt),
                    response_length=len(content),
                    usage=usage
                )

                return ModelResponse(
                    content=content,
                    model_id=self.config.model_id,
                    usage=usage,
                    metadata={
                        'finish_reason': output.get('finish_reason'),
                        'request_id': response.request_id,
                    }
                )
            else:
                error_msg = f"Qwen API error: {response.code} - {response.message}"
                logger.error(
                    "qwen_generate_error",
                    model_id=self.config.model_id,
                    error=error_msg
                )
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(
                "qwen_generate_exception",
                model_id=self.config.model_id,
                error=str(e)
            )
            raise

    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> EmbeddingResponse:
        """文本向量化

        通义千问的向量化模型需要单独调用，这里暂不实现。
        向量化功能由本地模型提供。

        Args:
            texts: 文本列表
            **kwargs: 额外参数

        Raises:
            NotImplementedError: 通义千问暂不支持向量化
        """
        raise NotImplementedError(
            "Qwen provider does not support embedding. "
            "Use local embedding model instead."
        )

    async def health_check(self) -> bool:
        """健康检查

        Returns:
            是否健康
        """
        try:
            # 发送一个简单的请求测试连接
            response = Generation.call(
                model=self.config.model_name,
                prompt="Hello",
                max_tokens=10
            )

            is_healthy = response.status_code == 200

            logger.info(
                "qwen_health_check",
                model_id=self.config.model_id,
                healthy=is_healthy
            )

            return is_healthy

        except Exception as e:
            logger.error(
                "qwen_health_check_failed",
                model_id=self.config.model_id,
                error=str(e)
            )
            return False


def create_qwen_provider(
    model_id: str = "qwen-turbo",
    model_name: str = "qwen-turbo",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> QwenProvider:
    """创建通义千问提供者

    Args:
        model_id: 模型ID
        model_name: 模型名称
        api_key: API Key
        max_tokens: 最大token数
        temperature: 温度参数

    Returns:
        通义千问提供者实例
    """
    config = ModelConfig(
        model_id=model_id,
        model_name=model_name,
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="qwen",
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    return QwenProvider(config)
