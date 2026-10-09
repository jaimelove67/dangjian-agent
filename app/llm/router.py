"""模型路由器

根据数据级别和任务类型选择合适的模型。
"""

from typing import Optional, Dict
from functools import lru_cache

from app.llm.base import (
    DataLevel,
    TaskType,
    ModelType,
    DeploymentType,
    BaseModelProvider,
)
from app.llm.registry import get_model_registry
from app.llm.gateway import get_gateway, GatewayError
import structlog

logger = structlog.get_logger(__name__)


class RouterError(Exception):
    """路由错误"""
    pass


class ModelRouter:
    """模型路由器

    根据数据级别和任务类型选择合适的模型。
    路由策略：
    1. 敏感数据强制使用本地模型
    2. 内部数据优先本地模型
    3. 公开数据可以使用外部模型
    4. 无可用模型时抛出异常
    """

    def __init__(self):
        """初始化路由器"""
        self.registry = get_model_registry()
        self.gateway = get_gateway()
        self._route_cache: Dict[tuple, str] = {}
        self._routing_rules: Dict[tuple, str] = {}
        logger.info("model_router_initialized")

    def register_route(
        self,
        data_level: DataLevel,
        task_type: TaskType,
        model_id: str,
    ) -> None:
        """注册路由规则

        Args:
            data_level: 数据级别
            task_type: 任务类型
            model_id: 模型ID
        """
        key = (data_level, task_type)
        self._routing_rules[key] = model_id
        logger.info(
            "route_registered",
            data_level=data_level,
            task_type=task_type,
            model_id=model_id
        )

    def get_model(
        self,
        data_level: DataLevel,
        task_type: TaskType = TaskType.QA,
        model_type: ModelType = ModelType.LLM,
        context: Optional[dict] = None,
    ) -> BaseModelProvider:
        """获取模型

        Args:
            data_level: 数据级别
            task_type: 任务类型
            model_type: 模型类型
            context: 上下文信息（用于审计）

        Returns:
            模型提供者

        Raises:
            RouterError: 无可用模型
            GatewayError: 闸门拦截
        """
        # 1. 检查是否有配置的路由规则
        model_id = self._get_configured_model(data_level, task_type)

        # 2. 如果没有配置规则，使用默认策略
        if not model_id:
            model_id = self._select_model_by_strategy(
                data_level,
                task_type,
                model_type
            )

        # 3. 获取模型提供者
        if not model_id:
            raise RouterError(
                f"No available model for data_level={data_level}, "
                f"task_type={task_type}, model_type={model_type}"
            )

        provider = self.registry.get_provider(model_id)
        if not provider:
            raise RouterError(f"Model {model_id} not found in registry")

        # 4. 通过闸门验证
        self.gateway.validate_and_block(
            data_level=data_level,
            model_config=provider.config,
            context=context
        )

        logger.info(
            "model_routed",
            data_level=data_level,
            task_type=task_type,
            model_type=model_type,
            model_id=model_id,
            context=context
        )

        return provider

    def _get_configured_model(
        self,
        data_level: DataLevel,
        task_type: TaskType
    ) -> Optional[str]:
        """获取配置的模型

        Args:
            data_level: 数据级别
            task_type: 任务类型

        Returns:
            模型ID，如果没有配置返回None
        """
        key = (data_level, task_type)
        return self._routing_rules.get(key)

    def _select_model_by_strategy(
        self,
        data_level: DataLevel,
        task_type: TaskType,
        model_type: ModelType,
    ) -> Optional[str]:
        """根据策略选择模型

        Args:
            data_level: 数据级别
            task_type: 任务类型
            model_type: 模型类型

        Returns:
            模型ID
        """
        # 策略1：敏感和涉密数据只能使用本地模型
        if data_level in [DataLevel.SENSITIVE, DataLevel.CLASSIFIED]:
            local_models = self.registry.list_models(
                model_type=model_type,
                deployment_type=DeploymentType.LOCAL
            )
            if local_models:
                return local_models[0]
            return None

        # 策略2：内部数据优先本地模型
        if data_level == DataLevel.INTERNAL:
            local_models = self.registry.list_models(
                model_type=model_type,
                deployment_type=DeploymentType.LOCAL
            )
            if local_models:
                return local_models[0]

            # 如果没有本地模型，尝试外部模型
            external_models = self.registry.list_models(
                model_type=model_type,
                deployment_type=DeploymentType.EXTERNAL
            )
            if external_models:
                return external_models[0]
            return None

        # 策略3：公开数据可以使用任何模型（优先外部模型降低成本）
        if data_level == DataLevel.PUBLIC:
            external_models = self.registry.list_models(
                model_type=model_type,
                deployment_type=DeploymentType.EXTERNAL
            )
            if external_models:
                return external_models[0]

            local_models = self.registry.list_models(
                model_type=model_type,
                deployment_type=DeploymentType.LOCAL
            )
            if local_models:
                return local_models[0]
            return None

        return None

    def clear_cache(self) -> None:
        """清空路由缓存"""
        self._route_cache.clear()
        logger.info("route_cache_cleared")

    def get_routing_rules(self) -> Dict[tuple, str]:
        """获取所有路由规则

        Returns:
            路由规则映射
        """
        return self._routing_rules.copy()

    def remove_route(
        self,
        data_level: DataLevel,
        task_type: TaskType
    ) -> None:
        """移除路由规则

        Args:
            data_level: 数据级别
            task_type: 任务类型
        """
        key = (data_level, task_type)
        if key in self._routing_rules:
            del self._routing_rules[key]
            logger.info(
                "route_removed",
                data_level=data_level,
                task_type=task_type
            )


@lru_cache
def get_model_router() -> ModelRouter:
    """获取模型路由器单例

    Returns:
        模型路由器实例
    """
    return ModelRouter()
