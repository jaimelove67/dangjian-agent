"""Security governance, durable jobs and database append-only audit.

Revision ID: 010
Revises: 009
"""

import sqlalchemy as sa
from alembic import op

revision = "010_security_governance"
down_revision = "009_member_workflow"
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade():
    op.add_column("tenants", sa.Column("is_active", sa.Boolean(), nullable=False,
                                    server_default=sa.true()))
    op.add_column("tenants", sa.Column("config_version", sa.Integer(), nullable=False,
                                    server_default="0"))
    op.add_column("org_units", sa.Column("is_active", sa.Boolean(), nullable=False,
                                      server_default=sa.true()))
    op.alter_column("audit_logs", "resource_id", type_=sa.String(200))
    op.create_table(
        "config_revisions", *common_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.UniqueConstraint("tenant_id", "version"),
    )
    op.create_table(
        "human_reviews", *common_columns(),
        sa.Column("source_kind", sa.String(40), nullable=False, index=True),
        sa.Column("source_id", sa.String(200), nullable=False, index=True),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("submitted_by", sa.String(36), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("opinion", sa.String(2000)),
    )
    op.create_index("uq_human_review_pending", "human_reviews",
                    ["tenant_id", "source_kind", "source_id", "source_version"],
                    unique=True, postgresql_where=sa.text("status='pending' AND is_deleted=false"))
    op.create_table(
        "durable_jobs", *common_columns(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("lease_until", sa.DateTime(), index=True),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("tenant_id", "dedup_key"),
    )
    op.create_table(
        "model_usage", *common_columns(),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_type", sa.String(20), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("retrieval_score", sa.Float()),
        sa.Column("error_code", sa.String(100)),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'audit_logs is append only'; END; $$;
        """)
        op.execute("""
            CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
        """)
        op.execute("""
            CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_logs
            FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
        """)
        op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM PUBLIC")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_no_truncate ON audit_logs")
        op.execute("DROP TRIGGER audit_no_update_delete ON audit_logs")
        op.execute("DROP FUNCTION reject_audit_mutation()")
    for table in ("model_usage", "durable_jobs", "human_reviews", "config_revisions"):
        op.drop_table(table)
    op.alter_column("audit_logs", "resource_id", type_=sa.String(36))
    op.drop_column("org_units", "is_active")
    op.drop_column("tenants", "config_version")
    op.drop_column("tenants", "is_active")
