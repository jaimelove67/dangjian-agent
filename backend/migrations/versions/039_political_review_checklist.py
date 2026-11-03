"""政治审查保存四项内容核对与八类不合格情形。

Revision ID: 039_political_review_checklist
Revises: 038_member_league_vote_counts
Create Date: 2026-11-02

结构化字段只用于登记组织已经核对的事实；是否合格仍由组织人员填写结论。
"""

import sqlalchemy as sa
from alembic import op

revision = "039_political_review_checklist"
down_revision = "038_member_league_vote_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member_political_reviews",
        sa.Column("checklist", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("member_political_reviews", "checklist")
