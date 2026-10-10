"""共用活动记录；中心组学习与组织生活复用同一记录、原文和审核版本。"""

from sqlalchemy import JSON, Column, Date, DateTime, Index, Integer, String, Text, UniqueConstraint

from app.db.base import Base


class MeetingRecord(Base):
    """一次活动只保存一条记录，修订与审核证据另存只追加版本。"""

    __tablename__ = "meeting_records"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (Index("ix_meeting_scope_date", "tenant_id", "org_unit_id", "held_on"),)

    org_unit_id = Column(String(36), nullable=False)
    activity_type = Column(String(40), nullable=False)
    title = Column(String(300), nullable=False)
    scheduled_on = Column(Date, nullable=False)
    held_on = Column(Date, nullable=True)
    host = Column(String(100), nullable=False, default="")
    participants = Column(JSON, nullable=False, default=list)
    source_doc_ids = Column(JSON, nullable=False, default=list)
    sources = Column(JSON, nullable=False, default=list)
    context = Column(JSON, nullable=False, default=dict)
    transcript = Column(Text, nullable=False, default="")
    minutes = Column(JSON, nullable=False, default=dict)
    revision = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="draft")
    submitted_by = Column(String(36), nullable=True)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=False, default="")
    archived_at = Column(DateTime, nullable=True)
    archive_policy_version = Column(Integer, nullable=True)


class MeetingTask(Base):
    """会议任务台账；原文未明确责任人或期限时留空，人工确认后进入台账。"""

    __tablename__ = "meeting_tasks"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_meeting_tasks_scope_status", "tenant_id", "org_unit_id", "status"),
        Index("ix_meeting_tasks_record", "tenant_id", "record_id"),
    )

    record_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    task_text = Column(Text, nullable=False)
    source_start = Column(Integer, nullable=False)
    source_end = Column(Integer, nullable=False)
    owner_name = Column(String(100), nullable=False, default="")
    due_on = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending/active/done/cancelled
    confirmed_by = Column(String(36), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    handled_at = Column(DateTime, nullable=True)
    handle_note = Column(Text, nullable=False, default="")


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

    resource_type = Column(String(40), nullable=False)
    resource_id = Column(String(36), nullable=False)
    revision = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    actor_id = Column(String(36), nullable=False)
    reason = Column(Text, nullable=False)
    snapshot = Column(JSON, nullable=False)
