"""Persist sessions and atomic, lifetime password allowances.

Revision ID: 028_account_security
Revises: 027_org_leader_terms
"""

import sqlalchemy as sa
from alembic import op

revision = "028_account_security"
down_revision = "027_org_leader_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    def common():
        return [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("user_id", sa.String(36), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        ]

    op.create_table(
        "login_sessions",
        *common(),
        sa.Column("identity_stamp", sa.String(64), nullable=False),
        sa.Column("client_label", sa.String(300), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
    )
    op.create_table(
        "password_requests",
        *common(),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("review_comment", sa.String(300)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("consumed_at", sa.DateTime()),
    )
    op.create_table(
        "password_changes",
        *common(),
        sa.Column("request_id", sa.String(36), unique=True),
    )


def downgrade() -> None:
    op.drop_table("password_changes")
    op.drop_table("password_requests")
    op.drop_table("login_sessions")
