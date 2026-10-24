"""发展党员全流程：批次、材料记录、阶段历史、提醒台账、培养数据、投票与档案检查。

不改动既有业务数据和列含义；member_profiles 仅新增年度/批次归属列。
Revision ID: 009_member_workflow
Revises: 008_org_life_tasks
"""

import sqlalchemy as sa
from alembic import op

revision = "009_member_workflow"
down_revision = "008_org_life_tasks"
branch_labels = None
depends_on = None


def _base() -> list:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _json(name: str, default: str = "{}") -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text(f"'{default}'::json"))


def upgrade() -> None:
    op.add_column("member_profiles", sa.Column("year", sa.Integer(), nullable=True))
    op.add_column("member_profiles", sa.Column("batch_no", sa.String(20), nullable=True))

    op.create_table(
        "member_batches",
        *_base(),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("batch_no", sa.String(20), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("tenant_id", "year", "batch_no", name="uq_member_batch_year_no"),
    )
    op.create_index("ix_member_batches_scope_year", "member_batches", ["tenant_id", "org_unit_id", "year"])

    op.create_table(
        "member_materials",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("material_type", sa.String(100), nullable=False),
        sa.Column("file_version", sa.String(100), nullable=False, server_default=""),
        sa.Column("submit_date", sa.Date()),
        sa.Column("submitter_id", sa.String(36)),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_member_materials_profile", "member_materials", ["tenant_id", "profile_id", "stage"])

    op.create_table(
        "member_stage_history",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("from_stage", sa.String(20), nullable=False),
        sa.Column("to_stage", sa.String(20), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("opinion", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(36), nullable=False),
    )
    op.create_index(
        "ix_member_stage_history_profile", "member_stage_history", ["tenant_id", "profile_id"]
    )

    op.create_table(
        "member_reminders",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("processed_by", sa.String(36)),
        sa.Column("processed_at", sa.DateTime()),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "tenant_id", "profile_id", "kind", "due_on", name="uq_member_reminder_dedup"
        ),
    )
    op.create_index(
        "ix_member_reminders_due", "member_reminders", ["tenant_id", "org_unit_id", "due_on", "status"]
    )

    op.create_table(
        "member_cultivation",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("score", sa.Numeric(10, 2), nullable=True),
        sa.Column("period", sa.String(40), nullable=False, server_default=""),
        sa.Column("source_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("verified_by", sa.String(36)),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("is_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_note", sa.String(500), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_member_cultivation_profile", "member_cultivation", ["tenant_id", "profile_id", "category"]
    )

    op.create_table(
        "member_votes",
        *_base(),
        sa.Column("batch_no", sa.String(20), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("voter_id", sa.String(36), nullable=False),
        sa.Column("vote", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "tenant_id", "round_no", "voter_id", "profile_id", name="uq_member_vote_dedup"
        ),
    )
    op.create_index(
        "ix_member_votes_batch",
        "member_votes",
        ["tenant_id", "batch_no", "round_no", "profile_id"],
    )

    op.create_table(
        "member_archive_checks",
        *_base(),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("checked_by", sa.String(36), nullable=False),
        sa.Column("rule_version", sa.String(20), nullable=False),
        _json("result"),
    )
    op.create_index(
        "ix_member_archive_checks_profile", "member_archive_checks", ["tenant_id", "profile_id"]
    )


def downgrade() -> None:
    for table in (
        "member_archive_checks",
        "member_votes",
        "member_cultivation",
        "member_reminders",
        "member_stage_history",
        "member_materials",
        "member_batches",
    ):
        op.drop_table(table)
    op.drop_column("member_profiles", "batch_no")
    op.drop_column("member_profiles", "year")
