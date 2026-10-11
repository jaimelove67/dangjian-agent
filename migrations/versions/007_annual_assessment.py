"""年度考核、规则版本、人工审核和站内提醒。

Revision ID: 007_assessment
Revises: 006
"""

import sqlalchemy as sa
from alembic import op

revision = "007_assessment"
down_revision = "006"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _str(name, size=36, nullable=False, default=None):
    return sa.Column(name, sa.String(size), nullable=nullable, server_default=default)


def _review():
    return [
        _str("review_status", 20, default="pending"),
        _str("created_by"),
        _str("reviewed_by", nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_opinion", sa.Text(), nullable=False, server_default=""),
    ]


def upgrade() -> None:
    """只新增考核表，不改动既有人员、问答或知识数据。"""
    op.create_table(
        "assessment_indicators",
        *_base(),
        _str("school_org_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("code", 64),
        sa.Column("version", sa.Integer(), nullable=False),
        _str("name", 200),
        sa.Column("requirement", sa.Text(), nullable=False),
        _str("formula", 20),
        _str("source", 30),
        sa.Column("source_options", sa.JSON(), nullable=False),
        _str("target", 50),
        _str("comparison", 10, default="gte"),
        _str("unit", 20, default="项"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("required_evidence", sa.JSON(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmation_note", sa.Text(), nullable=False, server_default=""),
        _str("created_by"),
        sa.UniqueConstraint("tenant_id", "school_org_id", "year", "code", "version"),
    )
    op.create_table(
        "assessment_tasks",
        *_base(),
        _str("school_org_id"),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("indicator_code", 64),
        _str("title", 200),
        _str("owner_id"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("declared_progress", sa.Integer(), nullable=False, server_default="0"),
        _str("manual_value", 50, nullable=True),
        sa.Column("completed_on", sa.Date(), nullable=True),
        sa.Column("basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_review(),
    )
    op.create_table(
        "assessment_evidence",
        *_base(),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("indicator_code", 64),
        _str("requirement_key", 100),
        _str("doc_id", 100),
        _str("source_version", 64),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_review(),
        sa.UniqueConstraint(
            "tenant_id", "org_unit_id", "year", "indicator_code", "requirement_key", "doc_id"
        ),
    )
    op.create_table(
        "assessment_runs",
        *_base(),
        _str("school_org_id"),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("fingerprint", 64),
        _str("engine_version", 30),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_review(),
        sa.UniqueConstraint("tenant_id", "org_unit_id", "year", "fingerprint"),
    )
    op.create_table(
        "assessment_plans",
        *_base(),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        _str("run_id"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_review(),
        sa.UniqueConstraint("tenant_id", "org_unit_id", "year", "version"),
    )
    op.create_table(
        "assessment_policies",
        *_base(),
        _str("school_org_id"),
        sa.Column("archive_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reminder_advance_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmation_note", sa.Text(), nullable=False, server_default=""),
        _str("confirmed_by", nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "school_org_id"),
    )
    op.create_table(
        "assessment_reminders",
        *_base(),
        _str("task_id"),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("owner_id"),
        _str("kind", 30),
        _str("dedup_key", 64),
        _str("status", 20, default="open"),
        _str("handled_by", nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("handling_note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("tenant_id", "dedup_key"),
    )
    op.create_table(
        "assessment_archives",
        *_base(),
        _str("org_unit_id"),
        sa.Column("year", sa.Integer(), nullable=False),
        _str("run_id"),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        _str("created_by"),
        sa.UniqueConstraint("tenant_id", "run_id"),
    )
    for table in (
        "indicators",
        "tasks",
        "evidence",
        "runs",
        "plans",
        "policies",
        "reminders",
        "archives",
    ):
        op.create_index(f"ix_assessment_{table}_tenant_id", f"assessment_{table}", ["tenant_id"])
    op.create_index(
        "ix_assessment_indicators_year",
        "assessment_indicators",
        ["tenant_id", "school_org_id", "year"],
    )
    for table in ("tasks", "evidence", "plans"):
        op.create_index(
            f"ix_assessment_{table}_scope",
            f"assessment_{table}",
            ["tenant_id", "org_unit_id", "year"],
        )
    op.create_index(
        "ix_assessment_runs_scope",
        "assessment_runs",
        ["tenant_id", "org_unit_id", "year", "created_at"],
    )
    op.create_index(
        "ix_assessment_reminders_owner", "assessment_reminders", ["tenant_id", "owner_id", "status"]
    )


def downgrade() -> None:
    """显式回退仅删除本迁移创建的表。"""
    for table in (
        "archives",
        "reminders",
        "policies",
        "plans",
        "runs",
        "evidence",
        "tasks",
        "indicators",
    ):
        op.drop_table(f"assessment_{table}")
