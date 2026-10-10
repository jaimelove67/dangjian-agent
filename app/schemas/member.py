"""党员发展（资格校验 / 流转建议 / 待办）出入参

统一强调决策边界：本模块的输出均为**建议与提示**，不构成组织认定，
阶段流转只能由具备权限的组织人员通过人工接口依规操作。
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.rules.member_stages import MemberStage

DECISION_BOUNDARY_NOTE = (
    "阶段流转仅可通过人工接口，由具备权限的组织人员依规操作；"
    "本结果不构成任何组织认定或选拔结论。"
)


class QualificationCheckRequest(BaseModel):
    """资格校验请求"""

    current_stage: str = Field(
        ..., description="当前阶段（applicant/activist/candidate/probationary/member/rejected）"
    )
    target_stage: str = Field(..., description="拟转入阶段")
    materials: List[str] = Field(default_factory=list, description="已提交材料名称")
    days_in_stage: int = Field(0, ge=0, description="在当前阶段已停留天数")


class QualificationResult(BaseModel):
    """资格校验结果"""

    eligible: bool
    blockers: List[str] = Field(default_factory=list, description="阻断项")
    missing_materials: List[str] = Field(default_factory=list)
    present_materials: List[str] = Field(default_factory=list)
    min_days: int = 0
    days_in_stage: int = 0


class TransitionSuggestionRequest(QualificationCheckRequest):
    """流转建议请求（与资格校验同参）"""


class TransitionSuggestion(BaseModel):
    """流转建议（不含阶段写入）"""

    current_stage: str
    suggested_target: Optional[str] = None
    eligible: bool = False
    procedures: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    note: str = DECISION_BOUNDARY_NOTE


class TodoSuggestionsRequest(BaseModel):
    """待办建议请求"""

    current_stage: str
    materials: List[str] = Field(default_factory=list)
    days_in_stage: int = Field(0, ge=0)


class TodoItem(BaseModel):
    """待办项"""

    category: str = Field(..., description="material / meeting / reminder")
    content: str


class TodoSuggestionsResponse(BaseModel):
    """待办建议（预留接口）"""

    todos: List[TodoItem] = Field(default_factory=list)
    note: str = DECISION_BOUNDARY_NOTE


class MemberRosterItem(BaseModel):
    id: str
    name: str
    org_name: str
    org_unit_id: Optional[str] = None
    stage: MemberStage
    stage_joined_on: date
    days_in_stage: int
    materials: List[str] = Field(default_factory=list)
    pending: int = 0

    @classmethod
    def from_profile(cls, profile: Any) -> "MemberRosterItem":
        return cls(
            id=str(profile.id),
            name=profile.name,
            org_name=profile.org_name,
            org_unit_id=profile.org_unit_id,
            stage=profile.current_stage,
            stage_joined_on=profile.stage_joined_on,
            days_in_stage=max(0, (date.today() - profile.stage_joined_on).days),
            materials=list(profile.materials or []),
            pending=profile.pending or 0,
        )


class MemberRosterResponse(BaseModel):
    total: int
    items: List[MemberRosterItem]
    page: int = 1
    page_size: int = 40


class MemberCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    org_unit_id: Optional[str] = Field(None, min_length=1, max_length=36)
    # 兼容协作者请求；真实组织名称始终由数据库中的组织单元生成。
    org_name: Optional[str] = Field(None, max_length=200)
    current_stage: MemberStage = MemberStage.APPLICANT
    stage_joined_on: Optional[date] = None
    materials: List[str] = Field(default_factory=list, max_length=50)
    pending: int = Field(0, ge=0, le=2147483647)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("stage_joined_on")
    @classmethod
    def not_in_future(cls, value: Optional[date]) -> Optional[date]:
        if value and value > date.today():
            raise ValueError("进入阶段日期不能晚于今天")
        return value

    @field_validator("materials")
    @classmethod
    def valid_materials(cls, values: List[str]) -> List[str]:
        if any(not value.strip() or len(value.strip()) > 200 for value in values):
            raise ValueError("材料名称应为 1 至 200 字")
        return list(dict.fromkeys(value.strip() for value in values))


class MemberOrgOption(BaseModel):
    id: str
    name: str
    org_type: str
