"""阿里云 DashScope 模型提供者

接入阿里云 DashScope 服务，支持：
- DeepSeek 系列模型
- 通义千问系列模型
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


class DashScopeProvider(BaseModelProvider):
    """阿里云 DashScope 模型提供者

    支持通义千问和DeepSeek等模型
    """

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
            "dashscope_provider_initialized",
            model_id=config.model_id,
            model_name=config.model_name,
            provider=config.provider
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
                    "dashscope_generate_success",
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
                error_msg = f"DashScope API error: {response.code} - {response.message}"
                logger.error(
                    "dashscope_generate_error",
                    model_id=self.config.model_id,
                    error=error_msg
                )
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(
                "dashscope_generate_exception",
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

        DashScope LLM提供者不支持向量化。
        向量化功能由专用的DashScopeEmbeddingProvider提供。

        Args:
            texts: 文本列表
            **kwargs: 额外参数

        Raises:
            NotImplementedError: LLM提供者不支持向量化
        """
        raise NotImplementedError(
            "DashScope LLM provider does not support embedding. "
            "Use DashScopeEmbeddingProvider instead."
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
                "dashscope_health_check",
                model_id=self.config.model_id,
                healthy=is_healthy
            )

            return is_healthy

        except Exception as e:
            logger.error(
                "dashscope_health_check_failed",
                model_id=self.config.model_id,
                error=str(e)
            )
            return False


def create_dashscope_provider(
    model_id: str = "deepseek-v4.1-flash",
    model_name: str = "deepseek-v4.1-flash",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> DashScopeProvider:
    """创建阿里云DashScope提供者

    Args:
        model_id: 模型ID
        model_name: 模型名称（如deepseek-v4.1-flash, qwen-turbo等）
        api_key: DashScope API Key
        max_tokens: 最大token数
        temperature: 温度参数

    Returns:
        DashScope提供者实例
    """
    config = ModelConfig(
        model_id=model_id,
        model_name=model_name,
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="dashscope",
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    return DashScopeProvider(config)


# 兼容性别名
QwenProvider = DashScopeProvider
create_qwen_provider = create_dashscope_provider
