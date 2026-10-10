"""党员发展（资格校验 / 流转建议 / 待办）出入参

统一强调决策边界：本模块的输出均为**建议与提示**，不构成组织认定，
阶段流转只能由具备权限的组织人员通过人工接口依规操作。
"""
from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field

DECISION_BOUNDARY_NOTE = (
    "阶段流转仅可通过人工接口，由具备权限的组织人员依规操作；"
    "本结果不构成任何组织认定或选拔结论。"
)


class QualificationCheckRequest(BaseModel):
    """资格校验请求"""
    current_stage: str = Field(..., description="当前阶段（applicant/activist/candidate/probationary/member/rejected）")
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
    """培养对象名册条目"""
    id: str
    name: str
    org_name: str
    stage: str = Field(..., description="当前阶段（applicant/activist/candidate/probationary/member）")
    stage_joined_on: date
    days_in_stage: int = Field(..., description="进入当前阶段的天数（按日期实时计算）")
    materials: List[str] = Field(default_factory=list)
    pending: int = 0

    @classmethod
    def from_profile(
        cls, profile: Any, today: Optional[date] = None
    ) -> "MemberRosterItem":
        """从 ORM 模型构造名册条目（在阶段天数实时计算）"""
        today = today or date.today()
        joined = profile.stage_joined_on
        days = max(0, (today - joined).days) if joined else 0
        return cls(
            id=str(profile.id),
            name=profile.name,
            org_name=profile.org_name,
            stage=profile.current_stage,
            stage_joined_on=joined,
            days_in_stage=days,
            materials=list(profile.materials or []),
            pending=profile.pending or 0,
        )


class MemberRosterResponse(BaseModel):
    """培养对象名册响应"""
    total: int = 0
    items: List[MemberRosterItem] = Field(default_factory=list)


class MemberCreateRequest(BaseModel):
    """新增培养对象请求"""
    name: str = Field(..., min_length=1, max_length=50, description="姓名")
    org_name: str = Field(..., min_length=1, max_length=200, description="组织全名")
    current_stage: str = Field(
        "applicant",
        description="起始阶段（applicant/activist/candidate/probationary/member）",
    )
    stage_joined_on: Optional[date] = Field(
        None, description="进入当前阶段日期，缺省为今天"
    )
    materials: List[str] = Field(default_factory=list, description="已具备材料名称")
    pending: int = Field(0, ge=0, description="待办数")
    org_unit_id: Optional[str] = Field(None, description="组织单元 ID（可选）")
