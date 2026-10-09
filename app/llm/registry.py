"""模型注册表

管理所有可用的模型提供者，支持动态注册和查询。
"""

from typing import Dict, Optional, List
from functools import lru_cache

from app.llm.base import (
    BaseModelProvider,
    ModelConfig,
    ModelType,
    DeploymentType,
)
import structlog

logger = structlog.get_logger(__name__)


class ModelRegistry:
    """模型注册表

    负责管理所有模型提供者的注册、查询和生命周期。
    """

    def __init__(self):
        """初始化注册表"""
        self._providers: Dict[str, BaseModelProvider] = {}
        self._configs: Dict[str, ModelConfig] = {}
        logger.info("model_registry_initialized")

    def register(
        self,
        provider: BaseModelProvider,
    ) -> None:
        """注册模型提供者

        Args:
            provider: 模型提供者实例

        Raises:
            ValueError: 如果模型ID已存在
        """
        model_id = provider.get_model_id()

        if model_id in self._providers:
            raise ValueError(f"Model {model_id} already registered")

        self._providers[model_id] = provider
        self._configs[model_id] = provider.config

        logger.info(
            "model_registered",
            model_id=model_id,
            provider=provider.config.provider,
            model_type=provider.config.model_type,
            deployment_type=provider.config.deployment_type,
        )

    def unregister(self, model_id: str) -> None:
        """注销模型提供者

        Args:
            model_id: 模型ID
        """
        if model_id in self._providers:
            del self._providers[model_id]
            del self._configs[model_id]
            logger.info("model_unregistered", model_id=model_id)

    def get_provider(self, model_id: str) -> Optional[BaseModelProvider]:
        """获取模型提供者

        Args:
            model_id: 模型ID

        Returns:
            模型提供者实例，如果不存在返回None
        """
        return self._providers.get(model_id)

    def get_config(self, model_id: str) -> Optional[ModelConfig]:
        """获取模型配置

        Args:
            model_id: 模型ID

        Returns:
            模型配置，如果不存在返回None
        """
        return self._configs.get(model_id)

    def list_models(
        self,
        model_type: Optional[ModelType] = None,
        deployment_type: Optional[DeploymentType] = None,
    ) -> List[str]:
        """列出模型

        Args:
            model_type: 按模型类型过滤
            deployment_type: 按部署类型过滤

        Returns:
            模型ID列表
        """
        models = []

        for model_id, config in self._configs.items():
            # 类型过滤
            if model_type and config.model_type != model_type:
                continue

            # 部署类型过滤
            if deployment_type and config.deployment_type != deployment_type:
                continue

            models.append(model_id)

        return models

    def has_local_model(self, model_type: ModelType) -> bool:
        """检查是否有指定类型的本地模型

        Args:
            model_type: 模型类型

        Returns:
            是否有本地模型
        """
        local_models = self.list_models(
            model_type=model_type,
            deployment_type=DeploymentType.LOCAL
        )
        return len(local_models) > 0

    async def health_check_all(self) -> Dict[str, bool]:
        """对所有模型进行健康检查

        Returns:
            模型ID -> 健康状态的映射
        """
        results = {}

        for model_id, provider in self._providers.items():
            try:
                is_healthy = await provider.health_check()
                results[model_id] = is_healthy

                if not is_healthy:
                    logger.warning(
                        "model_health_check_failed",
                        model_id=model_id
                    )
            except Exception as e:
                logger.error(
                    "model_health_check_error",
                    model_id=model_id,
                    error=str(e)
                )
                results[model_id] = False

        return results

    def get_stats(self) -> Dict[str, any]:
        """获取注册表统计信息

        Returns:
            统计信息
        """
        stats = {
            "total": len(self._providers),
            "by_type": {},
            "by_deployment": {},
        }

        for config in self._configs.values():
            # 按模型类型统计
            model_type = config.model_type.value
            stats["by_type"][model_type] = stats["by_type"].get(model_type, 0) + 1

            # 按部署类型统计
            deployment_type = config.deployment_type.value
            stats["by_deployment"][deployment_type] = \
                stats["by_deployment"].get(deployment_type, 0) + 1

        return stats


@lru_cache
def get_model_registry() -> ModelRegistry:
    """获取模型注册表单例

    Returns:
        模型注册表实例
    """
    return ModelRegistry()
