"""政审结论与集中培训的登记依据。

Revision ID: 035_member_gate_reasons
Revises: 034_member_development_gates
Create Date: 2026-10-29

两条台账都要求登记人填写依据，但 034 只落了业务字段，没有保存依据正文。
本迁移补上 ``reason``：政审依据随结论按敏感级管理，培训依据按内部级保存。
历史行不补造依据，保留空字符串，由组织人员核对原件后新增记录或补充说明。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "035_member_gate_reasons"
down_revision = "034_member_development_gates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member_political_reviews",
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "member_trainings",
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("member_trainings", "reason")
    op.drop_column("member_political_reviews", "reason")
