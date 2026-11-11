"""Store the role and permission scope snapshot for each QA answer.

Revision ID: 045_qa_access_context
Revises: 044_meeting_document_templates
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "045_qa_access_context"
down_revision = "044_meeting_document_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 只保存角色与范围标签，不保存个人资料正文；历史记录为空时按“未记录”展示。
    op.add_column("qa_sessions", sa.Column("access_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("qa_sessions", "access_context")
