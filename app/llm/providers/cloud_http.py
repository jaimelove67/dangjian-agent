"""百炼异步 HTTP 适配；密钥按请求传递，错误不回显供应商响应正文。"""

from typing import Any

import httpx

from app.core.config import settings
from app.llm.base import BaseModelProvider, EmbeddingResponse, ModelConfig, ModelResponse
from app.llm.errors import ModelUnavailableError


def cloud_endpoint(path: str) -> str:
    return settings.DASHSCOPE_BASE_URL.rstrip("/") + path


class CloudHTTPProvider(BaseModelProvider):
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        if not config.api_key or not config.endpoint:
            raise ValueError("云端模型需要 API Key 和接口地址")

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.MODEL_TIMEOUT_SECONDS, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.config.endpoint,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
            if response.status_code != 200:
                raise ModelUnavailableError(
                    f"云端模型调用失败（HTTP {response.status_code}），请检查模型配置或服务状态"
                )
            body = response.json()
            if not isinstance(body, dict) or body.get("error") or body.get("code"):
                raise ModelUnavailableError("云端模型返回错误，请检查模型配置或服务状态")
            return body
        except (httpx.HTTPError, ValueError):
            raise ModelUnavailableError("云端模型连接失败或响应无效") from None

    async def generate(self, prompt: str, **kwargs) -> ModelResponse:
        raise NotImplementedError("该模型不支持文本生成")

    async def embed(self, texts: list[str], **kwargs) -> EmbeddingResponse:
        raise NotImplementedError("该模型不支持向量化")

    async def health_check(self) -> bool:
        raise NotImplementedError
