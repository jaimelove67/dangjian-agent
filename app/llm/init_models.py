"""模型初始化脚本

加载模型配置并注册到系统中。
"""

import os
from typing import Optional

from app.llm.registry import get_model_registry
from app.llm.router import get_model_router
from app.llm.gateway import get_gateway
from app.llm.providers.qwen import create_qwen_provider
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

    # ==================== 注册通义千问模型 ====================
    if settings.QWEN_API_KEY:
        try:
            qwen_provider = create_qwen_provider(
                model_id="qwen-turbo",
                model_name="qwen-turbo",
                api_key=settings.QWEN_API_KEY,
                max_tokens=4096,
                temperature=0.7,
            )
            registry.register(qwen_provider)
            logger.info("qwen_model_registered", model_id="qwen-turbo")

            # 添加通义千问到白名单
            gateway.add_allowed_domain("dashscope.aliyuncs.com")

        except Exception as e:
            logger.error("failed_to_register_qwen", error=str(e))
    else:
        logger.warning("qwen_api_key_not_configured")

    # ==================== 注册本地向量化模型 ====================
    try:
        # 检查模型路径是否存在
        embedding_path = settings.EMBEDDING_MODEL_PATH

        # 如果模型路径不存在，尝试下载或使用默认模型名
        if not os.path.exists(embedding_path):
            logger.warning(
                "embedding_model_path_not_found",
                path=embedding_path,
                using_default="BAAI/bge-large-zh-v1.5"
            )
            embedding_path = "BAAI/bge-large-zh-v1.5"

        embedding_provider = create_local_embedding_provider(
            model_id="bge-large-zh",
            model_path=embedding_path,
        )
        registry.register(embedding_provider)
        logger.info(
            "embedding_model_registered",
            model_id="bge-large-zh",
            dimensions=embedding_provider.get_dimensions()
        )

    except Exception as e:
        logger.error("failed_to_register_embedding", error=str(e))

    # ==================== 配置路由规则 ====================
    # 公开数据优先外部模型（如果有）
    if settings.QWEN_API_KEY:
        router.register_route(
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.QA,
            model_id="qwen-turbo"
        )
        router.register_route(
            data_level=DataLevel.PUBLIC,
            task_type=TaskType.SUMMARIZE,
            model_id="qwen-turbo"
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
