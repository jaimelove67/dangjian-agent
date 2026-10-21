"""Qwen 视觉模型：把图片里的文字转录成纯文本（扫描件 / 拍照件）。

与 ``qwen.py`` 的区别只在请求体的 ``content``：文本模型发字符串，视觉模型发
"图片 + 指令"数组。其余（密钥、超时、错误收敛、白名单）沿用同一套
``CloudHTTPProvider``，不在视觉链路上另开一套出网规则。

**只做转录，不做回答**：提示词明确禁止总结与补充，因为这个输出会被当作"用户材料"
送进问答提示词——如果 OCR 阶段就开始解释，后面的引用边界就说不清了。
"""

from typing import Any, Optional

from app.llm.base import DeploymentType, ModelConfig, ModelResponse, ModelType
from app.llm.errors import ModelUnavailableError
from app.llm.providers.cloud_http import CloudHTTPProvider, cloud_endpoint

#: 单张图片的 MIME：扫描件渲染与用户上传都会先规整成 PNG
DEFAULT_IMAGE_MIME = "image/png"


def build_image_content(images: list[bytes], mime: str = DEFAULT_IMAGE_MIME) -> list[dict[str, Any]]:
    """把图片字节流组装成兼容接口的 ``image_url`` 内容块"""
    import base64

    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
        }
        for data in images
        if data
    ]


class DashScopeVisionProvider(CloudHTTPProvider):
    """百炼兼容接口的视觉识别模型"""

    async def generate(self, prompt: str, **kwargs: Any) -> ModelResponse:
        images: list[bytes] = list(kwargs.get("images") or [])
        if not images:
            raise ModelUnavailableError("图片文字识别缺少图片内容")
        # 图在前、指令在后：与百炼文档中的 OCR 示例一致，识别顺序更稳定
        content: list[dict[str, Any]] = build_image_content(images, kwargs.get("mime", DEFAULT_IMAGE_MIME))
        content.append({"type": "text", "text": prompt})
        body = await self._post(
            {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
                "temperature": 0,
            }
        )
        try:
            choice = body["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError
            return ModelResponse(
                content=text,
                model_id=self.config.model_id,
                usage=body.get("usage"),
                metadata={
                    "finish_reason": choice.get("finish_reason"),
                    "request_id": body.get("id"),
                },
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelUnavailableError("图片文字识别响应格式异常") from None

    async def health_check(self) -> bool:
        """配置齐全即视为可用：OCR 是按张付费的，就绪检查不应该替用户花钱。"""
        return True


def create_dashscope_vision_provider(
    model_id: str = "cloud-vision",
    model_name: str = "qwen-vl-ocr",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> DashScopeVisionProvider:
    return DashScopeVisionProvider(
        ModelConfig(
            model_id=model_id,
            model_name=model_name,
            model_type=ModelType.VISION,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
            endpoint=cloud_endpoint("/compatible-mode/v1/chat/completions"),
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    )
