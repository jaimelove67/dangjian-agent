"""Server-graded examinations and elapsed-time bounded video progress."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from app.schemas.school_business import Input


class Question(Input):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,30}$")
    text: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=8)
    correct_index: int = Field(ge=0, le=7)

    @model_validator(mode="after")
    def valid_answer(self) -> Question:
        if self.correct_index >= len(self.options) or any(
            not o or len(o) > 1000 for o in self.options
        ):
            raise ValueError("题目选项或标准答案无效")
        return self


class CourseCreate(Input):
    org_unit_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    video_url: HttpUrl | None = None
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    questions: list[Question] = Field(default_factory=list, max_length=100)
    passing_score: int = Field(default=60, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    points: int = Field(default=1, ge=0, le=1000)

    @model_validator(mode="after")
    def coherent(self) -> CourseCreate:
        if not self.video_url and not self.questions:
            raise ValueError("课程至少包含视频或考试")
        if self.video_url and (
            self.duration_seconds < 1 or self.video_url.username or self.video_url.password
        ):
            raise ValueError("视频必须设置真实时长，链接不得包含账号密码")
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("题目编号不能重复")
        return self


class EventCreate(Input):
    org_unit_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    starts_at: datetime
    registration_deadline: datetime
    location: str = Field(min_length=1, max_length=300)
    capacity: int = Field(ge=1, le=10000)
    points: int = Field(default=1, ge=0, le=1000)

    @model_validator(mode="after")
    def dates(self) -> EventCreate:
        if self.starts_at.tzinfo is None or self.registration_deadline.tzinfo is None:
            raise ValueError("活动时间必须包含时区")
        if self.registration_deadline > self.starts_at:
            raise ValueError("报名截止不能晚于活动开始")
        return self


class OfferingAction(Input):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class Heartbeat(Input):
    position_seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)


class ExamSubmit(Input):
    answers: dict[str, int] = Field(min_length=1, max_length=100)


class Attendance(Input):
    user_id: str = Field(min_length=1, max_length=36)
    attended: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)
