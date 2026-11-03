"""团组织推优登记应到会有表决权人数与同意票数。

Revision ID: 038_member_league_vote_counts
Revises: 037_qa_personal_sources
Create Date: 2026-11-02

依据《发展党员工作实务解读（2025.4）》：党员推荐、群团组织推优的得票须超过
应到会有表决权人数的半数。历史记录没有票数时保留为 0，不追溯改写。
"""

import sqlalchemy as sa
from alembic import op

revision = "038_member_league_vote_counts"
down_revision = "037_qa_personal_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member_league_recommendations",
        sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "member_league_recommendations",
        sa.Column("agree_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("member_league_recommendations", "agree_count")
    op.drop_column("member_league_recommendations", "eligible_count")
