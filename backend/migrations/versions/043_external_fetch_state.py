"""Track the latest external material fetch per school.

Revision ID: 043_external_fetch_state
Revises: 042_meeting_topic_feedback
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "043_external_fetch_state"
down_revision = "042_meeting_topic_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_fetch_state",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_filtered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("tenant_id", name="uq_external_fetch_state_tenant"),
    )


def downgrade() -> None:
    op.drop_table("external_fetch_state")
