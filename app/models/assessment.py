"""年度考核台账；规则、归集快照与计划版本均可回查，审核只来自人工。"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssessmentIndicator(Base):
    """同学校、年度和编码下追加规则版本，不覆盖已生效规则。"""

    __tablename__ = "assessment_indicators"
    __table_args__ = (
        UniqueConstraint("tenant_id", "school_org_id", "year", "code", "version"),
        Index("ix_assessment_indicators_year", "tenant_id", "school_org_id", "year"),
    )

    school_org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_options: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    target: Mapped[str] = mapped_column(String(50), nullable=False)
    comparison: Mapped[str] = mapped_column(String(10), nullable=False, default="gte")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="项")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    required_evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmation_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)


class AssessmentTask(Base):
    """人工年度任务；特色创新值保留依据，修改后重新审核。"""

    __tablename__ = "assessment_tasks"
    __table_args__ = (Index("ix_assessment_tasks_scope", "tenant_id", "org_unit_id", "year"),)

    school_org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    declared_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_opinion: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AssessmentEvidence(Base):
    """指标到真实知识文档版本的链接；不复制或伪造原始材料。"""

    __tablename__ = "assessment_evidence"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "org_unit_id", "year", "indicator_code", "requirement_key", "doc_id"
        ),
        Index("ix_assessment_evidence_scope", "tenant_id", "org_unit_id", "year"),
    )

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(100), nullable=False)
    doc_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_opinion: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AssessmentRun(Base):
    """可复算的输入与结果快照；相同输入复用同一次计算。"""

    __tablename__ = "assessment_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "year", "fingerprint"),
        Index("ix_assessment_runs_scope", "tenant_id", "org_unit_id", "year", "created_at"),
    )

    school_org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(30), nullable=False)
    inputs: Mapped[Any] = mapped_column(JSON, nullable=False)
    results: Mapped[Any] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_opinion: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AssessmentPlan(Base):
    """学院/支部计划参考；修订追加新版本并清除审核状态。"""

    __tablename__ = "assessment_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "year", "version"),
        Index("ix_assessment_plans_scope", "tenant_id", "org_unit_id", "year"),
    )

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_opinion: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AssessmentPolicy(Base):
    """电子归档默认关闭；学校确认人、依据与配置版本持久化。"""

    __tablename__ = "assessment_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "school_org_id"),)

    school_org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    archive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_advance_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmation_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AssessmentReminder(Base):
    """站内提醒及处理记录；重复扫描不重复生成或发送外部消息。"""

    __tablename__ = "assessment_reminders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key"),
        Index("ix_assessment_reminders_owner", "tenant_id", "owner_id", "status"),
    )

    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    handled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handling_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AssessmentArchive(Base):
    """审核后归档目录快照；保存来源版本、内容摘要及合规确认版本。"""

    __tablename__ = "assessment_archives"
    __table_args__ = (UniqueConstraint("tenant_id", "run_id"),)

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
