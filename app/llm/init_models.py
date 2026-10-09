"""模型初始化脚本

加载模型配置并注册到系统中。
支持阿里云DashScope服务（DeepSeek和Qwen向量化模型）。
"""

import os
from typing import Optional

from app.llm.registry import get_model_registry
from app.llm.router import get_model_router
from app.llm.gateway import get_gateway
from app.llm.providers.qwen import create_dashscope_provider
from app.llm.providers.dashscope_embedding import create_dashscope_embedding_provider
from app.llm.providers.local_embedding import create_local_embedding_provider
from app.llm.base import DataLevel, TaskType
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


def init_models() -> None:
    """初始化所有模型"""
    registry = get_model_registry()
    router = get_model_router()
    gateway = get_gateway()

    logger.info("initializing_models")

    # ==================== 注册 DeepSeek 模型（通过阿里云DashScope） ====================
    if settings.DASHSCOPE_API_KEY:
        try:
            deepseek_provider = create_dashscope_provider(
                model_id="deepseek-flash",
                model_name=settings.LLM_MODEL_NAME,
                api_key=settings.DASHSCOPE_API_KEY,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
            )
            registry.register(deepseek_provider)
            logger.info(
                "deepseek_model_registered",
                model_id="deepseek-flash",
                model_name=settings.LLM_MODEL_NAME
            )

            # 添加阿里云到白名单
            gateway.add_allowed_domain("dashscope.aliyuncs.com")

        except Exception as e:
            logger.error("failed_to_register_deepseek", error=str(e))
    else:
        logger.warning("dashscope_api_key_not_configured")

    # ==================== 注册阿里云向量化模型 ====================
    if settings.DASHSCOPE_API_KEY:
        try:
            qwen_embedding_provider = create_dashscope_embedding_provider(
                model_id="qwen-embedding",
                model_name=settings.EMBEDDING_MODEL_NAME,
                api_key=settings.DASHSCOPE_API_KEY,
            )
            registry.register(qwen_embedding_provider)
            logger.info(
                "qwen_embedding_model_registered",
                model_id="qwen-embedding",
                model_name=settings.EMBEDDING_MODEL_NAME
            )

        except Exception as e:
            logger.error("failed_to_register_qwen_embedding", error=str(e))
    else:
        logger.warning("dashscope_api_key_not_configured_for_embedding")

    # ==================== 配置路由规则 ====================
    if settings.DASHSCOPE_API_KEY:
        # 公开数据使用外部模型（DeepSeek）
        router.register_route(
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.QA,
            model_id="deepseek-flash"
        )
        router.register_route(
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.SUMMARIZE,
            model_id="deepseek-flash"
        )
        router.register_route(
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.EXTRACT,
            model_id="deepseek-flash"
        )

    # ==================== 输出初始化结果 ====================
    stats = registry.get_stats()
    logger.info(
        "models_initialized",
        total_models=stats["total"],
        by_type=stats["by_type"],
        by_deployment=stats["by_deployment"],
    )

    # 输出路由规则
    rules = router.get_routing_rules()
    logger.info("routing_rules_configured", rules_count=len(rules))

    # 输出闸门配置
    logger.info(
        "gateway_configured",
        enabled=gateway.enabled,
        allowed_domains=gateway.get_allowed_domains()
    )


async def health_check_models() -> dict:
    """检查所有模型的健康状态

    Returns:
        健康状态报告
    """
    registry = get_model_registry()
    results = await registry.health_check_all()

    logger.info("model_health_check_completed", results=results)

    return results


if __name__ == "__main__":
    # 配置日志
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    # 初始化模型
    init_models()

    # 健康检查
    import asyncio
    results = asyncio.run(health_check_models())

    print("\n========== 模型健康检查结果 ==========")
    for model_id, is_healthy in results.items():
        status = "✓ 健康" if is_healthy else "✗ 不健康"
        print(f"{model_id}: {status}")
