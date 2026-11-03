"""Normalize legacy member information collection statuses.

Revision ID: 040_member_info_status
Revises: 039_political_review_checklist
Create Date: 2026-11-03

Early test/import fixtures used ``approved`` although the API contract only
accepts workflow states such as ``archived``.  A single legacy row used to make
the whole collection list fail serialization, so normalize it once here.
"""

import sqlalchemy as sa
from alembic import op

revision = "040_member_info_status"
down_revision = "039_political_review_checklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE member_info_collections "
            "SET status = 'archived', updated_at = now() "
            "WHERE status = 'approved'"
        )
    )


def downgrade() -> None:
    # 数据归一不可逆：无法可靠区分原本就是 archived 的记录和由 approved 转换来的记录。
    pass
