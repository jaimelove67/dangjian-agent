"""中心组学习输入契约；租户、审核结论、来源内容均不能由创建请求伪造。"""

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

Label = Annotated[str, Field(min_length=1, max_length=300)]
DocId = Annotated[str, Field(min_length=1, max_length=100)]
PersonName = Annotated[str, Field(min_length=1, max_length=100)]


class StudyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RevisionRequest(StudyInput):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class ItemFields(StudyInput):
    topic: Label
    scheduled_on: date
    responsible: PersonName
    source_doc_ids: list[DocId] = Field(default_factory=list, max_length=20)

    @field_validator("source_doc_ids")
    @classmethod
    def unique_sources(cls, values: list[str]) -> list[str]:
        """保留来源顺序，同一资料只登记一次。"""
        return list(dict.fromkeys(values))


class PlanCreate(StudyInput):
    org_unit_id: str = Field(min_length=1, max_length=36)
    year: int = Field(ge=2000, le=2100)
    title: Label
    priorities: list[Label] = Field(min_length=1, max_length=12)
    responsible: PersonName
    source_doc_ids: list[DocId] = Field(default_factory=list, max_length=20)
    items: list[ItemFields] = Field(default_factory=list, max_length=60)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def check_dates(self) -> "PlanCreate":
        """计划条目属于计划年度；实际活动日期允许跨年。"""
        if any(item.scheduled_on.year != self.year for item in self.items):
            raise ValueError("计划安排日期必须在计划年度内")
        return self


class PlanUpdate(RevisionRequest):
    title: Label
    priorities: list[Label] = Field(min_length=1, max_length=12)
    responsible: PersonName
    source_doc_ids: list[DocId] = Field(default_factory=list, max_length=20)


class ItemUpdate(ItemFields, RevisionRequest):
    agenda: str = Field(default="", max_length=20000)
    outline: str = Field(default="", max_length=20000)


class ItemCreate(ItemFields, RevisionRequest):
    pass


class ReviewRequest(RevisionRequest):
    decision: Literal["approved", "rejected"]


class Participant(StudyInput):
    participant_id: str = Field(min_length=1, max_length=100)
    name: PersonName
    attended: StrictBool


class EvidenceNote(StudyInput):
    text: str = Field(min_length=1, max_length=5000)
    quote: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=5000
    )
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class MinutesInput(StudyInput):
    learning_points: list[EvidenceNote] = Field(default_factory=list, max_length=60)
    consensus: list[EvidenceNote] = Field(default_factory=list, max_length=60)
    requirements: list[EvidenceNote] = Field(default_factory=list, max_length=60)


class ActivityUpdate(RevisionRequest):
    held_on: date | None = None
    host: str = Field(default="", max_length=100)
    participants: list[Participant] = Field(default_factory=list, max_length=500)
    transcript: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        default="", max_length=200000
    )
    source_doc_ids: list[DocId] | None = Field(default=None, max_length=20)
    minutes: MinutesInput | None = None

    @model_validator(mode="after")
    def check_attendance(self) -> "ActivityUpdate":
        """去重依赖稳定人员编号；实际召开不能登记未来日期。"""
        ids = [person.participant_id for person in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("参学人员编号不能重复")
        if self.held_on and self.held_on > date.today():
            raise ValueError("实际学习日期不能晚于今天")
        return self


class ArchivePolicyUpdate(StudyInput):
    enabled: StrictBool
    expected_revision: int = Field(ge=0)
    evidence: str = Field(min_length=1, max_length=2000)
