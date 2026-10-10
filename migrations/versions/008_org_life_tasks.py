"""组织生活（三会一课）任务台账；责任人与处理记录只追加，不改动既有业务表。

Revision ID: 008_org_life_tasks
Revises: 007_assessment
"""

import sqlalchemy as sa
from alembic import op

revision = "008_org_life_tasks"
down_revision = "007_assessment"
branch_labels = None
depends_on = None


def _base() -> list:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    op.create_table(
        "meeting_tasks",
        *_base(),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("task_text", sa.Text(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("owner_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("due_on", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("confirmed_by", sa.String(36)),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("handled_at", sa.DateTime()),
        sa.Column("handle_note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_meeting_tasks_scope_status", "meeting_tasks", ["tenant_id", "org_unit_id", "status"])
    op.create_index("ix_meeting_tasks_record", "meeting_tasks", ["tenant_id", "record_id"])


def downgrade() -> None:
    op.drop_table("meeting_tasks")
