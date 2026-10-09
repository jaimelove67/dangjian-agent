"""迁移脚本离线渲染测试（不依赖真实数据库）

使用 Alembic offline 模式生成 SQL，验证迁移链可加载、且 002 迁移包含
中文全文检索相关 DDL。
"""
import io

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture(scope="module")
def offline_sql() -> str:
    """生成 001 -> head 的离线 SQL

    以编程方式构造 Config（不读取 alembic.ini），避免 Windows 中文
    locale（GBK）解析 UTF-8 注释时出错。
    """
    config = Config()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option(
        "sqlalchemy.url", "postgresql://user:pass@localhost:5432/party_agent_test"
    )
    buffer = io.StringIO()
    config.output_buffer = buffer
    command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def test_migration_chain_renders_core_tables(offline_sql):
    for table in ("tenants", "org_units", "users", "knowledge_docs", "audit_logs",
                  "embedding_chunks"):
        assert f"CREATE TABLE {table}" in offline_sql


def test_chinese_fts_ddl_rendered(offline_sql):
    assert "pg_trgm" in offline_sql
    assert "chinese_zh" in offline_sql
    assert "ADD COLUMN IF NOT EXISTS search_vector tsvector" in offline_sql
    assert "ix_knowledge_docs_search_vector" in offline_sql
    assert "ix_knowledge_docs_title_trgm" in offline_sql
