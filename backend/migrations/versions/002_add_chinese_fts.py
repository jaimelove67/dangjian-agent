"""数据库迁移脚本：中文全文检索配置

Revision ID: 002
Revises: 001
Create Date: 2026-10-09

本迁移为知识文档补齐中文全文检索能力：

1. 启用 pg_trgm 扩展，作为中文子串/模糊检索的兜底（PostgreSQL contrib 自带，无需额外编译）。
2. 创建文本检索配置 ``chinese_zh``，默认复制 ``simple``。
   生产环境安装 zhparser 后可将映射切换为中文分词器：

       ALTER TEXT SEARCH CONFIGURATION chinese_zh
         ALTER MAPPING FOR n,v,a,i,e,l WITH zhparser;

3. 为 knowledge_docs 增加生成列 ``search_vector``（随 title/summary 自动更新）。
4. 建立 GIN 索引：``search_vector`` 全文检索 + ``title`` 三元组模糊检索。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （与 001 保持一致的导入风格）

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# 中文全文检索配置名（需与 app/models/knowledge.py 的生成列表达式保持一致）
CHINESE_TS_CONFIG = "chinese_zh"

# 生成列表达式：标题 + 摘要
_SEARCH_EXPR = (
    "to_tsvector('{cfg}', coalesce(title, '') || ' ' || coalesce(summary, ''))"
).format(cfg=CHINESE_TS_CONFIG)


def upgrade() -> None:
    """升级数据库"""
    # 1. 三元组模糊检索扩展（中文子串匹配兜底）
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. 创建中文全文检索配置（默认基于 simple；zhparser 就绪后可切换映射）
    op.execute(
        "DO $$\n"
        "BEGIN\n"
        "    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = '%(cfg)s') THEN\n"
        "        CREATE TEXT SEARCH CONFIGURATION %(cfg)s (COPY = simple);\n"
        "    END IF;\n"
        "END\n"
        "$$;" % {"cfg": CHINESE_TS_CONFIG}
    )

    # 3. 生成列：随 title / summary 自动更新，无需触发器
    op.execute(
        "ALTER TABLE knowledge_docs "
        "ADD COLUMN IF NOT EXISTS search_vector tsvector "
        f"GENERATED ALWAYS AS ({_SEARCH_EXPR}) STORED"
    )

    # 4. GIN 索引：全文检索
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_docs_search_vector "
        "ON knowledge_docs USING GIN (search_vector)"
    )

    # 5. GIN 索引：中文子串/模糊检索兜底
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_docs_title_trgm "
        "ON knowledge_docs USING GIN (title gin_trgm_ops)"
    )


def downgrade() -> None:
    """回滚数据库"""
    op.execute("DROP INDEX IF EXISTS ix_knowledge_docs_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_docs_search_vector")
    op.execute("ALTER TABLE knowledge_docs DROP COLUMN IF EXISTS search_vector")
    op.execute(f"DROP TEXT SEARCH CONFIGURATION IF EXISTS {CHINESE_TS_CONFIG}")
    # pg_trgm 可能被其它对象依赖，回滚时不删除
