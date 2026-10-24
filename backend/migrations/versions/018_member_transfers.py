"""数据库迁移脚本：党员组织关系接转（T-MEM-14）

Revision ID: 018_member_transfers
Revises: 017_member_reviews
Create Date: 2026-10-16

新增 ``member_transfers`` 表，一条记录 = 一次组织关系接转（转入 / 转出）与介绍信要素。
依据《中国共产党党员教育管理工作条例》第五章"党员组织关系管理"：党员组织关系介绍信
是党员政治身份的证明，转移组织关系须办理转入 / 转出；介绍信有效期按上级党组织规定。

**为什么不复用 ``member_stage_history``**：那条表记的是"发展阶段流转"（入党申请人 →
积极分子 → …），接转是"组织关系移动"这一件独立的事——正式党员转出后仍然是正式党员，
把接转写进阶段历史会让按阶段统计与阶段时间顺序校验读到不是流转的行。因而本表只指向
``member_profiles``，不写阶段、不删档案。

**为什么状态能停在"待接收"**：转出只是开了介绍信，本人到新组织报到并回执后才算落地。
表以 ``status``（pending / settled / revoked）承载这一中间状态，并记 ``valid_until``
供"到期未回执"提示；作废（介绍信开错 / 重新开具）记 ``revoked_on`` 与理由，不物理删除。

**为什么不建接收单位联系人字段**：接收单位联系人与电话属第三人信息，接转只需要对方
组织名称与介绍信要素，落库越少越好。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "018_member_transfers"
down_revision = "017_member_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "member_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=False),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("member_name", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(20), nullable=False, server_default=""),
        sa.Column("counterpart_org", sa.String(200), nullable=False, server_default=""),
        sa.Column("letter_no", sa.String(64), nullable=False, server_default=""),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("settled_on", sa.Date(), nullable=True),
        sa.Column("receipt_no", sa.String(64), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("revoked_on", sa.Date(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # 常见查询路径：某组织待接收 / 已转出的接转台账。
    op.create_index(
        "ix_member_transfers_scope",
        "member_transfers",
        ["tenant_id", "org_unit_id", "direction", "status"],
    )
    # 一条档案的接转历史按时间读回，用于推导当前组织关系状态。
    op.create_index(
        "ix_member_transfers_profile",
        "member_transfers",
        ["tenant_id", "profile_id", "created_at"],
    )
    # 组织关系状态缓存列：唯一事实来源是上面的接转台账，本列只由 TransferService
    # 从台账推导后写入，供名册、名册统计与"应评议党员"直接过滤（存量默认在册）。
    op.add_column(
        "member_profiles",
        sa.Column("relation_status", sa.String(20), nullable=False, server_default="in_place"),
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("member_profiles", "relation_status")
    op.drop_index("ix_member_transfers_profile", table_name="member_transfers")
    op.drop_index("ix_member_transfers_scope", table_name="member_transfers")
    op.drop_table("member_transfers")
