"""Controlled backup and restore job ledger.

Revision ID: 031_backup_jobs
Revises: 030_education
"""

import sqlalchemy as sa
from alembic import op

revision = "031_backup_jobs"
down_revision = "030_education"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36)),
        sa.Column("dedup_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_backup_job_dedup"),
    )


def downgrade() -> None:
    op.drop_table("backup_jobs")
