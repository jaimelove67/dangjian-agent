"""数据库迁移脚本：问答记录附件元数据

Revision ID: 023_qa_session_attachments
Revises: 022_member_vote_dedup_batch
Create Date: 2026-10-21

问答记录新增 ``attachments``：记下"这次提问同时看了哪些材料"。

**只存元数据（编号 / 文件名 / 字数 / 是否截断），不存正文**：附件是提问人在本次
会话里提供的临时背景材料，正文仅在 Redis 中暂存两小时供生成使用；长期留存正文
既无必要，也会把同一份材料在问答表里复制很多份、扩大泄露面。历史记录该列为空，
接口返回空数组，界面不显示附件行。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "023_qa_session_attachments"
down_revision = "022_member_vote_dedup_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column("qa_sessions", sa.Column("attachments", sa.JSON(), nullable=True))


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("qa_sessions", "attachments")
