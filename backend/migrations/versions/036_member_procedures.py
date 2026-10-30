"""发展程序事实台账：培养联系人、入党介绍人、支委会审查、上级预审、志愿书与谈话。

Revision ID: 036_member_procedures
Revises: 035_member_gate_reasons
Create Date: 2026-10-29

本表只登记组织已经完成的程序事实，不替代组织决定，也不自动推进阶段：
- 培养联系人 / 入党介绍人可关联本校正式党员档案，外部正式党员须人工核验并留依据；
- 支委会审查、上级党委预审、入党志愿书、上级党委派人谈话分别保留日期、结论、依据与版本；
- 记录按 ``kind`` 分类、只增不改，最新一条作为当前状态；历史记录用于回溯。

历史数据不补造：既有人员的发展程序记录保持为空，由组织人员按会议记录、批复和志愿书
原件核对后登记。缺少记录时阶段流转会提示补录，不默认通过。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "036_member_procedures"
down_revision = "035_member_gate_reasons"
branch_labels = None
depends_on = None


def _base() -> list:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_procedures",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=""),
        sa.Column("title", sa.String(100), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("data_level", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(36), nullable=False),
    )
    op.create_index(
        "ix_member_procedures_profile",
        "member_procedures",
        ["tenant_id", "profile_id", "kind", "occurred_on"],
    )
    op.create_index(
        "ix_member_procedures_scope",
        "member_procedures",
        ["tenant_id", "org_unit_id", "kind", "status"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_procedures_scope", table_name="member_procedures")
    op.drop_index("ix_member_procedures_profile", table_name="member_procedures")
    op.drop_table("member_procedures")
