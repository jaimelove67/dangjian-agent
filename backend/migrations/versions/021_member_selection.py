"""数据库迁移脚本：选优结论与团组织推优台账（T-MEM-13、T-MEM-06）

Revision ID: 021_member_selection
Revises: 020_member_data_levels
Create Date: 2026-10-17

新增两张表：

* ``member_selections``——支部研究形成的**拟推荐名单**（选优结论），走"草稿 → 送审 →
  第二位组织人员审核"，审核通过才是生效结论。名单与依据都由人填写，服务层不读投票
  汇总替人排序或选人；投票明细只以**无记名汇总**快照进 ``evidence``。
* ``member_league_recommendations``——团组织推优环节台账（推荐团组织 / 推荐日期 /
  推优说明），可作废、保留记录。

**为什么结论需要"双人"而不是"谁保存谁算"**：选优结论是组织认定依据，一个人既填名单
又自己点"通过"，等于没有复核环节。表里因此保留 ``submitted_by`` / ``reviewed_by`` /
``reviewed_at`` / ``review_comment`` 与只增不减的 ``revision``，校验（送审人不得自审、
必填项缺一项不放行、修订后必须重新送审）在服务层完成。

**为什么不把团组织推优做成硬性拦截**：细则要求发展青年党员注重团组织推优，但系统里
没有出生年月，也没有可核对的"是否属 28 周岁以下"字段，硬拦会把"缺一条记录"变成
"填不进去"——真实推优材料常常后补。因此推优只登记 + 界面提示"系统不判断年龄，
请组织核对"，不阻断选优或阶段流转。

**为什么不给结论加唯一约束**：同一批次同一轮次可能出现不同事项（如"确定入党积极分子"
与"列为发展对象"）的两份结论，也可能因登记错误再登记一份；约束会把正常业务挡在门外，
重复由审核与留痕约束，而不是靠唯一键。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "021_member_selection"
down_revision = "020_member_data_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("batch_no", sa.String(20), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("target_stage", sa.String(20), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("research_on", sa.Date(), nullable=False),
        sa.Column("research_method", sa.String(20), nullable=False, server_default="committee"),
        sa.Column("data_level", sa.String(20), nullable=False, server_default="sensitive"),
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
    # 常见查询路径：某组织某批次某轮次的结论（列表与投票汇总对照用）。
    op.create_index(
        "ix_member_selections_scope",
        "member_selections",
        ["tenant_id", "org_unit_id", "batch_no", "round_no"],
    )
    # 待审核与审核历史：按状态 + 时间读回。
    op.create_index(
        "ix_member_selections_status",
        "member_selections",
        ["tenant_id", "review_status", "created_at"],
    )

    op.create_table(
        "member_league_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("league_org", sa.String(200), nullable=False, server_default=""),
        sa.Column("recommended_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_level", sa.String(20), nullable=False, server_default="sensitive"),
        sa.Column("revoked_on", sa.Date(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # 组织维度的推优台账（按推荐日期倒序列表）。
    op.create_index(
        "ix_member_league_recommendations_scope",
        "member_league_recommendations",
        ["tenant_id", "org_unit_id", "recommended_on"],
    )
    # 一个人可以有多条推优记录（积极分子阶段、发展对象阶段各一次），按档案 + 日期读回。
    op.create_index(
        "ix_member_league_recommendations_profile",
        "member_league_recommendations",
        ["tenant_id", "profile_id", "recommended_on"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index(
        "ix_member_league_recommendations_profile",
        table_name="member_league_recommendations",
    )
    op.drop_index(
        "ix_member_league_recommendations_scope",
        table_name="member_league_recommendations",
    )
    op.drop_table("member_league_recommendations")
    op.drop_index("ix_member_selections_status", table_name="member_selections")
    op.drop_index("ix_member_selections_scope", table_name="member_selections")
    op.drop_table("member_selections")
