"""Alembic 配置文件"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入 Base 和所有模型
from app.db.base import Base
from app.models.assessment import (  # noqa: F401
    AssessmentArchive,
    AssessmentEvidence,
    AssessmentIndicator,
    AssessmentPlan,
    AssessmentPolicy,
    AssessmentReminder,
    AssessmentRun,
    AssessmentTask,
)
from app.models.audit import AuditLog  # noqa: F401 - 注册迁移元数据
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc  # noqa: F401
from app.models.meeting import ContentRevision, MeetingRecord, MeetingTask  # noqa: F401
from app.models.member import (  # noqa: F401
    MemberArchiveCheck,
    MemberBatch,
    MemberCultivation,
    MemberMaterial,
    MemberProfile,
    MemberReminder,
    MemberStageHistory,
    MemberVote,
)
from app.models.org import OrgUnit  # noqa: F401
from app.models.qa_session import QASession  # noqa: F401
from app.models.study import StudyPlan, StudyPlanItem  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User  # noqa: F401

# Alembic Config 对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 MetaData
target_metadata = Base.metadata


def _database_url() -> str:
    from app.core.config import settings

    return os.getenv("ALEMBIC_DATABASE_URL") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    """离线模式运行迁移"""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    # 保留远端专用迁移 URL 覆盖和本地异步驱动/测试事务连接。
    url = make_url(_database_url())
    if url.drivername in {"postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+asyncpg")
    section["sqlalchemy.url"] = url
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_migrate)
    await connectable.dispose()


def run_migrations_online() -> None:
    """支持正常 CLI 迁移和测试传入的事务连接。"""
    connection = config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
    else:
        asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
