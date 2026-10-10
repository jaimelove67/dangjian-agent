"""培养对象台账；阶段登记由组织人员完成，规则建议不修改台账。"""

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class MemberProfile(Base):
    __tablename__ = "member_profiles"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_member_profiles_stage", "tenant_id", "current_stage", "created_at"),
        Index("ix_member_profiles_org_created", "tenant_id", "org_unit_id", "created_at"),
    )

    name = Column(String(50), nullable=False)
    org_name = Column(String(200), nullable=False)
    org_unit_id = Column(String(36), nullable=True)
    current_stage = Column(String(20), nullable=False, default="applicant")
    stage_joined_on = Column(Date, nullable=False, default=date.today)
    materials = Column(JSON, nullable=False, default=list)
    pending = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    year = Column(Integer, nullable=True)
    batch_no = Column(String(20), nullable=True)


class MemberBatch(Base):
    """年度发展批次；人员可通过批次归属追溯跨年度。"""

    __tablename__ = "member_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "batch_no", name="uq_member_batch_year_no"),
        Index("ix_member_batches_scope_year", "tenant_id", "org_unit_id", "year"),
    )

    year = Column(Integer, nullable=False)
    batch_no = Column(String(20), nullable=False)
    label = Column(String(100), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    org_name = Column(String(200), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class MemberMaterial(Base):
    """材料记录；补交、退回与版本追踪，不能虚构原始文件或通过状态。"""

    __tablename__ = "member_materials"
    __table_args__ = (Index("ix_member_materials_profile", "tenant_id", "profile_id", "stage"),)

    profile_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    stage = Column(String(20), nullable=False)
    material_type = Column(String(100), nullable=False)
    file_version = Column(String(100), nullable=False, default="")
    submit_date = Column(Date, nullable=True)
    submitter_id = Column(String(36), nullable=True)
    review_status = Column(String(20), nullable=False, default="pending")
    note = Column(Text, nullable=False, default="")


class MemberStageHistory(Base):
    """人工阶段流转历史；记录决策人、依据与意见，持久化合法顺序校验。"""

    __tablename__ = "member_stage_history"
    __table_args__ = (Index("ix_member_stage_history_profile", "tenant_id", "profile_id"),)

    profile_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    from_stage = Column(String(20), nullable=False)
    to_stage = Column(String(20), nullable=False)
    decision_date = Column(Date, nullable=False)
    basis = Column(Text, nullable=False)
    opinion = Column(Text, nullable=False, default="")
    decided_by = Column(String(36), nullable=False)


class MemberReminder(Base):
    """关键节点提醒台账；按阶段时限与批次规则计算，可查、可完成、可去重。"""

    __tablename__ = "member_reminders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "profile_id", "kind", "due_on", name="uq_member_reminder_dedup"
        ),
        Index("ix_member_reminders_due", "tenant_id", "org_unit_id", "due_on", "status"),
    )

    profile_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    kind = Column(String(40), nullable=False)
    due_on = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="open")
    processed_by = Column(String(36), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=False, default="")


class MemberCultivation(Base):
    """培养与表现数据；每项关联统计期间、来源记录与核验人，供后续考核复用。"""

    __tablename__ = "member_cultivation"
    __table_args__ = (
        Index("ix_member_cultivation_profile", "tenant_id", "profile_id", "category"),
    )

    profile_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    category = Column(String(40), nullable=False)
    score = Column(Numeric(10, 2), nullable=True)
    period = Column(String(40), nullable=False, default="")
    source_note = Column(String(500), nullable=False, default="")
    verified_by = Column(String(36), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    is_risk = Column(Boolean, nullable=False, default=False)
    risk_note = Column(String(500), nullable=False, default="")


class MemberVote(Base):
    """多轮选优投票；重复记录按批次、轮次与投票人去重，明细按最小权限展示。"""

    __tablename__ = "member_votes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "round_no", "voter_id", "profile_id", name="uq_member_vote_dedup"
        ),
        Index("ix_member_votes_batch", "tenant_id", "batch_no", "round_no", "profile_id"),
    )

    batch_no = Column(String(20), nullable=False)
    round_no = Column(Integer, nullable=False)
    profile_id = Column(String(36), nullable=False)
    voter_id = Column(String(36), nullable=False)
    vote = Column(String(20), nullable=False)
    comment = Column(Text, nullable=False, default="")


class MemberArchiveCheck(Base):
    """档案检查结果；每项异常可定位到材料与规则，结果仅为检查提示。"""

    __tablename__ = "member_archive_checks"
    __table_args__ = (Index("ix_member_archive_checks_profile", "tenant_id", "profile_id"),)

    profile_id = Column(String(36), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    checked_at = Column(DateTime, nullable=False)
    checked_by = Column(String(36), nullable=False)
    rule_version = Column(String(20), nullable=False)
    result = Column(JSON, nullable=False, default=dict)
