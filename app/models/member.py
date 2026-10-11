"""培养对象台账；阶段登记由组织人员完成，规则建议不修改台账。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MemberProfile(Base):
    __tablename__ = "member_profiles"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_member_profiles_stage", "tenant_id", "current_stage", "created_at"),
        Index("ix_member_profiles_org_created", "tenant_id", "org_unit_id", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_stage: Mapped[str] = mapped_column(String(20), nullable=False, default="applicant")
    stage_joined_on: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    materials: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_no: Mapped[str | None] = mapped_column(String(20), nullable=True)


class MemberBatch(Base):
    """年度发展批次；人员可通过批次归属追溯跨年度。"""

    __tablename__ = "member_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "batch_no", name="uq_member_batch_year_no"),
        Index("ix_member_batches_scope_year", "tenant_id", "org_unit_id", "year"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MemberMaterial(Base):
    """材料记录；补交、退回与版本追踪，不能虚构原始文件或通过状态。"""

    __tablename__ = "member_materials"
    __table_args__ = (Index("ix_member_materials_profile", "tenant_id", "profile_id", "stage"),)

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    material_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    submit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MemberStageHistory(Base):
    """人工阶段流转历史；记录决策人、依据与意见，持久化合法顺序校验。"""

    __tablename__ = "member_stage_history"
    __table_args__ = (Index("ix_member_stage_history_profile", "tenant_id", "profile_id"),)

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    from_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    opinion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[str] = mapped_column(String(36), nullable=False)


class MemberReminder(Base):
    """关键节点提醒台账；按阶段时限与批次规则计算，可查、可完成、可去重。"""

    __tablename__ = "member_reminders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "profile_id", "kind", "due_on", name="uq_member_reminder_dedup"
        ),
        Index("ix_member_reminders_due", "tenant_id", "org_unit_id", "due_on", "status"),
    )

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    processed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MemberCultivation(Base):
    """培养与表现数据；每项关联统计期间、来源记录与核验人，供后续考核复用。"""

    __tablename__ = "member_cultivation"
    __table_args__ = (
        Index("ix_member_cultivation_profile", "tenant_id", "profile_id", "category"),
    )

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    period: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    source_note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_note: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class MemberVote(Base):
    """多轮选优投票；重复记录按批次、轮次与投票人去重，明细按最小权限展示。"""

    __tablename__ = "member_votes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "round_no", "voter_id", "profile_id", name="uq_member_vote_dedup"
        ),
        Index("ix_member_votes_batch", "tenant_id", "batch_no", "round_no", "profile_id"),
    )

    batch_no: Mapped[str] = mapped_column(String(20), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    voter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    vote: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MemberArchiveCheck(Base):
    """档案检查结果；每项异常可定位到材料与规则，结果仅为检查提示。"""

    __tablename__ = "member_archive_checks"
    __table_args__ = (Index("ix_member_archive_checks_profile", "tenant_id", "profile_id"),)

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    checked_by: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
