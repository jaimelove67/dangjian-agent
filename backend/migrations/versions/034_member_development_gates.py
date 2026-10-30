"""发展党员前置事实：材料落款日期、政治审查结论、集中培训。

Revision ID: 034_member_development_gates
Revises: 033_member_info_collections
Create Date: 2026-10-29

三件事分开存：
- ``member_materials.document_date`` 是材料落款日期，与组织收到日期 ``submit_date`` 区分；
  入党申请书的 18 周岁和"申请满 6 个月"都以落款日期为锚点。
- ``member_political_reviews`` 只登记组织形成的政审结论，原始政审材料仍按涉密级管理。
- ``member_trainings`` 只登记集中培训事实，是否计入发展程序仍须人工核验原件。

历史数据不补造：既有材料 ``document_date`` 保持 NULL，由组织人员按原件补录；
补录前入党申请书不能通过核验，也不能用于"满 6 个月"的核算。

两张新台账的登记依据 ``reason`` 由后续 ``035_member_gate_reasons`` 迁移补充。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "034_member_development_gates"
down_revision = "033_member_info_collections"
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
    op.add_column("member_materials", sa.Column("document_date", sa.Date(), nullable=True))

    op.create_table(
        "member_political_reviews",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("reviewed_by", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(200), nullable=False, server_default=""),
        sa.Column("conclusion", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("material_id", sa.String(36), nullable=True),
        sa.Column("data_level", sa.String(20), nullable=False, server_default="sensitive"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_member_political_reviews_profile",
        "member_political_reviews",
        ["tenant_id", "profile_id", "reviewed_on"],
    )
    op.create_index(
        "ix_member_political_reviews_scope",
        "member_political_reviews",
        ["tenant_id", "org_unit_id", "status"],
    )

    op.create_table(
        "member_trainings",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("training_type", sa.String(40), nullable=False, server_default="centralized"),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("hours", sa.Integer(), nullable=True),
        sa.Column("issuer", sa.String(200), nullable=False, server_default=""),
        sa.Column("certificate_material_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_level", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(36), nullable=False),
    )
    op.create_index(
        "ix_member_trainings_profile",
        "member_trainings",
        ["tenant_id", "profile_id", "end_on"],
    )
    op.create_index(
        "ix_member_trainings_scope",
        "member_trainings",
        ["tenant_id", "org_unit_id", "training_type"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_trainings_scope", table_name="member_trainings")
    op.drop_index("ix_member_trainings_profile", table_name="member_trainings")
    op.drop_table("member_trainings")
    op.drop_index("ix_member_political_reviews_scope", table_name="member_political_reviews")
    op.drop_index("ix_member_political_reviews_profile", table_name="member_political_reviews")
    op.drop_table("member_political_reviews")
    op.drop_column("member_materials", "document_date")
