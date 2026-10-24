"""数据库迁移脚本：民主评议党员结果（T-ORG-11）

Revision ID: 017_member_reviews
Revises: 016_qa_session_versions
Create Date: 2026-10-16

新增 ``member_reviews`` 表，一条记录 = 一个年度 × 一名党员，承载"个人自评、
党员互评、民主测评、支部评定意见"四项程序与最终等次。依据《中国共产党支部工作
条例（试行）》第十九条：党支部一般每年开展 1 次民主评议党员，由支委会或党员大会
根据评议情况和党员日常表现提出评定意见，可以结合组织生活会一并进行。

**为什么不复用 ``member_stage_history``**：那条表记的是"阶段流转"这一件事
（from_stage → to_stage），民主评议是年度结论且要送审、要能改后重审，两件事的
生命周期不同，硬塞进去会让"阶段历史"里混进不是阶段流转的行。

**为什么不把评议结果写进知识库或模型**：等次是组织结论，只有人工能定；本表只存
录入内容与流转状态，留痕走 ``content_revisions``（resource_type=member_review），
不另建版本表。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "017_member_reviews"
down_revision = "016_qa_session_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("procedure", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("grade", sa.String(20), nullable=False, server_default=""),
        sa.Column("basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("rectification", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("submitted_by", sa.String(36), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # 一人一年一条：重复发起时不会把同一个人评两次、留下两个互相矛盾的等次。
    op.create_unique_constraint(
        "uq_member_review_year_profile",
        "member_reviews",
        ["tenant_id", "year", "profile_id"],
    )
    # 常见查询路径：某支部某年度的评议进度与汇总。
    op.create_index(
        "ix_member_reviews_scope",
        "member_reviews",
        ["tenant_id", "org_unit_id", "year", "review_status"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_reviews_scope", table_name="member_reviews")
    op.drop_constraint("uq_member_review_year_profile", "member_reviews", type_="unique")
    op.drop_table("member_reviews")
