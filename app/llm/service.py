"""模型服务统一接口

提供高层次的模型调用接口，封装路由、闸门和调用逻辑。
"""

from typing import List, Optional, Dict, Any

from app.llm.base import (
    DataLevel,
    TaskType,
    ModelType,
    ModelResponse,
    EmbeddingResponse,
)
from app.llm.router import get_model_router
from app.llm.gateway import GatewayError
import structlog

logger = structlog.get_logger(__name__)


class ModelService:
    """模型服务

    统一的模型调用接口，自动处理路由和安全检查。
    """

    def __init__(self):
        """初始化模型服务"""
        self.router = get_model_router()
        logger.info("model_service_initialized")

    async def generate(
        self,
        prompt: str,
        data_level: DataLevel,
        task_type: TaskType = TaskType.QA,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
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
            response = await provider.generate(prompt, **kwargs)

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
                error=str(e),
                context=context,
            )
            raise

        except Exception as e:
            logger.error(
                "generate_failed",
                data_level=data_level,
                task_type=task_type,
                error=str(e),
                context=context,
            )
            raise

    async def embed(
        self,
        texts: List[str],
        data_level: DataLevel = DataLevel.PUBLIC,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
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
            response = await provider.embed(texts, **kwargs)

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
                error=str(e),
                context=context,
            )
            raise

        except Exception as e:
            logger.error(
                "embed_failed",
                data_level=data_level,
                num_texts=len(texts),
                error=str(e),
                context=context,
            )
            raise

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
