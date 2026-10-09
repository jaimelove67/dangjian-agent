"""FastAPI 应用主入口"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.cache import redis_manager
from app.api.v1 import health

# 设置日志
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """应用生命周期管理"""
    # 启动时执行
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Application starting up...")
    logger.info(f"Environment: {settings.ENV}")
    logger.info(f"Debug mode: {settings.DEBUG}")

    # 初始化 Redis 连接
    try:
        await redis_manager.connect()
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")

    # TODO: 初始化数据库连接池
    # TODO: 加载模型配置

    yield

    # 关闭时执行
    logger.info("Application shutting down...")

    # 关闭 Redis 连接
    await redis_manager.disconnect()

    # TODO: 关闭数据库连接


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="基于 LangChain 的高校党建工作智能辅助系统",
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS 配置
if settings.ALLOWED_HOSTS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# 注册路由
app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "code": 50001,
            "message": "Internal server error",
            "data": None,
            "trace_id": getattr(request.state, "trace_id", "unknown"),
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
