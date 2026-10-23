"""管理员输入：不接受客户端提交审核快照或服务端权限结论。"""

from datetime import date
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


class OrgLeaderFields(BaseModel):
    """组织负责人与联系电话。

    治理页需要能按组织登记"谁是负责人、打哪个电话"，用于联络与责任落实；
    姓名与职务分开存，换职务时不必改写姓名。三项**不参与权限判断**，留空表示尚未登记。
    """

    leader_name: str | None = Field(None, max_length=50, description="负责人姓名")
    leader_title: str | None = Field(None, max_length=50, description="负责人职务")
    leader_phone: str | None = Field(None, max_length=20, description="负责人联系电话")

    @field_validator("leader_name", "leader_title", "leader_phone")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        # 表单清空输入框会提交空串；统一归一为 None，库里不存空字符串。
        text = (value or "").strip()
        return text or None


class OrgCreate(StrictInput, OrgLeaderFields):
    name: str = Field(min_length=1, max_length=100)
    org_type: Literal["school", "department", "branch"]
    parent_id: str | None = Field(None, max_length=36)


class OrgUpdate(StrictInput, OrgLeaderFields):
    name: str | None = Field(None, min_length=1, max_length=100)
    parent_id: str | None = Field(None, max_length=36)
    is_active: bool | None = None


class OrgLeaderCreate(StrictInput):
    """登记一段任职：一条记录 = 一人在一个组织的一届任职。

    ``ended_on`` 允许一起填，用于补录已离任的前任；留空表示仍在任。
    """

    org_unit_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=50)
    phone: str | None = Field(None, max_length=20)
    started_on: date | None = None
    ended_on: date | None = None
    is_primary: bool = Field(False, description="是否该组织主要负责人（书记）")
    remark: str | None = Field(None, max_length=200)

    @field_validator("phone", "remark")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class OrgLeaderReplace(StrictInput):
    """一键换人：原主要负责人离任 + 新任一届，两个动作一次提交。

    现实中"书记调走了、新人接上"是一次人事变动，拆成两次提交会让组织在中间
    短暂显示"无负责人"。这里仍落两条任职记录（履历不合并），只是在一个事务里完成。
    """

    org_unit_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=50)
    phone: str | None = Field(None, max_length=20)
    started_on: date | None = Field(None, description="新负责人任职日期，默认今天")
    ended_on_prev: date | None = Field(None, description="原负责人离任日期，默认今天")
    remark: str | None = Field(None, max_length=200)

    @field_validator("phone", "remark")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class OrgLeaderUpdate(StrictInput):
    """修改任职或登记离任：离任只写 ended_on，记录保留为履历"""

    org_unit_id: str | None = Field(None, max_length=36)
    name: str | None = Field(None, min_length=1, max_length=50)
    title: str | None = Field(None, min_length=1, max_length=50)
    phone: str | None = Field(None, max_length=20)
    started_on: date | None = None
    ended_on: date | None = None
    is_primary: bool | None = None
    remark: str | None = Field(None, max_length=200)

    @field_validator("phone", "remark")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class UserCreate(StrictInput):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.@-]+$")
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=72, repr=False)
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
    # 管理员重置密码：留空表示不改；下限与 POST /admin/users 保持一致。
    password: str | None = Field(None, min_length=8, max_length=72, repr=False)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > 72:
            raise ValueError("密码 UTF-8 编码不能超过 72 字节")
        return value


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
