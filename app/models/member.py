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
    # 字段级敏感分级（T-MEM-12）：登记时按材料类型带出的密级快照，配置调整不回改历史。
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
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
    """多轮选优投票；重复记录按**批次**、轮次与投票人去重，明细按最小权限展示。

    批次是一次独立的选优：同一投票人在新年度批次的第 1 轮投票不算重复提交。唯一约束必须带
    ``batch_no``，才会与服务层查重（同租户 + 同批次 + 同轮次 + 同投票人）是同一条规则；
    少一项就会让正常投票撞唯一键、被抛成 500 而不是被查重挡住。约束按"投票人 + 投票对象"
    保留 ``profile_id``：一次提交本来就要给名单里每个人各留一条记录。
    """

    __tablename__ = "member_votes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "batch_no",
            "round_no",
            "voter_id",
            "profile_id",
            name="uq_member_vote_dedup",
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
    # 字段级敏感分级（T-MEM-12）：评议含个人自评 / 党员互评 / 支部评定意见原文。
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, default="sensitive")
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


class MemberUpperReport(Base):
    """上级党组织审批 / 备案报送台账（报送 + 回填上级批复结果）。

    依据《中国共产党发展党员工作细则》：确定入党积极分子（第八条）与列为发展对象
    （第十三条）须报上级党委**备案**；接收预备党员（第二十一条、第二十二条）与预备党员
    转正须报上级党委**审批**，党委应当在三个月内审批（第二十五条，特殊情况不超过六个月）。

    这张表只做两件事：**登记"支部已把材料报送出去"这一事实**，以及**回填上级的批复结果**。
    它不能、也不应该替代上级审批：系统里没有上级党组织的登录身份，也就不存在"系统批准"
    这种结论。因此：

    * ``status`` 停在 ``submitted``（已报送、等批复）本身就是常态，不是异常；
    * 回填批复（``settled``）要求给出批复文号（``reply_no``）或需补充材料的具体说明——
      没有文号的"同意"不是批复；
    * 回填**不改发展阶段**，阶段仍由授权人员按程序在 ``member_stage_history`` 上人工办理。

    ``upper_org`` 只记上级组织名称文本：受理备案的可能是院系党委、校党委或市委组织部，
    未必在本系统的组织树里，硬套组织字典会把"填不进去"变成登记失败。
    """

    __tablename__ = "member_upper_reports"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index(
            "ix_member_upper_reports_scope", "tenant_id", "org_unit_id", "status", "submitted_on"
        ),
        Index("ix_member_upper_reports_profile", "tenant_id", "profile_id", "item"),
    )

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 报送时的姓名 / 组织 / 阶段快照：人员改名、流转后历史行仍能读回去
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    member_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # 事项（activist_record / candidate_record / probationary_approval / member_approval）
    # 与类别（record 备案 / approval 审批）由服务层单源给出，请求只能选事项
    item: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="record")
    upper_org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    letter_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    submitted_on: Mapped[date] = mapped_column(Date, nullable=False)
    # 报送材料清单快照：与阶段材料要求同一来源，配置改了也不改写历史
    materials: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    # 回填的上级批复：agreed 同意 / rejected 不同意 / supplement 需补充材料（或留空）
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    decided_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reply_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    decide_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 操作版本：报送 / 回填 / 作废各留一版完整快照，编号只增不减
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MemberSelection(Base):
    """选优结论台账（模块2 / `T-MEM-13`、`T-MEM-06`）：支部研究形成的**拟推荐名单**。

    这张表的形状由三件不能让步的事决定：

    1. **系统不出结论**。名单与依据都是组织人员填写的（``candidates`` / ``basis``），
       服务层只做校验与留痕，**不读投票汇总替人排序或选人**——多轮投票是辅助材料，
       不是结论来源。投票明细只以**无记名汇总**快照进 ``evidence``（供审核人核对依据
       位置），不含投票人身份。
    2. **必经第二位组织人员审核**。``review_status`` 走"草稿 → 送审 → 审核"，
       送审人不得自审（``apply_review``），审核通过（``approved``）才是生效结论；
       未送审、被退回的结论界面上明确标出不可视为认定依据。
    3. **结论不等于阶段流转**。生效结论只是"组织认定依据"，阶段仍由授权人员在
       ``member_stage_history`` 上人工办理——系统不因为结论通过就改 ``current_stage``，
       也不自动向上级报送（报送走 `T-MEM-11` 台账，由人登记）。

    ``target_stage`` 只允许"向前"的阶段；``research_method`` 区分支委会 / 党员大会，
    因为细则要求"经支委会或党员大会研究确定"，两种程序都要能如实记下来。
    """

    __tablename__ = "member_selections"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_member_selections_scope", "tenant_id", "org_unit_id", "batch_no", "round_no"),
        Index("ix_member_selections_status", "tenant_id", "review_status", "created_at"),
    )

    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    batch_no: Mapped[str] = mapped_column(String(20), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 拟推进到的阶段（activist / candidate / probationary / member），只允许向前
    target_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    # 名单快照 [{"profile_id":…, "member_name":…, "stage":…}]：人员改名或流转后历史行仍可读回
    candidates: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    # 结论依据：必须由人写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录，不写等于没依据
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 无记名投票汇总快照（仅限名单内候选人）：只留票数规模与分布，不留投票人身份
    evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    research_on: Mapped[date] = mapped_column(Date, nullable=False)
    # 研究程序：committee 支委会 / member_meeting 党员大会
    research_method: Mapped[str] = mapped_column(String(20), nullable=False, default="committee")
    # 字段级敏感分级（T-MEM-12）：含组织对某人的评价与认定依据
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, default="sensitive")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MemberLeagueRecommendation(Base):
    """团组织推优台账（`T-MEM-06`）：记录"28 周岁以下青年入党"要有的推优环节。

    细则要求发展青年党员注重团组织推优，但**这项判断系统做不了**：名册里没有出生年月，
    也没有可核对的"是否属 28 周岁以下"的权威字段。因此本表只做两件事——把推优这件事
    如实记下来（推荐团组织 / 推荐日期 / 推优说明），以及在界面上提示"系统不判断年龄，
    请组织核对"。**不因为缺这条记录就阻断选优或阶段流转**（宁缺勿假：真实推优材料
    往往后补，硬拦会逼人填假日期），也不自动把推优记录写成选优结论。

    ``note`` 是推优说明，属第三人信息（可能含团组织 / 他人的评价意见），读取出口按
    密级（`member_selection_level`，默认敏感）收敛；作废保留记录与理由，不删除。
    """

    __tablename__ = "member_league_recommendations"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index(
            "ix_member_league_recommendations_scope",
            "tenant_id",
            "org_unit_id",
            "recommended_on",
        ),
        Index(
            "ix_member_league_recommendations_profile",
            "tenant_id",
            "profile_id",
            "recommended_on",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 登记时的姓名 / 组织 / 阶段快照
    org_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    member_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # 推荐团组织名称文本：可能是院系团委、校团委或校外团组织，未必在本系统组织树里
    league_org: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    recommended_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 字段级敏感分级（T-MEM-12）：推优说明含第三人评价意见
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, default="sensitive")
    revoked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 操作版本：登记 / 作废各留一版完整快照，编号只增不减
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
