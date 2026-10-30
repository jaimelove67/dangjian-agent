"""发展党员全流程输入契约；阶段结论、审核状态与租户不能由请求伪造。"""

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Label = Annotated[str, Field(min_length=1, max_length=200)]
Reason = Annotated[str, Field(min_length=1, max_length=2000)]


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BatchCreate(MemberInput):
    year: int = Field(ge=2000, le=2100)
    batch_no: str = Field(min_length=1, max_length=20)
    label: Label
    org_unit_id: str = Field(min_length=1, max_length=36)
    reason: Reason


class ProfileUpdate(MemberInput):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    # 身份证号即开户时的登录账号来源：历史档案缺号时在此补录，录错可更正，但不允许清空。
    id_card_no: str | None = Field(default=None, max_length=32)
    # 团组织推优资格：仅补录 / 更正，不提供清空；缺项时推优接口会拒绝登记。
    birth_date: date | None = None
    league_joined_on: date | None = None
    batch_no: str | None = Field(default=None, max_length=20)
    year: int | None = Field(default=None, ge=2000, le=2100)
    is_active: bool | None = None
    reason: Reason

    @field_validator("birth_date", "league_joined_on")
    @classmethod
    def dates_not_in_future(cls, value: date | None) -> date | None:
        if value and value > date.today():
            raise ValueError("出生年月和入团时间不能晚于今天")
        return value

    @model_validator(mode="after")
    def league_after_birth(self) -> "ProfileUpdate":
        if self.birth_date and self.league_joined_on and self.league_joined_on < self.birth_date:
            raise ValueError("入团时间不能早于出生年月")
        return self

    @field_validator("id_card_no")
    @classmethod
    def check_id_card(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().upper()
        if not text:
            raise ValueError("身份证号不能留空；如为更正，请填写新的 18 位号码")
        if not re.fullmatch(r"\d{17}[\dX]", text):
            raise ValueError("身份证号须为 18 位，末位可为 X")
        return text


class MaterialCreate(MemberInput):
    material_type: Label
    file_version: str = Field(default="", max_length=100)
    # 材料落款日期与组织收到日期分开；入党申请书必须填写，用于 18 周岁与满 6 个月核算。
    document_date: date | None = None
    submit_date: date | None = None
    stage: str | None = Field(default=None, max_length=20)
    reason: Reason

    @field_validator("document_date", "submit_date")
    @classmethod
    def material_dates_not_in_future(cls, value: date | None) -> date | None:
        if value and value > date.today():
            raise ValueError("材料落款日期和组织收到日期不能晚于今天")
        return value

    @model_validator(mode="after")
    def application_date_required(self) -> "MaterialCreate":
        if self.material_type == "入党申请书" and self.document_date is None:
            raise ValueError("入党申请书须填写落款日期，用于核验申请时年满18周岁和申请满6个月")
        return self


class PoliticalReviewCreate(MemberInput):
    """登记组织形成的政审结论；原始政审材料仍走材料归档与涉密级出口。"""

    status: Literal["in_progress", "passed", "failed"]
    reviewed_on: date
    scope: Label
    conclusion: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=2000)
    material_id: str | None = Field(default=None, max_length=36)
    reason: Reason

    @field_validator("reviewed_on")
    @classmethod
    def review_date_not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("政审日期不能晚于今天")
        return value

    @model_validator(mode="after")
    def conclusion_required_for_decision(self) -> "PoliticalReviewCreate":
        if self.status in {"passed", "failed"} and not self.conclusion.strip():
            raise ValueError("作出政审结论时须填写结论内容")
        return self


class TrainingCreate(MemberInput):
    """登记集中培训事实；是否计入发展程序仍由组织人员核验原件后确认。"""

    training_type: Literal["centralized"] = "centralized"
    start_on: date
    end_on: date
    days: int | None = Field(default=None, ge=0, le=365)
    hours: int | None = Field(default=None, ge=0, le=2000)
    issuer: str = Field(default="", max_length=200)
    certificate_material_id: str | None = Field(default=None, max_length=36)
    note: str = Field(default="", max_length=2000)
    reason: Reason

    @model_validator(mode="after")
    def training_dates_and_amount(self) -> "TrainingCreate":
        if self.start_on > date.today() or self.end_on > date.today():
            raise ValueError("培训日期不能晚于今天")
        if self.end_on < self.start_on:
            raise ValueError("培训结束日期不能早于开始日期")
        if not (self.days or 0) and not (self.hours or 0):
            raise ValueError("请填写培训天数或学时，至少一项大于0")
        return self


class ProcedureCreate(MemberInput):
    """登记发展程序事实；具体字段按 kind 由服务层校验，不在此处替组织判断。"""

    kind: Literal[
        "contact",
        "introducer",
        "branch_committee_review",
        "upper_pre_review",
        "application_form",
        "upper_talk",
    ]
    occurred_on: date
    status: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=2000)
    reason: Reason
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_on")
    @classmethod
    def occurred_not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("程序日期不能晚于今天")
        return value


class MaterialReview(MemberInput):
    review_status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)
    # 历史材料补录落款日期：核验时一并写入，原状态先留基线，写入后再留审核快照。
    document_date: date | None = None
    reason: Reason

    @field_validator("document_date")
    @classmethod
    def review_date_not_in_future(cls, value: date | None) -> date | None:
        if value and value > date.today():
            raise ValueError("材料落款日期不能晚于今天")
        return value


class TransitionRequest(MemberInput):
    target_stage: Literal[
        "applicant", "activist", "candidate", "probationary", "member", "rejected"
    ]
    decision_date: date
    basis: str = Field(min_length=1, max_length=2000)
    opinion: str = Field(default="", max_length=2000)


class ReminderResolve(MemberInput):
    status: Literal["closed", "skipped"]
    note: str = Field(default="", max_length=500)


class CultivationCreate(MemberInput):
    profile_id: str = Field(min_length=1, max_length=36)
    category: Literal[
        "theory_test", "volunteer_service", "academic", "public_review", "party_review", "other"
    ]
    score: float | None = Field(default=None, ge=0, le=100)
    period: str = Field(default="", max_length=40)
    source_note: str = Field(default="", max_length=500)
    is_risk: bool = False
    risk_note: str = Field(default="", max_length=500)


class VoteBatch(MemberInput):
    batch_no: str = Field(min_length=1, max_length=20)
    round_no: int = Field(ge=1, le=20)
    votes: list["VoteEntry"] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_profiles(self) -> "VoteBatch":
        ids = [entry.profile_id for entry in self.votes]
        if len(ids) != len(set(ids)):
            raise ValueError("同一轮次对同一人员不能重复投票")
        return self


class VoteEntry(MemberInput):
    profile_id: str = Field(min_length=1, max_length=36)
    vote: Literal["agree", "disagree", "abstain"]
    comment: str = Field(default="", max_length=500)


class ScoringRequest(MemberInput):
    profile_id: str = Field(min_length=1, max_length=36)
    year: int | None = Field(default=None, ge=2000, le=2100)


class ArchiveCheckRun(MemberInput):
    profile_id: str = Field(min_length=1, max_length=36)
    materials_note: dict[str, str] = Field(default_factory=dict, max_length=300)
