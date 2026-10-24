"""保留本地问答风险信息并为组织名册查询添加索引。

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qa_sessions",
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "qa_sessions",
        sa.Column(
            "disclaimer", sa.Text(), nullable=False,
            server_default="本回答仅供参考，具体以组织部门确认为准。",
        ),
    )
    op.add_column(
        "qa_sessions", sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("qa_sessions", sa.Column("session_id", sa.String(64), nullable=True))
    op.execute("UPDATE qa_sessions SET refused = NOT has_sufficient_evidence")
    op.create_index(
        "ix_member_profiles_org_created", "member_profiles", ["tenant_id", "org_unit_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_member_profiles_org_created", table_name="member_profiles")
    for column in ("session_id", "refused", "disclaimer", "warnings"):
        op.drop_column("qa_sessions", column)
