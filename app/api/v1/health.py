"""健康检查接口"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/health",
    summary="健康检查",
    description="检查服务是否正常运行",
    response_description="服务状态信息",
)
async def health_check() -> Dict[str, Any]:
    """健康检查接口

    Returns:
        服务状态信息
    """
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENV,
    }


@router.get(
    "/health/ready",
    summary="就绪检查",
    description="检查服务是否准备好接收请求（数据库、Redis等依赖服务是否可用）",
    response_description="服务就绪状态",
)
async def readiness_check() -> JSONResponse:
    """就绪检查接口

    检查所有依赖服务是否可用

    Returns:
        就绪状态
    """
    checks = {
        "database": "unknown",
        "redis": "unknown",
        "schema": "unknown",
        "models": "unknown",
    }

    # 检查 Redis 连接
    try:
        from app.core.cache import redis_manager

        await redis_manager.client.ping()
        checks["redis"] = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        checks["redis"] = "unhealthy"

    # 检查数据库连接
    try:
        from sqlalchemy import text

        from app.db.session import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            expected_tables = (
                "users",
                "tenants",
                "org_units",
                "knowledge_docs",
                "embedding_chunks",
                "audit_logs",
            )
            present = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables_ready = set(expected_tables).issubset({row[0] for row in present})
            fts_ready = await conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese_zh') "
                    "AND EXISTS(SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'knowledge_docs' AND column_name = 'search_vector')"
                )
            )
            checks["schema"] = "healthy" if tables_ready and fts_ready else "migration_required"
        checks["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["database"] = "unhealthy"

    from app.llm.init_models import model_readiness

    models = model_readiness()
    checks["models"] = (
        "healthy"
        if all(value != "missing" for value in models.values())
        else "configuration_required"
    )

    # 判断整体状态
    all_healthy = all(v == "healthy" for v in checks.values())
    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "model_capabilities": models,
        },
    )


@router.get(
    "/health/live",
    summary="存活检查",
    description="检查服务进程是否存活",
    response_description="存活状态",
)
async def liveness_check() -> Dict[str, str]:
    """存活检查接口

    Returns:
        存活状态
    """
    return {"status": "alive"}
