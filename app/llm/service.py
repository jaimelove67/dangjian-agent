"""模型服务统一接口

提供高层次的模型调用接口，封装路由、闸门和调用逻辑。
"""

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import structlog
from fastapi import HTTPException

from app.core.config import settings, tenant_config
from app.core.model_usage import record as record_usage
from app.core.model_usage import tracked
from app.core.rate_limit import check_model_budget
from app.core.tenant import get_tenant_id
from app.llm.base import (
    DataLevel,
    EmbeddingResponse,
    ModelResponse,
    ModelType,
    RerankResponse,
    TaskType,
)
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import GatewayError
from app.llm.router import RouterError, get_model_router

logger = structlog.get_logger(__name__)


class ModelService:
    """模型服务

    统一的模型调用接口，自动处理路由和安全检查。
    """

    def __init__(self) -> None:
        """初始化模型服务"""
        self.router = get_model_router()
        logger.info("model_service_initialized")

    @tracked("llm")
    async def generate(
        self,
        prompt: str,
        data_level: DataLevel,
        task_type: TaskType = TaskType.QA,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """生成文本

        Args:
            prompt: 输入提示词
            data_level: 数据级别
            task_type: 任务类型
            context: 上下文信息（用于审计）
            **kwargs: 额外参数传递给模型

        Returns:
            模型响应

        Raises:
            GatewayError: 闸门拦截
            RouterError: 路由错误
        """
        try:
            # 获取模型
            provider = self.router.get_model(
                data_level=data_level,
                task_type=task_type,
                model_type=ModelType.LLM,
                context=context,
            )

            # 调用模型
            await check_model_budget()
            response = await asyncio.wait_for(
                provider.generate(prompt, **kwargs), timeout=settings.MODEL_TIMEOUT_SECONDS
            )

            logger.info(
                "generate_success",
                model_id=response.model_id,
                data_level=data_level,
                task_type=task_type,
                prompt_length=len(prompt),
                response_length=len(response.content),
            )

            return response

        except GatewayError as e:
            logger.error(
                "generate_blocked_by_gateway",
                data_level=data_level,
                task_type=task_type,
                error=type(e).__name__,
                context=context,
            )
            raise

        except (RouterError, HTTPException):
            raise
        except Exception as e:
            logger.error(
                "generate_failed",
                data_level=data_level,
                task_type=task_type,
                error=type(e).__name__,
                context=context,
            )
            raise ModelUnavailableError("文本生成服务暂不可用，请检查模型配置或稍后重试") from e

    @tracked("embedding")
    async def embed(
        self,
        texts: List[str],
        data_level: DataLevel = DataLevel.PUBLIC,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """文本向量化

        Args:
            texts: 文本列表
            data_level: 数据级别
            context: 上下文信息（用于审计）
            **kwargs: 额外参数传递给模型

        Returns:
            向量化响应

        Raises:
            GatewayError: 闸门拦截
            RouterError: 路由错误
        """
        try:
            # 获取向量化模型
            provider = self.router.get_model(
                data_level=data_level,
                task_type=TaskType.QA,  # 向量化不区分任务类型
                model_type=ModelType.EMBEDDING,
                context=context,
            )

            # 调用模型
            await check_model_budget()
            response = await asyncio.wait_for(
                provider.embed(texts, **kwargs), timeout=settings.MODEL_TIMEOUT_SECONDS
            )

            logger.info(
                "embed_success",
                model_id=response.model_id,
                data_level=data_level,
                num_texts=len(texts),
                dimensions=response.dimensions,
            )

            return response

        except GatewayError as e:
            logger.error(
                "embed_blocked_by_gateway",
                data_level=data_level,
                num_texts=len(texts),
                error=type(e).__name__,
                context=context,
            )
            raise

        except (RouterError, HTTPException):
            raise
        except Exception as e:
            logger.error(
                "embed_failed",
                data_level=data_level,
                num_texts=len(texts),
                error=type(e).__name__,
                context=context,
            )
            raise ModelUnavailableError("向量模型暂不可用，请检查配置和服务状态") from None

    async def generate_stream(
        self,
        prompt: str,
        data_level: DataLevel,
        task_type: TaskType = TaskType.QA,
        system_prompt: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式生成文本

        Args:
            prompt: 输入提示词
            data_level: 数据级别
            task_type: 任务类型
            system_prompt: 系统提示词
            context: 上下文信息（用于审计）
            **kwargs: 额外参数传递给模型

        Yields:
            生成的文本片段

        Raises:
            GatewayError: 闸门拦截
            RouterError: 路由错误
        """
        started, outcome, model_id = time.monotonic(), "failed", "routing"
        emitted = False
        version = int(tenant_config.local(get_tenant_id() or "", "_config_version", 0))
        try:
            provider = self.router.get_model(
                data_level=data_level,
                task_type=task_type,
                model_type=ModelType.LLM,
                context=context,
            )
            model_id = provider.get_model_id()
            await check_model_budget()
            if system_prompt:
                kwargs["system_prompt"] = system_prompt
            # 一个明确的总期限同时约束流式响应与非流式降级。
            async with asyncio.timeout(settings.MODEL_TIMEOUT_SECONDS):
                stream = getattr(provider, "generate_stream", None)
                if stream is None:
                    response = await provider.generate(prompt, **kwargs)
                    emitted = bool(response.content.strip())
                    yield response.content
                else:
                    async for chunk in stream(prompt, **kwargs):
                        emitted = emitted or bool(chunk.strip())
                        yield chunk
            outcome = "success" if emitted else "invalid_response"
        except (GatewayError, RouterError, HTTPException):
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            raise ModelUnavailableError("流式模型服务暂不可用") from None
        finally:
            await record_usage(
                "llm", time.monotonic() - started, outcome, model_id, context, version
            )

    @tracked("reranker")
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int,
        data_level: DataLevel = DataLevel.PUBLIC,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> RerankResponse:
        """文档重排序

        Args:
            query: 查询文本
            documents: 文档列表
            top_k: 返回top-k结果
            data_level: 数据级别
            context: 上下文信息
            **kwargs: 额外参数

        Returns:
            重排序响应
        """
        try:
            # 获取重排模型
            provider = self.router.get_model(
                data_level=data_level,
                task_type=TaskType.QA,
                model_type=ModelType.RERANKER,
                context=context,
            )

            # 调用模型
            await check_model_budget()
            response = await asyncio.wait_for(
                provider.rerank(query, documents, top_k=top_k, **kwargs),
                timeout=settings.MODEL_TIMEOUT_SECONDS,
            )

            logger.info(
                "rerank_success",
                data_level=data_level,
                num_documents=len(documents),
                top_k=top_k,
            )

            return response

        except (GatewayError, RouterError, HTTPException):
            raise
        except Exception as e:
            logger.error(
                "rerank_failed",
                data_level=data_level,
                error=type(e).__name__,
                context=context,
            )
            raise ModelUnavailableError("重排模型暂不可用，请检查配置和服务状态") from None

    async def health_check(self) -> Dict[str, bool]:
        """健康检查所有模型

        Returns:
            模型健康状态映射
        """
        return await self.router.registry.health_check_all()


# 全局模型服务实例
_model_service: Optional[ModelService] = None


def get_model_service() -> ModelService:
    """获取模型服务单例

    Returns:
        模型服务实例
    """
    global _model_service
    if _model_service is None:
        _model_service = ModelService()
    return _model_service
