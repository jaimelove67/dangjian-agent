"""League recommendation eligibility fields.

Revision ID: 032_member_league_eligibility
Revises: 031_backup_jobs
"""

import sqlalchemy as sa
from alembic import op

revision = "032_member_league_eligibility"
down_revision = "031_backup_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("member_profiles", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("member_profiles", sa.Column("league_joined_on", sa.Date(), nullable=True))
    op.add_column(
        "member_league_recommendations",
        sa.Column("eligibility_note", sa.String(200), nullable=False, server_default=""),
    )
    op.alter_column(
        "member_league_recommendations",
        "eligibility_note",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("member_league_recommendations", "eligibility_note")
    op.drop_column("member_profiles", "league_joined_on")
    op.drop_column("member_profiles", "birth_date")
