"""Qwen 云端聊天模型，使用百炼兼容聊天接口。"""

from typing import Optional

from app.llm.base import DeploymentType, ModelConfig, ModelResponse, ModelType
from app.llm.errors import ModelUnavailableError
from app.llm.providers.cloud_http import CloudHTTPProvider, cloud_endpoint


class DashScopeProvider(CloudHTTPProvider):
    async def generate(self, prompt: str, **kwargs) -> ModelResponse:
        body = await self._post(
            {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "temperature": kwargs.get("temperature", self.config.temperature),
                "enable_thinking": False,
            }
        )
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
            return ModelResponse(
                content=content,
                model_id=self.config.model_id,
                usage=body.get("usage"),
                metadata={
                    "finish_reason": choice.get("finish_reason"),
                    "request_id": body.get("id"),
                },
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelUnavailableError("聊天模型响应格式异常") from None

    async def health_check(self) -> bool:
        try:
            await self.generate("健康检查", max_tokens=16)
            return True
        except Exception:
            return False


def create_dashscope_provider(
    model_id: str = "cloud-llm",
    model_name: str = "qwen3.8-flash",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> DashScopeProvider:
    return DashScopeProvider(
        ModelConfig(
            model_id=model_id,
            model_name=model_name,
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
            endpoint=cloud_endpoint("/compatible-mode/v1/chat/completions"),
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    )


QwenProvider = DashScopeProvider
create_qwen_provider = create_dashscope_provider
