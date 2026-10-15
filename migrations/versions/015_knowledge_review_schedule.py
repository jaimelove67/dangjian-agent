"""数据库迁移脚本：知识条目供给复核日程

Revision ID: 015_knowledge_review_schedule
Revises: 014_knowledge_authority_validity
Create Date: 2026-10-15

支撑 T-KB-13 的「内容供给与版本维护机制」：

- ``maintained_at``    最近一次复核确认或内容更新的时间；
- ``next_review_at``   按学校「供给机制」的更新周期排定的下次复核日期。

责任部门、责任人与更新周期不落在条目上，而是按权威来源由学校配置的
``knowledge_supply``（租户配置，见 app/services/governance_service.py）统一给出，
条目只记录"什么时候复核过、下次什么时候复核"，避免同一类制度出现多套并行口径。

回填口径：存量条目**不**回填日程（``next_review_at`` 保持为空）。迁移之前无法判定
各条目由谁供给、按什么周期复核，凭空生成日期只会制造一批假到期项；这些条目在首次
复核确认或下次内容更新时自然排定日程。回填后的索引足以支撑"待复核"筛选。
"""

import sqlalchemy as sa  # noqa: F401  （与既有迁移保持一致的导入风格）
from alembic import op

# revision identifiers, used by Alembic.
revision = "015_knowledge_review_schedule"
down_revision = "014_knowledge_authority_validity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column("knowledge_docs", sa.Column("maintained_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_docs", sa.Column("next_review_at", sa.Date(), nullable=True))
    op.create_index("ix_knowledge_docs_next_review_at", "knowledge_docs", ["next_review_at"])


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_knowledge_docs_next_review_at", table_name="knowledge_docs")
    op.drop_column("knowledge_docs", "next_review_at")
    op.drop_column("knowledge_docs", "maintained_at")
