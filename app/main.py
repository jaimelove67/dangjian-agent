"""FastAPI 应用主入口"""
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.cache import redis_manager
from app.core import tenant as _tenant  # noqa: F401  导入即注册租户隔离事件监听
from app.core.security import SecurityError
from app.core.tenant import TenantIsolationError
from app.api.v1 import auth, health, knowledge, user, qa
from app.schemas.common import ErrorCode

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

    # 初始化数据库连接
    try:
        from app.db.session import init_db
        await init_db()
    except Exception as e:
        logger.warning(f"Database connection failed: {e}")

    # TODO: 加载模型配置

    yield

    # 关闭时执行
    logger.info("Application shutting down...")

    # 关闭 Redis 连接
    await redis_manager.disconnect()

    # 关闭数据库连接
    try:
        from app.db.session import close_db
        await close_db()
    except Exception as e:
        logger.warning(f"Database close failed: {e}")


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


# 请求追踪 ID 中间件
@app.middleware("http")
async def trace_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """为每个请求生成/透传 trace_id，便于审计与排障"""
    trace_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    return response


# 注册路由
app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])
app.include_router(auth.router, prefix="/api/v1", tags=["鉴权"])
app.include_router(user.router, prefix="/api/v1", tags=["用户"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["知识库"])
app.include_router(qa.router, prefix="/api/v1", tags=["知识问答"])


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


# 认证 / 租户隔离异常处理
@app.exception_handler(SecurityError)
async def security_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """认证失败"""
    return JSONResponse(
        status_code=401,
        content={
            "code": ErrorCode.UNAUTHORIZED,
            "message": str(exc) or "认证失败",
            "data": None,
            "trace_id": getattr(request.state, "trace_id", "unknown"),
        },
    )


@app.exception_handler(TenantIsolationError)
async def tenant_isolation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """租户隔离校验失败"""
    return JSONResponse(
        status_code=403,
        content={
            "code": ErrorCode.TENANT_ISOLATION,
            "message": "租户隔离校验失败",
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
