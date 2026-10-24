"""民主评议党员输入契约；等次、审核结论与租户不能由请求伪造。

等次用稳定英文键（``outstanding`` / ``qualified`` / ``basic`` / ``unqualified``），
中文说法只在界面与文案里出现一次，避免筛选、汇总与导出各写一套中文导致对不上。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Reason = Annotated[str, Field(min_length=1, max_length=2000)]
GradeOption = Literal["outstanding", "qualified", "basic", "unqualified"]
Text = Annotated[str, Field(max_length=5000)]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewTest(ReviewInput):
    """民主测评票数（不记名，只存汇总）。

    只记票数、不记谁投了谁：测评本来是不记名的，逐人明细既不符合制度，也会把
    "谁给谁投了不合格"摊在页面上（那是第三人信息）。
    """

    eligible: int = Field(default=0, ge=0, le=100000)
    attended: int = Field(default=0, ge=0, le=100000)
    outstanding: int = Field(default=0, ge=0, le=100000)
    qualified: int = Field(default=0, ge=0, le=100000)
    basic: int = Field(default=0, ge=0, le=100000)
    unqualified: int = Field(default=0, ge=0, le=100000)

    @model_validator(mode="after")
    def check_counts(self) -> "ReviewTest":
        if self.eligible and self.attended > self.eligible:
            raise ValueError("实际参加人数不能多于应参加人数")
        votes = self.outstanding + self.qualified + self.basic + self.unqualified
        if self.attended and votes > self.attended:
            raise ValueError("测评票数合计不能多于实际参加人数")
        return self


class ReviewProcedure(ReviewInput):
    """评议程序：个人自评、党员互评、民主测评、支部评定意见。"""

    self_assessment: Text = ""
    peer_review: Text = ""
    test: ReviewTest | None = None
    branch_opinion: Text = ""


class ReviewLaunch(ReviewInput):
    """按年度发起某支部的民主评议：为在册党员建立草稿，不覆盖已有记录。"""

    year: int = Field(ge=2000, le=2100)
    org_unit_id: str = Field(min_length=1, max_length=36)
    reason: Reason


class ReviewCreate(ReviewInput):
    year: int = Field(ge=2000, le=2100)
    profile_id: str = Field(min_length=1, max_length=36)
    procedure: ReviewProcedure = Field(default_factory=ReviewProcedure)
    grade: GradeOption | None = None
    basis: str = Field(default="", max_length=2000)
    rectification: str = Field(default="", max_length=2000)
    reason: Reason


class ReviewUpdate(ReviewInput):
    expected_revision: int = Field(ge=1)
    procedure: ReviewProcedure | None = None
    grade: GradeOption | None = None
    basis: str | None = Field(default=None, max_length=2000)
    rectification: str | None = Field(default=None, max_length=2000)
    reason: Reason


class ReviewSubmit(ReviewInput):
    expected_revision: int = Field(ge=1)
    reason: Reason


class ReviewDecision(ReviewInput):
    expected_revision: int = Field(ge=1)
    decision: Literal["approved", "rejected"]
    reason: Reason
