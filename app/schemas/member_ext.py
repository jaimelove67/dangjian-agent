"""发展党员全流程输入契约；阶段结论、审核状态与租户不能由请求伪造。"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    batch_no: str | None = Field(default=None, max_length=20)
    year: int | None = Field(default=None, ge=2000, le=2100)
    is_active: bool | None = None
    reason: Reason


class MaterialCreate(MemberInput):
    material_type: Label
    file_version: str = Field(default="", max_length=100)
    submit_date: date | None = None
    stage: str | None = Field(default=None, max_length=20)
    reason: Reason


class MaterialReview(MemberInput):
    review_status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)
    reason: Reason


class TransitionRequest(MemberInput):
    target_stage: Literal["applicant", "activist", "candidate", "probationary", "member", "rejected"]
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
