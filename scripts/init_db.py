"""初始化数据库脚本

创建初始迁移并应用到数据库
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

# 添加项目根目录到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from app.db.base import Base
from app.db.session import engine

# 导入所有模型以确保它们被注册
from app.models.user import User
from app.models.tenant import Tenant
from app.models.org import OrgUnit
from app.models.knowledge import KnowledgeDoc, EmbeddingChunk
from app.models.audit import AuditLog

# 建表前需要的扩展与文本检索配置（与 scripts/init_db.sql 保持一致）
_SETUP_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese_zh') THEN
            CREATE TEXT SEARCH CONFIGURATION chinese_zh (COPY = simple);
        END IF;
    END
    $$;
    """,
]


async def create_tables():
    """创建所有表"""
    async with engine.begin() as conn:
        # 准备扩展与检索配置
        for statement in _SETUP_STATEMENTS:
            await conn.execute(text(statement))

        # 删除所有表（开发环境）
        await conn.run_sync(Base.metadata.drop_all)

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

    print("✅ 数据库表创建成功")


if __name__ == "__main__":
    asyncio.run(create_tables())
