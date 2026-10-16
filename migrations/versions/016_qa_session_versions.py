"""数据库迁移脚本：问答记录版本留痕（SEC-11 / T-SEC-11）

Revision ID: 016_qa_session_versions
Revises: 015_knowledge_review_schedule
Create Date: 2026-10-16

问答记录新增 ``versions``：记下"这条答案由哪个提示词版本、哪个工作流契约版本产出"。
知识库版本不落在这里——它跟着每一条引用走（``citations[].content_revision``），
因为一条答案可能同时引了多篇文档的不同修订，写成一个字段就说不清了。

**为什么不回填**：问的是留痕，而历史记录产生时根本没有记录过版本。按当前配置回填
等于伪造留痕，比留空更糟——将来复核会以为"当时就是这一版"。存量记录保持为空，
接口与界面显示"未留痕"，导出说明里也写明这批记录早于功能上线。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "016_qa_session_versions"
down_revision = "015_knowledge_review_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column("qa_sessions", sa.Column("versions", sa.JSON(), nullable=True))


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("qa_sessions", "versions")
