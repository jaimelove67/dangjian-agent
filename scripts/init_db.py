"""初始化数据库脚本

创建初始迁移并应用到数据库
"""
import asyncio
import sys
from pathlib import Path

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


async def create_tables():
    """创建所有表"""
    async with engine.begin() as conn:
        # 删除所有表（开发环境）
        await conn.run_sync(Base.metadata.drop_all)

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

    print("✅ 数据库表创建成功")


if __name__ == "__main__":
    asyncio.run(create_tables())
