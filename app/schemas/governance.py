"""管理员输入：不接受客户端提交审核快照或服务端权限结论。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserRole


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TenantCreate(StrictInput):
    name: str = Field(min_length=1, max_length=100)
    tenant_type: Literal["school", "department", "branch"] = "school"
    parent_id: str = Field(min_length=1, max_length=36)


class TenantUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None


class OrgCreate(StrictInput):
    name: str = Field(min_length=1, max_length=100)
    org_type: Literal["school", "department", "branch"]
    parent_id: str | None = Field(None, max_length=36)


class OrgUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=100)
    parent_id: str | None = Field(None, max_length=36)
    is_active: bool | None = None


class UserCreate(StrictInput):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.@-]+$")
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=12, max_length=72, repr=False)
    role: UserRole = UserRole.MEMBER
    org_unit_id: str | None = Field(None, max_length=36)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码 UTF-8 编码不能超过 72 字节")
        return value


class UserUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=50)
    role: UserRole | None = None
    org_unit_id: str | None = Field(None, max_length=36)
    is_active: bool | None = None


class ReviewSubmit(StrictInput):
    source_kind: Literal[
        "score",
        "vote",
        "meeting",
        "member_review",
        "study_activity",
        "study_plan",
        "assessment_report",
        "assessment_plan",
    ]
    source_id: str = Field(min_length=1, max_length=200)
    year: int = Field(default=2026, ge=2000, le=2100)
    round: int = Field(default=1, ge=1, le=100)


class ReviewDecision(StrictInput):
    decision: Literal["approved", "returned"]
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    opinion: str = Field(min_length=1, max_length=2000)


JobKind = Literal["member_reminders", "assessment_reminders", "embedding"]


class JobCreate(StrictInput):
    kind: JobKind
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    dedup_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.-]+$")
