"""数据库迁移脚本：上级党组织审批 / 备案报送台账（T-MEM-11）

Revision ID: 019_member_upper_reports
Revises: 018_member_transfers
Create Date: 2026-10-16

新增 ``member_upper_reports`` 表，一条记录 = 一次"向上级党组织报送 + 回填上级批复结果"。

依据《中国共产党发展党员工作细则》：确定入党积极分子（第八条）与列为发展对象（第十三条）
须报上级党委**备案**；接收预备党员（第二十一条、第二十二条）与预备党员转正须报上级党委
**审批**，党委应当在三个月内审批（第二十五条，特殊情况不超过六个月）。

**为什么不建"审批"工作流表**：系统里没有上级党组织的登录身份，也没有跨组织审批通道，
任何"系统批准入党"的建模都会把责任从上级党组织挪到软件上。因此本表只承载两个可由支部
如实登记的事实——**已报送**（``status = submitted``，含报送材料清单快照）与**上级批复结果
回填**（``status = settled``，含批复文号 / 日期 / 结论）；回填不改发展阶段，阶段仍由授权人员
在 ``member_stage_history`` 上人工办理。

**为什么回填必须有文号或说明**：没有文号的"同意"无法对账，也就不是批复；定为
``supplement``（需补充材料）时必须写清缺什么，否则回填变成走过场。校验在服务层完成，
列上只做非空约束。

**为什么只记上级组织名称文本**：受理备案的可能是院系党委、校党委或市委组织部，未必在本
系统的组织树里，硬套组织字典会把"填不进去"变成登记失败。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "019_member_upper_reports"
down_revision = "018_member_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_upper_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("item", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="record"),
        sa.Column("upper_org", sa.String(200), nullable=False, server_default=""),
        sa.Column("letter_no", sa.String(64), nullable=False, server_default=""),
        sa.Column("submitted_on", sa.Date(), nullable=False),
        sa.Column("materials", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("result", sa.String(20), nullable=False, server_default=""),
        sa.Column("decided_on", sa.Date(), nullable=True),
        sa.Column("reply_no", sa.String(64), nullable=False, server_default=""),
        sa.Column("decide_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("revoked_on", sa.Date(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # 常见查询路径：某组织在办 / 已回填的报送台账（列表、汇总与超期提示共用）。
    op.create_index(
        "ix_member_upper_reports_scope",
        "member_upper_reports",
        ["tenant_id", "org_unit_id", "status", "submitted_on"],
    )
    # 一条档案的事项查重与历史读回：同一事项同时只允许一次未办结的报送。
    op.create_index(
        "ix_member_upper_reports_profile",
        "member_upper_reports",
        ["tenant_id", "profile_id", "item"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_member_upper_reports_profile", table_name="member_upper_reports")
    op.drop_index("ix_member_upper_reports_scope", table_name="member_upper_reports")
    op.drop_table("member_upper_reports")
