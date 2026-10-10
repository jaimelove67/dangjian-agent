"""中心组年度重点、计划条目以及共用活动记录的稳定关联。"""

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class StudyPlan(Base):
    """同一组织每年一份年度计划；每次修订保留完整版本。"""

    __tablename__ = "study_plans"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "year", name="uq_study_plan_year"),
        Index("ix_study_plan_scope_year", "tenant_id", "org_unit_id", "year"),
    )

    org_unit_id = Column(String(36), nullable=False)
    year = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    priorities = Column(JSON, nullable=False, default=list)
    source_doc_ids = Column(JSON, nullable=False, default=list)
    sources = Column(JSON, nullable=False, default=list)
    responsible = Column(String(100), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    review_status = Column(String(20), nullable=False, default="draft")
    submitted_by = Column(String(36), nullable=True)
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=False, default="")


class StudyPlanItem(Base):
    """每期学习安排；活动外键唯一，防止重试或统计创建重复流水。"""

    __tablename__ = "study_plan_items"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (Index("ix_study_item_plan_date", "tenant_id", "plan_id", "scheduled_on"),)

    plan_id = Column(String(36), ForeignKey("study_plans.id"), nullable=False)
    topic = Column(String(300), nullable=False)
    scheduled_on = Column(Date, nullable=False)
    responsible = Column(String(100), nullable=False)
    source_doc_ids = Column(JSON, nullable=False, default=list)
    sources = Column(JSON, nullable=False, default=list)
    agenda = Column(Text, nullable=False, default="")
    outline = Column(Text, nullable=False, default="")
    template_version = Column(String(40), nullable=True)
    meeting_record_id = Column(
        String(36), ForeignKey("meeting_records.id"), nullable=True, unique=True
    )
