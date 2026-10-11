"""本人档案账号关联及私有个人材料。

Revision ID: 008_member_self
Revises: 007_assessment
"""

import sqlalchemy as sa
from alembic import op

revision = "008_member_self"
down_revision = "007_assessment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """保留既有档案，不自动按姓名关联账号。"""
    op.add_column("member_profiles", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_member_profiles_user", "member_profiles", "users", ["user_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_member_profiles_tenant_user", "member_profiles", ["tenant_id", "user_id"]
    )
    op.create_table(
        "member_materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("member_profiles.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "submission_key", name="uq_member_material_submission"
        ),
    )
    op.create_index(
        "ix_member_materials_owner", "member_materials", ["tenant_id", "user_id", "created_at"]
    )
    op.create_index("ix_member_materials_tenant_id", "member_materials", ["tenant_id"])


def downgrade() -> None:
    """撤销个人材料表和账号关联字段。"""
    op.drop_table("member_materials")
    op.drop_constraint("uq_member_profiles_tenant_user", "member_profiles", type_="unique")
    op.drop_constraint("fk_member_profiles_user", "member_profiles", type_="foreignkey")
    op.drop_column("member_profiles", "user_id")
