"""数据级别出网闸门

根据数据级别拦截敏感数据调用外部模型，确保数据安全。
"""

from typing import Optional
from functools import lru_cache

from app.llm.base import DataLevel, DeploymentType, ModelConfig
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


class GatewayError(Exception):
    """闸门错误"""
    pass


class DataLevelGateway:
    """数据级别出网闸门

    核心安全机制：
    1. 敏感及以上级别禁止使用外部模型
    2. 涉密数据直接拒绝处理
    3. 所有出网请求记录审计日志
    """

    def __init__(self):
        """初始化闸门"""
        self.enabled = settings.ENABLE_DATA_LEVEL_GATEWAY
        self.allowed_external_domains = set(settings.ALLOWED_EXTERNAL_MODELS)
        logger.info(
            "gateway_initialized",
            enabled=self.enabled,
            allowed_domains=list(self.allowed_external_domains)
        )

    def check_access(
        self,
        data_level: DataLevel,
        model_config: ModelConfig,
        context: Optional[dict] = None
    ) -> tuple[bool, Optional[str]]:
        """检查是否允许访问

        Args:
            data_level: 数据级别
            model_config: 模型配置
            context: 上下文信息（用于审计）

        Returns:
            (是否允许, 拒绝原因)
        """
        # 如果闸门未启用，直接通过
        if not self.enabled:
            logger.warning("gateway_disabled", data_level=data_level)
            return True, None

        # 涉密数据直接拒绝
        if data_level == DataLevel.CLASSIFIED:
            reason = "涉密数据禁止进行AI处理"
            logger.error(
                "gateway_blocked_classified",
                data_level=data_level,
                model_id=model_config.model_id,
                context=context
            )
            return False, reason

        # 敏感数据强制使用本地模型
        if data_level == DataLevel.SENSITIVE:
            if model_config.deployment_type == DeploymentType.EXTERNAL:
                reason = "敏感数据禁止使用外部模型"
                logger.warning(
                    "gateway_blocked_sensitive",
                    data_level=data_level,
                    model_id=model_config.model_id,
                    deployment_type=model_config.deployment_type,
                    context=context
                )
                return False, reason

        # 内部数据：外部模型需要在白名单中
        if data_level == DataLevel.INTERNAL:
            if model_config.deployment_type == DeploymentType.EXTERNAL:
                # 检查是否在白名单中
                if not self._is_allowed_external(model_config):
                    reason = f"外部模型 {model_config.provider} 不在白名单中"
                    logger.warning(
                        "gateway_blocked_internal",
                        data_level=data_level,
                        model_id=model_config.model_id,
                        provider=model_config.provider,
                        context=context
                    )
                    return False, reason

        # 公开数据：允许所有模型
        # 记录审计日志
        logger.info(
            "gateway_allowed",
            data_level=data_level,
            model_id=model_config.model_id,
            deployment_type=model_config.deployment_type,
            provider=model_config.provider,
            context=context
        )

        return True, None

    def _is_allowed_external(self, model_config: ModelConfig) -> bool:
        """检查外部模型是否在白名单中

        Args:
            model_config: 模型配置

        Returns:
            是否允许
        """
        # 如果白名单为空，拒绝所有外部模型
        if not self.allowed_external_domains:
            return False

        # 检查供应商是否在白名单中
        provider_lower = model_config.provider.lower()
        for allowed in self.allowed_external_domains:
            if allowed.lower() in provider_lower:
                return True

        # 检查端点域名是否在白名单中
        if model_config.endpoint:
            endpoint_lower = model_config.endpoint.lower()
            for allowed in self.allowed_external_domains:
                if allowed.lower() in endpoint_lower:
                    return True

        return False

    def validate_and_block(
        self,
        data_level: DataLevel,
        model_config: ModelConfig,
        context: Optional[dict] = None
    ) -> None:
        """验证并在不通过时抛出异常

        Args:
            data_level: 数据级别
            model_config: 模型配置
            context: 上下文信息

        Raises:
            GatewayError: 如果不允许访问
        """
        allowed, reason = self.check_access(data_level, model_config, context)

        if not allowed:
            # 记录安全事件
            logger.error(
                "gateway_violation",
                data_level=data_level,
                model_id=model_config.model_id,
                provider=model_config.provider,
                deployment_type=model_config.deployment_type,
                reason=reason,
                context=context
            )
            raise GatewayError(reason)

    def add_allowed_domain(self, domain: str) -> None:
        """添加允许的外部域名

        Args:
            domain: 域名
        """
        self.allowed_external_domains.add(domain)
        logger.info("gateway_domain_added", domain=domain)

    def remove_allowed_domain(self, domain: str) -> None:
        """移除允许的外部域名

        Args:
            domain: 域名
        """
        self.allowed_external_domains.discard(domain)
        logger.info("gateway_domain_removed", domain=domain)

    def get_allowed_domains(self) -> list[str]:
        """获取允许的外部域名列表

        Returns:
            域名列表
        """
        return list(self.allowed_external_domains)


@lru_cache
def get_gateway() -> DataLevelGateway:
    """获取闸门单例

    Returns:
        闸门实例
    """
    return DataLevelGateway()
