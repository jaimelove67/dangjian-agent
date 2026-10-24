"""Align governance timestamp defaults with the ORM for databases already at 010.

Revision ID: 011_governance_timestamps
Revises: 010_security_governance
"""

import sqlalchemy as sa
from alembic import op

revision = "011_governance_timestamps"
down_revision = "010_security_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("config_revisions", "human_reviews", "durable_jobs", "model_usage"):
        for column in ("created_at", "updated_at"):
            op.alter_column(table, column, server_default=sa.func.now())


def downgrade() -> None:
    for table in ("config_revisions", "human_reviews", "durable_jobs", "model_usage"):
        for column in ("created_at", "updated_at"):
            op.alter_column(table, column, server_default=None)
