"""Record which organization account opened a personal material and when.

Revision ID: 046_member_material_receipts
Revises: 045_qa_access_context
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "046_member_material_receipts"
down_revision = "045_qa_access_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_material_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.String(length=36), nullable=False),
        sa.Column("viewer_id", sa.String(length=36), nullable=False),
        sa.Column("viewed_at", sa.DateTime(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "material_id",
            "viewer_id",
            name="uq_member_material_receipt",
        ),
    )
    op.create_index(
        "ix_member_material_receipts_material",
        "member_material_receipts",
        ["tenant_id", "material_id", "viewed_at"],
        unique=False,
    )
    op.create_index(
        "ix_member_material_receipts_material_id",
        "member_material_receipts",
        ["material_id"],
        unique=False,
    )
    op.create_index(
        "ix_member_material_receipts_viewer_id",
        "member_material_receipts",
        ["viewer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_member_material_receipts_viewer_id", table_name="member_material_receipts"
    )
    op.drop_index(
        "ix_member_material_receipts_material_id", table_name="member_material_receipts"
    )
    op.drop_index(
        "ix_member_material_receipts_material", table_name="member_material_receipts"
    )
    op.drop_table("member_material_receipts")
