"""数据库迁移脚本：培养对象名册表

Revision ID: 004
Revises: 003
Create Date: 2026-10-10

新增 ``member_profiles`` 表，记录培养对象台账（姓名 / 组织 / 当前阶段 /
进入阶段日期 / 已具备材料 / 待办数）。在阶段天数由 ``stage_joined_on``
实时计算，不做冗余存储。种子数据不写入迁移（数据而非结构），由脚本/人工导入。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （与 001-003 保持一致的导入风格）

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=True),
        sa.Column(
            "current_stage",
            sa.String(20),
            nullable=False,
            server_default="applicant",
        ),
        sa.Column("stage_joined_on", sa.Date(), nullable=False),
        sa.Column(
            "materials", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # 常见查询：某租户下按阶段/时间浏览名册
    op.create_index(
        "ix_member_profiles_stage",
        "member_profiles",
        ["tenant_id", "current_stage", "created_at"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_profiles_stage", table_name="member_profiles")
    op.drop_table("member_profiles")