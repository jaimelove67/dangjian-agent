"""年度考核台账；规则、归集快照与计划版本均可回查，审核只来自人工。"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class AssessmentIndicator(Base):
    """同学校、年度和编码下追加规则版本，不覆盖已生效规则。"""

    __tablename__ = "assessment_indicators"
    __table_args__ = (
        UniqueConstraint("tenant_id", "school_org_id", "year", "code", "version"),
        Index("ix_assessment_indicators_year", "tenant_id", "school_org_id", "year"),
    )

    school_org_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    code = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    requirement = Column(Text, nullable=False)
    formula = Column(String(20), nullable=False)
    source = Column(String(30), nullable=False)
    source_options = Column(JSON, nullable=False, default=dict)
    target = Column(String(50), nullable=False)
    comparison = Column(String(10), nullable=False, default="gte")
    unit = Column(String(20), nullable=False, default="项")
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    effective_from = Column(DateTime, nullable=False)
    required_evidence = Column(JSON, nullable=False, default=list)
    confirmed = Column(Boolean, nullable=False, default=False)
    confirmation_note = Column(Text, nullable=False, default="")
    created_by = Column(String(36), nullable=False)


class AssessmentTask(Base):
    """人工年度任务；特色创新值保留依据，修改后重新审核。"""

    __tablename__ = "assessment_tasks"
    __table_args__ = (Index("ix_assessment_tasks_scope", "tenant_id", "org_unit_id", "year"),)

    school_org_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    indicator_code = Column(String(64), nullable=False)
    title = Column(String(200), nullable=False)
    owner_id = Column(String(36), nullable=False)
    due_date = Column(Date, nullable=False)
    declared_progress = Column(Integer, nullable=False, default=0)
    manual_value = Column(String(50), nullable=True)
    completed_on = Column(Date, nullable=True)
    basis = Column(Text, nullable=False, default="")
    revision = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="pending")
    created_by = Column(String(36), nullable=False)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_opinion = Column(Text, nullable=False, default="")


class AssessmentEvidence(Base):
    """指标到真实知识文档版本的链接；不复制或伪造原始材料。"""

    __tablename__ = "assessment_evidence"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "org_unit_id", "year", "indicator_code", "requirement_key", "doc_id"
        ),
        Index("ix_assessment_evidence_scope", "tenant_id", "org_unit_id", "year"),
    )

    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    indicator_code = Column(String(64), nullable=False)
    requirement_key = Column(String(100), nullable=False)
    doc_id = Column(String(100), nullable=False)
    source_version = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="pending")
    created_by = Column(String(36), nullable=False)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_opinion = Column(Text, nullable=False, default="")


class AssessmentRun(Base):
    """可复算的输入与结果快照；相同输入复用同一次计算。"""

    __tablename__ = "assessment_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "year", "fingerprint"),
        Index("ix_assessment_runs_scope", "tenant_id", "org_unit_id", "year", "created_at"),
    )

    school_org_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    engine_version = Column(String(30), nullable=False)
    inputs = Column(JSON, nullable=False)
    results = Column(JSON, nullable=False)
    review_status = Column(String(20), nullable=False, default="pending")
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(String(36), nullable=False)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_opinion = Column(Text, nullable=False, default="")


class AssessmentPlan(Base):
    """学院/支部计划参考；修订追加新版本并清除审核状态。"""

    __tablename__ = "assessment_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "year", "version"),
        Index("ix_assessment_plans_scope", "tenant_id", "org_unit_id", "year"),
    )

    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    run_id = Column(String(36), nullable=False)
    content = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="pending")
    created_by = Column(String(36), nullable=False)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_opinion = Column(Text, nullable=False, default="")


class AssessmentPolicy(Base):
    """电子归档默认关闭；学校确认人、依据与配置版本持久化。"""

    __tablename__ = "assessment_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "school_org_id"),)

    school_org_id = Column(String(36), nullable=False)
    archive_enabled = Column(Boolean, nullable=False, default=False)
    reminder_advance_days = Column(Integer, nullable=False, default=14)
    version = Column(Integer, nullable=False, default=1)
    confirmation_note = Column(Text, nullable=False, default="")
    confirmed_by = Column(String(36), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)


class AssessmentReminder(Base):
    """站内提醒及处理记录；重复扫描不重复生成或发送外部消息。"""

    __tablename__ = "assessment_reminders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key"),
        Index("ix_assessment_reminders_owner", "tenant_id", "owner_id", "status"),
    )

    task_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    owner_id = Column(String(36), nullable=False)
    kind = Column(String(30), nullable=False)
    dedup_key = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="open")
    handled_by = Column(String(36), nullable=True)
    handled_at = Column(DateTime, nullable=True)
    handling_note = Column(Text, nullable=False, default="")


class AssessmentArchive(Base):
    """审核后归档目录快照；保存来源版本、内容摘要及合规确认版本。"""

    __tablename__ = "assessment_archives"
    __table_args__ = (UniqueConstraint("tenant_id", "run_id"),)

    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    run_id = Column(String(36), nullable=False)
    policy_version = Column(Integer, nullable=False)
    manifest = Column(JSON, nullable=False)
    created_by = Column(String(36), nullable=False)
