"""School work records.

Revision ID: 029_school_business
Revises: 028_account_security
"""

import sqlalchemy as sa
from alembic import op

revision = "029_school_business"
down_revision = "028_account_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_business_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.String(20), nullable=False, index=True),
        sa.Column("org_unit_id", sa.String(36), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("submitted_by", sa.String(36)),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("review_comment", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("school_business_records")
