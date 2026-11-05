"""会议主题推荐反馈：记录支部对推荐主题的实际使用判断。

反馈只影响后续推荐排序或去重，不改变已创建会议的审核、归档或正式结论。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingTopicFeedback(Base):
    __tablename__ = "meeting_topic_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "org_unit_id",
            "topic",
            name="uq_meeting_topic_feedback_scope",
        ),
        Index(
            "ix_meeting_topic_feedback_lookup",
            "tenant_id",
            "org_unit_id",
            "decision",
        ),
    )

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ids: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
