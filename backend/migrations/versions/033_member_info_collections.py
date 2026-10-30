"""Member basic-information collection current version.

Revision ID: 033_member_info_collections
Revises: 032_member_league_eligibility
"""

import sqlalchemy as sa
from alembic import op

revision = "033_member_info_collections"
down_revision = "032_member_league_eligibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_info_collections",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("member_profiles.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("member_stage", sa.String(32), nullable=False, server_default=""),
        sa.Column("member_stage_label", sa.String(50), nullable=False, server_default=""),
        sa.Column("org_unit_id", sa.String(36), nullable=True),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("department", sa.String(200), nullable=False, server_default=""),
        sa.Column("id_card_masked", sa.String(32), nullable=False, server_default=""),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("stage_joined_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("collector_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("member_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("branch_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("branch_reviewed_by_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("branch_opinion", sa.Text(), nullable=False, server_default=""),
        sa.Column("department_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "department_reviewed_by_name",
            sa.String(50),
            nullable=False,
            server_default="",
        ),
        sa.Column("department_opinion", sa.Text(), nullable=False, server_default=""),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("returned_by_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("return_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("return_stage", sa.String(32), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "tenant_id", "profile_id", name="uq_member_info_collections_profile"
        ),
    )
    op.create_index(
        "ix_member_info_collections_tenant_id",
        "member_info_collections",
        ["tenant_id"],
    )
    op.create_index(
        "ix_member_info_collections_scope",
        "member_info_collections",
        ["tenant_id", "org_unit_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_member_info_collections_scope", table_name="member_info_collections"
    )
    op.drop_index(
        "ix_member_info_collections_tenant_id", table_name="member_info_collections"
    )
    op.drop_table("member_info_collections")
