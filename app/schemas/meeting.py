"""组织生活（三会一课）输入契约；租户、审核结论与来源内容不能由创建请求伪造。"""

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Label = Annotated[str, Field(min_length=1, max_length=300)]
DocId = Annotated[str, Field(min_length=1, max_length=100)]
PersonName = Annotated[str, Field(min_length=1, max_length=100)]

ACTIVITY_TYPE_OPTIONS = Literal[
    "branch_member_meeting",  # 支部大会
    "branch_committee_meeting",  # 支委会
    "party_group_meeting",  # 党小组会
    "party_lecture",  # 党课
    "other",  # 其他组织生活
]


class MeetingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RevisionRequest(MeetingInput):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class Participant(MeetingInput):
    participant_id: str = Field(min_length=1, max_length=100)
    name: PersonName
    attended: bool = True


class EvidenceNote(MeetingInput):
    text: str = Field(min_length=1, max_length=5000)
    quote: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=5000
    )
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class MinutesInput(MeetingInput):
    learning_points: list[EvidenceNote] = Field(default_factory=list, max_length=60)
    consensus: list[EvidenceNote] = Field(default_factory=list, max_length=60)
    requirements: list[EvidenceNote] = Field(default_factory=list, max_length=60)


class ActivityCreate(MeetingInput):
    org_unit_id: str = Field(min_length=1, max_length=36)
    activity_type: ACTIVITY_TYPE_OPTIONS
    title: Label
    scheduled_on: date
    host: str = Field(default="", max_length=100)
    participants: list[Participant] = Field(default_factory=list, max_length=500)
    source_doc_ids: list[DocId] = Field(default_factory=list, max_length=20)
    agenda: str = Field(default="", max_length=20000)
    notice: str = Field(default="", max_length=20000)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("source_doc_ids")
    @classmethod
    def unique_sources(cls, values: list[str]) -> list[str]:
        """保留顺序，同一资料只登记一次。"""
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def check_participants(self) -> "ActivityCreate":
        ids = [person.participant_id for person in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("参会人员编号不能重复")
        return self


class ActivityUpdate(RevisionRequest):
    scheduled_on: date | None = None
    held_on: date | None = None
    host: str | None = Field(default=None, max_length=100)
    topic: Label | None = None
    participants: list[Participant] | None = Field(default=None, max_length=500)
    transcript: Annotated[str, StringConstraints(strip_whitespace=False)] | None = Field(
        default=None, max_length=200000
    )
    source_doc_ids: list[DocId] | None = Field(default=None, max_length=20)
    minutes: MinutesInput | None = None
    agenda: str | None = Field(default=None, max_length=20000)
    notice: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def check_attendance(self) -> "ActivityUpdate":
        if self.participants is not None:
            ids = [person.participant_id for person in self.participants]
            if len(ids) != len(set(ids)):
                raise ValueError("参会人员编号不能重复")
        if self.held_on and self.held_on > date.today():
            raise ValueError("实际召开日期不能晚于今天")
        return self


class ReviewRequest(RevisionRequest):
    decision: Literal["approved", "rejected"]


class TaskCreate(MeetingInput):
    """原文摘录任务；责任人或期限缺省时标记为待人工补齐。"""

    task_text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=2000
    )
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=1)
    owner_name: str = Field(default="", max_length=100)
    due_on: date | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def check_bounds(self) -> "TaskCreate":
        if self.source_start >= self.source_end:
            raise ValueError("摘录起点必须小于终点")
        return self


class TaskUpdate(MeetingInput):
    """人工补齐责任人与期限后确认任务进入台账。"""

    owner_name: str = Field(default="", max_length=100)
    due_on: date | None = None
    reason: str = Field(min_length=1, max_length=2000)


class TaskHandle(MeetingInput):
    status: Literal["done", "cancelled"]
    handle_note: str = Field(default="", max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
