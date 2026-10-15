"""通知投递台账：承载“事件→渠道”的路由、去重、重试与留痕。

对应《党建工作智能体_LangChain实现项目文档》5.9.4（提醒渠道全部可配置、提醒记录
进入审计）与 15.10（实现通知接口并登记一个渠道实现）。本表只记录**投递事实**，
业务提醒本身仍由 ``member_reminders`` / ``assessment_reminders`` 承载。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 已登记的事件名（新增事件无需迁移；这里只做常量与文档）
EVENT_MEMBER_REMINDER = "member_reminder"
EVENT_ASSESSMENT_REMINDER = "assessment_reminder"
EVENT_MEMBER_STAGE_TRANSITION = "member_stage_transition"
EVENT_MEETING_ARCHIVED = "meeting_archived"
EVENT_ASSESSMENT_COMPLETED = "assessment_completed"
EVENT_CHANNEL_SELF_TEST = "channel_self_test"

KNOWN_EVENTS = frozenset(
    {
        EVENT_MEMBER_REMINDER,
        EVENT_ASSESSMENT_REMINDER,
        EVENT_MEMBER_STAGE_TRANSITION,
        EVENT_MEETING_ARCHIVED,
        EVENT_ASSESSMENT_COMPLETED,
        EVENT_CHANNEL_SELF_TEST,
    }
)

# 站内渠道：投递即台账落库，用户端从同一张表读取，不产生外部调用
CHANNEL_IN_APP = "inapp"

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"

# 失败原因分类，避免把渠道凭据或异常原文写进台账
ERROR_UNKNOWN_CHANNEL = "unknown_channel"
ERROR_NOT_CONFIGURED = "channel_not_configured"
ERROR_DELIVERY_FAILED = "delivery_failed"


class NotificationDelivery(Base):
    """一条“事件×渠道×接收人”的投递记录。

    同一 ``(租户, 去重键, 渠道)`` 只允许一行：补偿扫描、人工重试与并发请求都不会
    造成重复外发；重试用尽后保留失败分类，供运维查询而不是静默丢弃。
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dedup_key", "channel", name="uq_notification_delivery_dedup"
        ),
        Index("ix_notification_deliveries_owner", "tenant_id", "recipient_id", "created_at"),
        Index("ix_notification_deliveries_status", "tenant_id", "status"),
    )

    event: Mapped[str] = mapped_column(String(40), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    recipient_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recipient_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(60), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
