"""选优结论与团组织推优输入契约（`T-MEM-13`、`T-MEM-06`）。

结论、拟推荐名单快照、审核状态、证据快照、密级与租户都**不能由请求伪造**：请求只能给
"拟推进阶段 + 拟推荐人 + 依据 + 研究程序"，其余由服务层按授权范围与规则生成。
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Annotated[str, Field(min_length=1, max_length=200)]
Reason = Annotated[str, Field(min_length=1, max_length=2000)]
Text = Annotated[str, Field(max_length=5000)]


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SelectionCreate(SelectionInput):
    """登记一份拟推荐名单（草稿）：系统不替人产生结论，名单与依据必须由人给出。"""

    batch_no: str = Field(min_length=1, max_length=20)
    round_no: int = Field(ge=1, le=20)
    # 拟推进到的阶段；只允许向前（服务层按阶段顺序核对）
    target_stage: Literal["activist", "candidate", "probationary", "member"]
    candidate_ids: list[str] = Field(min_length=1, max_length=200)
    # 结论依据：必须写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录
    basis: str = Field(min_length=1, max_length=2000)
    research_on: date
    # 研究程序：支委会 / 党员大会（细则要求"经支委会或党员大会研究确定"）
    research_method: Literal["committee", "member_meeting"]
    reason: Reason

    @model_validator(mode="after")
    def unique_candidates(self) -> "SelectionCreate":
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("同一份结论里同一人员只能出现一次")
        return self


class SelectionUpdate(SelectionInput):
    """修订结论：改后回到草稿，必须重新送审（旧版本留在修订记录里）。"""

    expected_revision: int = Field(ge=1)
    target_stage: Literal["activist", "candidate", "probationary", "member"] | None = None
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=200)
    basis: str | None = Field(default=None, max_length=2000)
    research_on: date | None = None
    research_method: Literal["committee", "member_meeting"] | None = None
    reason: Reason

    @model_validator(mode="after")
    def unique_candidates(self) -> "SelectionUpdate":
        if self.candidate_ids is not None and len(self.candidate_ids) != len(
            set(self.candidate_ids)
        ):
            raise ValueError("同一份结论里同一人员只能出现一次")
        return self


class SelectionSubmit(SelectionInput):
    """送审：必填项缺一项都不放行；送审人不得审核自己的版本。"""

    expected_revision: int = Field(ge=1)
    reason: Reason


class SelectionDecision(SelectionInput):
    """人工审核：只有审核通过（``approved``）才是生效结论。"""

    expected_revision: int = Field(ge=1)
    decision: Literal["approved", "rejected"]
    reason: Reason


class LeagueRecommendationCreate(SelectionInput):
    """登记团组织推优：推荐团组织与推荐日期由人填写，系统不判断年龄。"""

    profile_id: str = Field(min_length=1, max_length=36)
    league_org: Label
    recommended_on: date
    note: Text = ""
    reason: Reason


class LeagueRecommendationRevoke(SelectionInput):
    """作废一条推优记录（录错 / 未办成）：记录保留、理由必填。"""

    reason: Reason
