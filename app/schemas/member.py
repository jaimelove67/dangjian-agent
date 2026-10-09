"""党员发展（资格校验 / 流转建议 / 待办）出入参

统一强调决策边界：本模块的输出均为**建议与提示**，不构成组织认定，
阶段流转只能由具备权限的组织人员通过人工接口依规操作。
"""
from __future__ import annotations

from typing import List, Optional

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
