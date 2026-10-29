"""School operations only accept business fields, never actor/tenant/status claims."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.user import UserRole


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoticeCreate(Input):
    org_unit_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    category: Literal["notice", "publicity"] = "notice"
    starts_on: date | None = None
    expires_on: date | None = None
    doc_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def publication_dates(self) -> "NoticeCreate":
        if self.category == "publicity" and (self.starts_on is None or self.expires_on is None):
            raise ValueError("公示须填写开始和截止日期")
        if self.starts_on and self.expires_on and self.starts_on > self.expires_on:
            raise ValueError("开始日期不能晚于截止日期")
        return self


class TaskCreate(Input):
    org_unit_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    category: Literal["learning", "development", "life", "assessment", "other"]
    due_date: date
    requirements: str = Field(min_length=1, max_length=4000)
    assignee_id: str = Field(min_length=1, max_length=36)
    evidence_required: bool = True


class PermissionCreate(Input):
    user_id: str = Field(min_length=1, max_length=36)
    role: UserRole
    org_unit_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=5, max_length=2000)


class Action(Input):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class Complete(Action):
    report: str = Field(min_length=1, max_length=10000)
    doc_ids: list[str] = Field(default_factory=list, max_length=30)
    material_ids: list[str] = Field(default_factory=list, max_length=30)


class Review(Action):
    decision: Literal["approved", "rejected"]


class Rules(Input):
    expected_revision: int = Field(ge=0)
    year: int = Field(ge=2000, le=2100)
    review_days: int = Field(ge=1, le=60)
    reminder_days: int = Field(ge=0, le=60)
    development_materials: str = Field(min_length=1, max_length=2000)
    archive_requirements: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)
