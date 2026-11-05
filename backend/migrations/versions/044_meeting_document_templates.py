"""Create versioned meeting document layout templates.

Revision ID: 044_meeting_document_templates
Revises: 043_external_fetch_state
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "044_meeting_document_templates"
down_revision = "043_external_fetch_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_document_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("org_unit_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_data", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("published_by", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "org_unit_id",
            "version",
            name="uq_meeting_document_template_version",
        ),
    )
    op.create_index(
        "ix_meeting_document_template_scope",
        "meeting_document_templates",
        ["tenant_id", "org_unit_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meeting_document_template_scope",
        table_name="meeting_document_templates",
    )
    op.drop_table("meeting_document_templates")
