"""培养对象台账；阶段登记由组织人员完成，规则建议不修改台账。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class MemberProfile(Base):
    __tablename__ = "member_profiles"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_member_profiles_stage", "tenant_id", "current_stage", "created_at"),
        Index("ix_member_profiles_org_created", "tenant_id", "org_unit_id", "created_at"),
        UniqueConstraint("tenant_id", "user_id", name="uq_member_profiles_tenant_user"),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_stage: Mapped[str] = mapped_column(String(20), nullable=False, default="applicant")
    stage_joined_on: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    materials: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 组织关系状态缓存（T-MEM-14）：in_place / out_pending / transferred_out。
    # 唯一事实来源是 member_transfers 台账，本列只由 TransferService 从台账推导后写入，
    # 供名册、名册统计与"应评议党员"直接过滤——三处口径必须一致，否则会出现
    # "名册说已转出、民主评议里还在评"的互相打脸。无接转记录恒为 in_place。
    relation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_place")
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
    __table_args__ = (
        Index("ix_member_materials_profile", "tenant_id", "profile_id", "stage"),
        Index("ix_member_materials_owner", "tenant_id", "user_id", "created_at"),
        UniqueConstraint(
            "tenant_id", "user_id", "submission_key", name="uq_member_material_submission"
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    org_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    material_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    file_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    submit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submission_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))


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


class MemberReview(Base):
    """民主评议党员结果（年度 × 党员）。

    程序与等次**由人工记录**：系统的职责是把"个人自评、党员互评、民主测评、支部
    评定意见"和最终等次如实留下来，供本人档案与考核复用，不替组织下结论、也不按
    票数自动排名定等次。一条记录一个人一个年度；重复发起按年度 + 党员去重。
    """

    __tablename__ = "member_reviews"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "profile_id", name="uq_member_review_year_profile"),
        Index("ix_member_reviews_scope", "tenant_id", "org_unit_id", "year", "review_status"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 发起时的姓名 / 组织 / 阶段快照：人员改名、流转或调出后，历年评议仍能读回去
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    member_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # {"self_assessment":…, "peer_review":…, "test":{…票数}, "branch_opinion":…}
    procedure: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    grade: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rectification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MemberTransfer(Base):
    """党员组织关系接转台账（转入 / 转出与介绍信）。

    依据《中国共产党党员教育管理工作条例》第五章"党员组织关系管理"：党员组织关系
    介绍信是党员政治身份的证明，转移组织关系须办理转入 / 转出。一条记录 = 一次接转。

    两条关键事实决定了表结构：**一是转出开介绍信不等于转出完成**——本人持介绍信到新
    组织报到、新组织回执（``settled``）才算落地，中间是"待接收"（``pending``），所以
    状态必须能停在中间，而不是一按就"已完成"；**二是接转不是阶段流转**——正式党员
    转出后仍然是正式党员，把接转写进 ``member_stage_history`` 会让"阶段历史"混进
    不是阶段流转的行，因此接转只指向 ``member_profiles``、不改发展阶段。

    ``counterpart_org`` 只记对方组织名称与介绍信要素；接收单位联系人与电话**不落库**：
    那是第三人信息，接转只需要组织名称与介绍信要素（编号 / 开具日期 / 有效期至）。
    """

    __tablename__ = "member_transfers"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_member_transfers_scope", "tenant_id", "org_unit_id", "direction", "status"),
        Index("ix_member_transfers_profile", "tenant_id", "profile_id", "created_at"),
    )

    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 接转发生时的姓名 / 组织 / 阶段快照：人员改名、流转或再次调动后历史行仍能读回去
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    member_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    counterpart_org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    letter_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 操作版本：登记 / 回执 / 作废各留一版完整快照，编号只增不减
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
