"""共用活动记录；中心组学习与组织生活复用同一记录、原文和审核版本。"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingRecord(Base):
    """一次活动只保存一条记录，修订与审核证据另存只追加版本。"""

    __tablename__ = "meeting_records"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (Index("ix_meeting_scope_date", "tenant_id", "org_unit_id", "held_on"),)

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    scheduled_on: Mapped[date] = mapped_column(Date, nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    host: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    participants: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    source_doc_ids: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    sources: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    context: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    minutes: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archive_policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MeetingTask(Base):
    """会议任务台账；原文未明确责任人或期限时留空，人工确认后进入台账。"""

    __tablename__ = "meeting_tasks"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_meeting_tasks_scope_status", "tenant_id", "org_unit_id", "status"),
        Index("ix_meeting_tasks_record", "tenant_id", "record_id"),
    )

    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending/active/done/cancelled
    confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handle_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ContentRevision(Base):
    """业务修订与人工审核证据；服务只追加，不覆盖旧内容。"""

    __tablename__ = "content_revisions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "resource_type", "resource_id", "revision", name="uq_content_revision"
        ),
        Index("ix_content_revision_resource", "tenant_id", "resource_type", "resource_id"),
    )

    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
