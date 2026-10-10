"""百炼云端向量化：固定 1024 维、每批至多 20 条，保留输入顺序。"""

import asyncio
import logging
import math

from app.llm.base import DeploymentType, EmbeddingResponse, ModelConfig, ModelType
from app.llm.errors import ModelUnavailableError
from app.llm.providers.cloud_http import CloudHTTPProvider, cloud_endpoint

logger = logging.getLogger(__name__)


class DashScopeEmbeddingProvider(CloudHTTPProvider):
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._single_input_only = False

    async def embed(self, texts: list[str], **kwargs) -> EmbeddingResponse:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), 20):
            batch = texts[start : start + 20]
            embeddings.extend(
                await self._embed_singly(batch)
                if self._single_input_only
                else await self._request_batch(batch)
            )
        return EmbeddingResponse(
            embeddings=embeddings, model_id=self.config.model_id, dimensions=1024
        )

    async def _request_batch(self, batch: list[str]) -> list[list[float]]:
        body = await self._post(
            {
                "model": self.config.model_name,
                "input": batch,
                "dimensions": 1024,
                "encoding_format": "float",
            }
        )
        try:
            rows = body["data"]
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise ValueError
            if any(type(row["index"]) is not int for row in rows):
                raise ValueError
            for row in rows:
                vector = row["embedding"]
                if (
                    not isinstance(vector, list)
                    or len(vector) != 1024
                    or any(
                        type(value) not in (float, int) or not math.isfinite(value)
                        for value in vector
                    )
                ):
                    raise ValueError
            indices = [row["index"] for row in rows]
            if sorted(indices) != list(range(len(batch))):
                # Flash 的实测批响应重复返回 index=0；不能猜测数组顺序。
                if (
                    self.config.model_name == "qwen3.7-text-embedding-flash"
                    and len(batch) > 1
                    and set(indices) == {0}
                ):
                    self._single_input_only = True
                    logger.warning("embedding_batch_indices_repeated_using_single_requests")
                    return await self._embed_singly(batch)
                raise ValueError
            return [row["embedding"] for row in sorted(rows, key=lambda row: row["index"])]
        except (KeyError, TypeError, ValueError):
            raise ModelUnavailableError("向量模型返回数量、索引或维度异常") from None

    async def _embed_singly(self, texts: list[str]) -> list[list[float]]:
        semaphore = asyncio.Semaphore(4)
        aborted = False

        async def one(text: str) -> list[float]:
            nonlocal aborted
            async with semaphore:
                if aborted:
                    raise ModelUnavailableError("向量化批次已中止")
                try:
                    return (await self._request_batch([text]))[0]
                except BaseException:
                    aborted = True
                    raise

        tasks = [asyncio.create_task(one(text)) for text in texts]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            # 失败或超时时取消同批其他调用，不能遗留后台请求。
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def health_check(self) -> bool:
        try:
            await self.embed(["健康检查"])
            return True
        except Exception:
            return False


def create_dashscope_embedding_provider(
    model_id: str = "cloud-embedding",
    model_name: str = "qwen3.7-text-embedding-flash",
    api_key: str = None,
) -> DashScopeEmbeddingProvider:
    return DashScopeEmbeddingProvider(
        ModelConfig(
            model_id=model_id,
            model_name=model_name,
            model_type=ModelType.EMBEDDING,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
            endpoint=cloud_endpoint("/compatible-mode/v1/embeddings"),
            api_key=api_key,
        )
    )
