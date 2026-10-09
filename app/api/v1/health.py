"""健康检查接口"""
from typing import Dict, Any
import logging

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
    }

    # 检查 Redis 连接
    try:
        from app.core.cache import redis_manager
        await redis_manager.client.ping()
        checks["redis"] = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        checks["redis"] = f"unhealthy: {str(e)}"

    # TODO: 检查数据库连接
    # try:
    #     await check_database()
    #     checks["database"] = "healthy"
    # except Exception as e:
    #     checks["database"] = f"unhealthy: {str(e)}"

    # 暂时标记为未实现
    checks["database"] = "not_implemented"

    # 判断整体状态
    all_healthy = all(v == "healthy" for v in checks.values())
    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
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
