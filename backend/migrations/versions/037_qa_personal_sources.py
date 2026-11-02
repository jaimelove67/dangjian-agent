"""问答记录保存本人资料来源元数据。

Revision ID: 037_qa_personal_sources
Revises: 036_member_procedures
Create Date: 2026-11-02

本人资料只作为当前登录账号提问时的背景材料，不进入知识库、不作为制度依据。
问答历史保留参考了哪些资料的名称和编号，便于本人回看；不保存个人材料正文。
"""

import sqlalchemy as sa
from alembic import op

revision = "037_qa_personal_sources"
down_revision = "036_member_procedures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qa_sessions",
        sa.Column("personal_sources", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("qa_sessions", "personal_sources")
