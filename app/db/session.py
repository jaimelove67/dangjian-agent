"""数据库会话管理

提供异步数据库连接和会话管理
"""

import logging
from typing import Any, AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

# sslmode 是 libpq 参数；转换为 asyncpg 原生 ssl，避免生产 URL 被错误传递。
database_url = make_url(settings.DATABASE_URL)
ssl_mode = database_url.query.get("sslmode") or database_url.query.get("ssl")
connect_args: dict[str, Any] = {"ssl": ssl_mode} if ssl_mode else {}
database_url = database_url.set(
    query={key: value for key, value in database_url.query.items() if key not in {"sslmode", "ssl"}}
)
# Pytest and synchronous HTTP test clients use multiple event loops. Never reuse
# an asyncpg connection from a closed test loop; the production pool stays bounded.
pool_options: dict[str, Any] = (
    {"poolclass": NullPool}
    if settings.ENV == "testing"
    else {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    }
)
engine = create_async_engine(
    database_url,
    connect_args=connect_args,
    echo=settings.DEBUG,
    hide_parameters=True,
    **pool_options,
    pool_pre_ping=True,  # 连接健康检查
)

# 创建会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话

    用于 FastAPI 依赖注入

    Yields:
        数据库会话
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """初始化数据库连接"""
    try:
        # 测试连接
        async with engine.begin() as conn:
            await conn.run_sync(lambda _: None)
        logger.info("Database connected successfully")
    except Exception:
        logger.error("database_initialization_failed")
        raise


async def close_db() -> None:
    """关闭数据库连接"""
    await engine.dispose()
    logger.info("Database connection closed")
