"""中心组学习和共用活动、修订证据；不改动既有业务表和数据。

Revision ID: 006
Revises: 005
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _base_columns() -> list:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def _review_columns() -> list:
    return [
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("submitted_by", sa.String(36)),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
    ]


def _json(name: str, default: str = "[]") -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text(f"'{default}'::json"))


def upgrade() -> None:
    op.create_table(
        "meeting_records",
        *_base_columns(),
        *_review_columns(),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("activity_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column("held_on", sa.Date()),
        sa.Column("host", sa.String(100), nullable=False, server_default=""),
        _json("participants"),
        _json("source_doc_ids"),
        _json("sources"),
        _json("context", "{}"),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        _json("minutes", "{}"),
        sa.Column("archived_at", sa.DateTime()),
        sa.Column("archive_policy_version", sa.Integer()),
    )
    op.create_index(
        "ix_meeting_scope_date", "meeting_records", ["tenant_id", "org_unit_id", "held_on"]
    )
    op.create_table(
        "study_plans",
        *_base_columns(),
        *_review_columns(),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        _json("priorities"),
        _json("source_doc_ids"),
        _json("sources"),
        sa.Column("responsible", sa.String(100), nullable=False),
        sa.UniqueConstraint("tenant_id", "org_unit_id", "year", name="uq_study_plan_year"),
    )
    op.create_index("ix_study_plan_scope_year", "study_plans", ["tenant_id", "org_unit_id", "year"])
    op.create_table(
        "study_plan_items",
        *_base_columns(),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("study_plans.id"), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column("responsible", sa.String(100), nullable=False),
        _json("source_doc_ids"),
        _json("sources"),
        sa.Column("agenda", sa.Text(), nullable=False, server_default=""),
        sa.Column("outline", sa.Text(), nullable=False, server_default=""),
        sa.Column("template_version", sa.String(40)),
        sa.Column(
            "meeting_record_id", sa.String(36), sa.ForeignKey("meeting_records.id"), unique=True
        ),
    )
    op.create_index(
        "ix_study_item_plan_date", "study_plan_items", ["tenant_id", "plan_id", "scheduled_on"]
    )
    op.create_table(
        "content_revisions",
        *_base_columns(),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        _json("snapshot", "{}"),
        sa.UniqueConstraint(
            "tenant_id", "resource_type", "resource_id", "revision", name="uq_content_revision"
        ),
    )
    op.create_index(
        "ix_content_revision_resource",
        "content_revisions",
        ["tenant_id", "resource_type", "resource_id"],
    )
    for table in ("meeting_records", "study_plans", "study_plan_items", "content_revisions"):
        op.create_index(f"ix_{table}_id", table, ["id"])
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in ("content_revisions", "study_plan_items", "study_plans", "meeting_records"):
        op.drop_table(table)
