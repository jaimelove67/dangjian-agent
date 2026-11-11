"""Record personal material review, reviewer time and resubmission link.

Revision ID: 047_member_material_review
Revises: 046_member_material_receipts
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "047_member_material_review"
down_revision = "046_member_material_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member_materials", sa.Column("reviewed_by", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "member_materials", sa.Column("reviewed_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "member_materials",
        sa.Column("previous_material_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_member_materials_previous",
        "member_materials",
        ["tenant_id", "previous_material_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_member_materials_previous", table_name="member_materials")
    op.drop_column("member_materials", "previous_material_id")
    op.drop_column("member_materials", "reviewed_at")
    op.drop_column("member_materials", "reviewed_by")
