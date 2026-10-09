"""数据库集成测试（需要可用的 PostgreSQL）

无法连接数据库时自动跳过。设置 DATABASE_URL 并可用后运行：

    pytest -m integration

前置：先执行 ``alembic upgrade head`` 应用迁移。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

pytestmark = pytest.mark.integration

CORE_TABLES = {
    "tenants",
    "org_units",
    "users",
    "knowledge_docs",
    "audit_logs",
    "embedding_chunks",
}


def _make_engine():
    """创建短连接引擎（集成测试用）"""
    return create_async_engine(settings.DATABASE_URL, poolclass=NullPool)


async def _db_reachable() -> bool:
    engine = _make_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def conn():
    """数据库连接；不可用时跳过测试"""
    if not await _db_reachable():
        pytest.skip("PostgreSQL 不可用，跳过集成测试（请配置 DATABASE_URL）")

    engine = _make_engine()
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def test_core_tables_exist(conn):
    """核心表已由迁移创建"""
    result = await conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    tables = {row[0] for row in result}
    missing = CORE_TABLES - tables
    assert not missing, f"缺少核心表 {missing}，请先执行 alembic upgrade head"


async def test_chinese_ts_config_exists(conn):
    """中文全文检索配置存在"""
    result = await conn.execute(
        text("SELECT cfgname FROM pg_ts_config WHERE cfgname = 'chinese_zh'")
    )
    assert result.scalar() == "chinese_zh", "缺少 chinese_zh 文本检索配置"


async def test_search_vector_is_generated_column(conn):
    """search_vector 为生成列"""
    result = await conn.execute(
        text(
            "SELECT is_generated FROM information_schema.columns "
            "WHERE table_name = 'knowledge_docs' AND column_name = 'search_vector'"
        )
    )
    assert result.scalar() == "ALWAYS", "search_vector 应为生成列"


async def test_fts_indexes_exist(conn):
    """全文检索与 pg_trgm 索引存在"""
    result = await conn.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'knowledge_docs'")
    )
    indexes = {row[0] for row in result}
    assert "ix_knowledge_docs_search_vector" in indexes
    assert "ix_knowledge_docs_title_trgm" in indexes


async def test_chinese_fts_query_runs(conn):
    """chinese_zh 配置可正常用于检索"""
    result = await conn.execute(
        text("SELECT to_tsvector('chinese_zh', '中国共产党章程')")
    )
    vector = result.scalar()
    assert vector is not None
