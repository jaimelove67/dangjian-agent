"""FastAPI 应用主入口"""

import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import admin, auth, embeddings, health, knowledge, member, qa, user
from app.core import tenant as _tenant  # noqa: F401  导入即注册租户隔离事件监听
from app.core.cache import redis_manager
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.security import SecurityError
from app.core.tenant import TenantIsolationError
from app.core.token_revocation import AuthStoreUnavailable
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import GatewayError
from app.llm.router import RouterError
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

    from app.llm.init_models import init_models

    init_models()

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
    provided_id = request.headers.get("X-Request-ID", "")
    trace_id = (
        provided_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", provided_id) else uuid.uuid4().hex
    )
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace_id
    return response


# 注册路由
app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])
app.include_router(auth.router, prefix="/api/v1", tags=["鉴权"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["知识库"])
app.include_router(embeddings.router, prefix="/api/v1", tags=["向量化"])
app.include_router(qa.router, prefix="/api/v1", tags=["知识问答"])
app.include_router(member.router, prefix="/api/v1", tags=["党员发展"])
app.include_router(user.router, prefix="/api/v1", tags=["兼容用户接口"])
app.include_router(admin.router, prefix="/api/v1", tags=["管理"])


# 全局异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    code = {
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
        422: ErrorCode.BUSINESS_ERROR,
        503: ErrorCode.SERVICE_UNAVAILABLE,
    }.get(
        exc.status_code, ErrorCode.PARAM_ERROR if exc.status_code < 500 else ErrorCode.SERVER_ERROR
    )
    message = str(detail)
    if isinstance(detail, dict):
        code = detail.get("code", code)
        message = detail.get("message") or "；".join(detail.get("errors", [])) or "请求参数不正确"
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "code": code,
            "message": message,
            "data": None,
            "detail": detail,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # 不返回 input / body，避免将密码或敏感材料回显到错误响应。
    errors = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "code": ErrorCode.PARAM_ERROR,
            "message": "请求参数校验失败",
            "data": None,
            "detail": errors,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(ModelUnavailableError)
@app.exception_handler(RouterError)
@app.exception_handler(AuthStoreUnavailable)
async def dependency_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    message = (
        "模型服务未就绪，请检查模型配置"
        if not isinstance(exc, AuthStoreUnavailable)
        else "认证存储暂不可用，请稍后重试"
    )
    return JSONResponse(
        status_code=503,
        content={
            "code": ErrorCode.SERVICE_UNAVAILABLE,
            "message": message,
            "data": None,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.exception_handler(GatewayError)
async def gateway_exception_handler(request: Request, exc: GatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "code": ErrorCode.FORBIDDEN,
            "message": "当前模型无法按数据安全政策处理此内容",
            "data": None,
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


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
async def tenant_isolation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
