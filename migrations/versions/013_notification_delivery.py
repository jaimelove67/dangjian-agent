"""数据库迁移脚本：通知投递台账

Revision ID: 013_notification_delivery
Revises: 012_member_self
Create Date: 2026-10-15

新增 ``notification_deliveries`` 表，承载“事件→渠道”的投递去重、重试与留痕
（见《党建工作智能体_LangChain实现项目文档》5.9.4 与 15.10）。业务提醒本身仍由
``member_reminders`` / ``assessment_reminders`` 承载，本表只记录投递事实。
租户隔离与时间戳字段由 Base 提供。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （与既有迁移保持一致的导入风格）

# revision identifiers, used by Alembic.
revision = "013_notification_delivery"
down_revision = "012_member_self"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=True),
        sa.Column("recipient_address", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(60), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # 同一租户、同一去重键、同一渠道只允许一行：补偿扫描与人工重试都不会重复外发。
    op.create_unique_constraint(
        "uq_notification_delivery_dedup",
        "notification_deliveries",
        ["tenant_id", "dedup_key", "channel"],
    )
    # 常见查询路径：某人收到的投递记录、某租户的失败投递。
    op.create_index(
        "ix_notification_deliveries_owner",
        "notification_deliveries",
        ["tenant_id", "recipient_id", "created_at"],
    )
    op.create_index(
        "ix_notification_deliveries_status",
        "notification_deliveries",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_owner", table_name="notification_deliveries")
    op.drop_constraint(
        "uq_notification_delivery_dedup", "notification_deliveries", type_="unique"
    )
    op.drop_table("notification_deliveries")
