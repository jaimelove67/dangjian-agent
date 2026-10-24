"""数据库迁移脚本：党员档案增加身份证号

Revision ID: 024_member_id_card
Revises: 023_qa_session_attachments
Create Date: 2026-10-22

学校实际用身份证号作为登录账号，名册需要保存该号码才能在开户时自动带出。

**存明文**：登录名必须可读可核对（哈希后无法回显，管理员无法确认是哪个人）；
对外展示一律经 ``mask_id_card`` 脱敏为「前 6 位 + **** + 后 4 位」，审计同口径。
该列仅作账号标识，不作为实名核验依据——核验仍需线下查验证件。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "024_member_id_card"
down_revision = "023_qa_session_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column("member_profiles", sa.Column("id_card_no", sa.String(length=32), nullable=True))
    op.create_index(
        "ix_member_profiles_tenant_id_card",
        "member_profiles",
        ["tenant_id", "id_card_no"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_profiles_tenant_id_card", table_name="member_profiles")
    op.drop_column("member_profiles", "id_card_no")
