"""Create meeting topic recommendation feedback.

Revision ID: 042_meeting_topic_feedback
Revises: 041_external_updates
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "042_meeting_topic_feedback"
down_revision = "041_external_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_topic_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("activity_type", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "tenant_id",
            "org_unit_id",
            "topic",
            name="uq_meeting_topic_feedback_scope",
        ),
    )
    op.create_index(
        "ix_meeting_topic_feedback_lookup",
        "meeting_topic_feedback",
        ["tenant_id", "org_unit_id", "decision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meeting_topic_feedback_lookup",
        table_name="meeting_topic_feedback",
    )
    op.drop_table("meeting_topic_feedback")
