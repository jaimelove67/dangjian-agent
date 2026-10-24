"""Education offerings and idempotent per-person progress.

Revision ID: 030_education
Revises: 029_school_business
"""

import sqlalchemy as sa
from alembic import op

revision = "030_education"
down_revision = "029_school_business"
branch_labels = None
depends_on = None


def upgrade() -> None:
    def common():
        return [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        ]

    op.create_table(
        "education_offerings",
        *common(),
        sa.Column("kind", sa.String(20), nullable=False, index=True),
        sa.Column("org_unit_id", sa.String(36), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
    )
    op.create_table(
        "education_enrollments",
        *common(),
        sa.Column("offering_id", sa.String(36), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "offering_id", "user_id", name="uq_education_enrollment"),
    )


def downgrade() -> None:
    op.drop_table("education_enrollments")
    op.drop_table("education_offerings")
