"""上级党组织审批 / 备案报送输入契约（T-MEM-11）；事项、类别与材料清单不能由请求伪造。

这张表只登记两个事实：**支部已把材料报送出去**，以及**上级批复结果是什么**。因此请求里
没有任何"批准"字段——事项（``item``）决定它属于备案还是审批、对应哪一条依据、随报哪些材料，
全部由服务层单源给出；调用方只能选事项、填报送与批复的事实要素。

回填批复的校验是这一层的重点：**没有文号的"同意 / 不同意"不是批复**（``agreed`` /
``rejected`` 必须给 ``reply_no``），**"需补充材料"必须写清缺什么**（``supplement`` 必须给
``decide_note``）——否则回填就变成走过场，"已回填"也就不再可信。
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Reason = Annotated[str, Field(min_length=1, max_length=2000)]
OrgName = Annotated[str, Field(min_length=1, max_length=200)]
UpperItem = Literal[
    "activist_record",
    "candidate_record",
    "probationary_approval",
    "member_approval",
]
UpperResult = Literal["agreed", "rejected", "supplement"]


class UpperReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UpperReportCreate(UpperReportInput):
    """登记一次向上级党组织的报送：事项由服务层映射依据与材料清单。"""

    profile_id: str = Field(min_length=1, max_length=36)
    item: UpperItem
    upper_org: OrgName
    # 报送文号可留空：多数支部报送的报告未必有文号，有则填以便对账；批复文号不能省。
    letter_no: str = Field(default="", max_length=64)
    submitted_on: date
    note: str = Field(default="", max_length=2000)
    reason: Reason

    @model_validator(mode="after")
    def not_future(self) -> "UpperReportCreate":
        if self.submitted_on > date.today():
            raise ValueError("报送日期不能晚于今天")
        return self


class UpperReportSettle(UpperReportInput):
    """回填上级党组织的批复结果；结果只能是同意 / 不同意 / 需补充材料。"""

    result: UpperResult
    decided_on: date | None = None
    reply_no: str = Field(default="", max_length=64)
    decide_note: str = Field(default="", max_length=2000)
    reason: Reason

    @model_validator(mode="after")
    def check_result(self) -> "UpperReportSettle":
        if self.decided_on is not None and self.decided_on > date.today():
            raise ValueError("批复日期不能晚于今天")
        if self.result in ("agreed", "rejected") and not self.reply_no:
            raise ValueError("回填「同意」或「不同意」必须填写上级批复文号：没有文号的结论无法对账")
        if self.result == "supplement" and not self.decide_note:
            raise ValueError("回填「需补充材料」必须写清还缺什么材料")
        return self


class UpperReportRevoke(UpperReportInput):
    """报送报错 / 重复报送时作废本次报送；记录不删除，理由必填。"""

    reason: Reason
