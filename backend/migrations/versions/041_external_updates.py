"""Create external party-building update review ledger.

Revision ID: 041_external_updates
Revises: 040_member_info_status
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "041_external_updates"
down_revision = "040_member_info_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("knowledge_doc_id", sa.String(100), nullable=True),
        sa.UniqueConstraint("tenant_id", "content_hash", name="uq_external_updates_tenant_hash"),
    )
    op.create_index(
        "ix_external_updates_scope",
        "external_updates",
        ["tenant_id", "status", "fetched_at"],
    )
    op.create_index(
        "ix_external_updates_status",
        "external_updates",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_updates_status", table_name="external_updates")
    op.drop_index("ix_external_updates_scope", table_name="external_updates")
    op.drop_table("external_updates")
