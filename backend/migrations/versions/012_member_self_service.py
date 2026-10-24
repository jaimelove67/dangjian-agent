"""为现有党员模型补充账号关联和私有个人材料字段。

本迁移接在 master 的 ``011_governance_timestamps`` 之后。组织端的
``009_member_workflow`` 已经创建 ``member_materials``，因此这里只扩展同一张表，
不重复建表，也不改写既有组织材料记录。
"""

import sqlalchemy as sa
from alembic import op


revision = "012_member_self"
down_revision = "011_governance_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """关联账号并为党员自助提交预留私有原件字段。"""
    op.add_column("member_profiles", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_member_profiles_user", "member_profiles", "users", ["user_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_member_profiles_tenant_user", "member_profiles", ["tenant_id", "user_id"]
    )

    op.add_column("member_materials", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_member_materials_user", "member_materials", "users", ["user_id"], ["id"]
    )
    op.add_column(
        "member_materials",
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column(
        "member_materials",
        sa.Column("category", sa.String(30), nullable=False, server_default="other"),
    )
    op.add_column(
        "member_materials",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "member_materials",
        sa.Column("file_name", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "member_materials",
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("member_materials", sa.Column("submission_key", sa.String(36), nullable=True))
    op.add_column(
        "member_materials", sa.Column("content_sha256", sa.String(64), nullable=True)
    )
    # 组织端历史记录没有原始文件；只有新的党员自助记录会写入内容。
    op.add_column("member_materials", sa.Column("content", sa.LargeBinary(), nullable=True))
    op.create_index(
        "ix_member_materials_owner",
        "member_materials",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_unique_constraint(
        "uq_member_material_submission",
        "member_materials",
        ["tenant_id", "user_id", "submission_key"],
    )


def downgrade() -> None:
    """撤销党员自助字段，保留 master 原有组织材料列。"""
    op.drop_constraint("uq_member_material_submission", "member_materials", type_="unique")
    op.drop_index("ix_member_materials_owner", table_name="member_materials")
    op.drop_column("member_materials", "content")
    op.drop_column("member_materials", "content_sha256")
    op.drop_column("member_materials", "submission_key")
    op.drop_column("member_materials", "file_size")
    op.drop_column("member_materials", "file_name")
    op.drop_column("member_materials", "description")
    op.drop_column("member_materials", "category")
    op.drop_column("member_materials", "title")
    op.drop_constraint("fk_member_materials_user", "member_materials", type_="foreignkey")
    op.drop_column("member_materials", "user_id")
    op.drop_constraint("uq_member_profiles_tenant_user", "member_profiles", type_="unique")
    op.drop_constraint("fk_member_profiles_user", "member_profiles", type_="foreignkey")
    op.drop_column("member_profiles", "user_id")
