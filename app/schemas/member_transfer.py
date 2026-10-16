"""组织关系接转输入契约；方向、状态、租户与派生结论不能由请求伪造。

介绍信要素（编号 / 开具日期 / 有效期至）与对方组织名称是接转的关键事实：缺了编号，
介绍信无法追溯；缺了对方组织，就说不清关系转到了哪里。接收单位联系人与电话**不采集**：
那是第三人信息，接转只需要组织名称与介绍信要素，落库越少越好。

转入要么关联名册里已有的档案（同一学校内支部之间调动），要么登记必要的三项信息
（姓名、阶段、进入阶段日期）新建一份档案；不能同时既关联又新建——那样会凭空多出一
份同人档案。
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Reason = Annotated[str, Field(min_length=1, max_length=2000)]
OrgName = Annotated[str, Field(min_length=1, max_length=200)]
LetterNo = Annotated[str, Field(min_length=1, max_length=64)]
TransferStage = Literal["probationary", "member"]


class TransferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TransferCreate(TransferInput):
    """登记一次接转：转出沿用名册档案；转入可关联既有档案或新建档案。"""

    direction: Literal["in", "out"]
    profile_id: str | None = Field(default=None, min_length=1, max_length=36)
    # 转入且名册中没有此人时，按登记培养对象的同一套必填项建档
    name: str | None = Field(default=None, min_length=1, max_length=50)
    # 转入填接收组织；转出忽略（转出的组织由名册档案决定，不接受客户端指定）
    org_unit_id: str | None = Field(default=None, min_length=1, max_length=36)
    current_stage: TransferStage | None = None
    stage_joined_on: date | None = None
    counterpart_org: OrgName
    letter_no: LetterNo
    issued_on: date
    valid_until: date | None = None
    note: str = Field(default="", max_length=2000)
    reason: Reason

    @model_validator(mode="after")
    def check_target(self) -> "TransferCreate":
        if self.issued_on > date.today():
            raise ValueError("介绍信开具日期不能晚于今天")
        if self.valid_until is not None and self.valid_until < self.issued_on:
            raise ValueError("介绍信有效期不能早于开具日期")
        if self.direction == "out":
            if not self.profile_id:
                raise ValueError("转出必须指定名册中的党员")
            if self.name or self.current_stage or self.stage_joined_on:
                raise ValueError("转出沿用名册档案，不重复登记姓名、阶段与进入阶段日期")
        else:
            if not self.org_unit_id:
                raise ValueError("转入必须指定接收组织")
            if self.profile_id and self.name:
                raise ValueError("转入要么关联既有档案、要么新建档案，不能同时登记姓名")
            if not self.profile_id and not (
                self.name and self.current_stage and self.stage_joined_on
            ):
                raise ValueError("转入需关联既有档案，或登记姓名、阶段与进入阶段日期")
        return self


class TransferSettle(TransferInput):
    """转出回执 / 转入档案核对完成；日期不填按今天记。"""

    settled_on: date | None = None
    receipt_no: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=2000)
    reason: Reason

    @model_validator(mode="after")
    def not_future(self) -> "TransferSettle":
        if self.settled_on is not None and self.settled_on > date.today():
            raise ValueError("回执日期不能晚于今天")
        return self


class TransferRevoke(TransferInput):
    """介绍信开错或重新开具时作废本次接转；记录不删除，理由必填。"""

    reason: Reason
