"""Alembic 配置文件"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 导入 Base 和所有模型
from app.db.base import Base
from app.models.user import User
from app.models.tenant import Tenant
from app.models.org import OrgUnit
from app.models.knowledge import KnowledgeDoc, EmbeddingChunk
from app.models.audit import AuditLog
from app.models.qa_session import QASession
from app.models.member import MemberProfile

# Alembic Config 对象
config = context.config


def _resolve_database_url() -> str:
    """解析数据库连接 URL

    alembic.ini 注释声明「URL 从环境变量加载」，此处兑现：
    优先 ``ALEMBIC_DATABASE_URL``，其次 ``DATABASE_URL``，最后应用默认配置。
    alembic 为同步执行，asyncpg 驱动不可用，统一替换为 psycopg2。
    """
    url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not url:
        from app.core.config import settings

        url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url


# 设置 SQLAlchemy URL（必须在 configure 之前）
config.set_main_option("sqlalchemy.url", _resolve_database_url())

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 MetaData
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式运行迁移"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
