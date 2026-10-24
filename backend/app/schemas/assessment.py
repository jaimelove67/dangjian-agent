"""年度考核的受限配置与人工操作契约；拒绝客户端租户和审核人字段。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

SourceName = Literal[
    "organizations", "members", "member_materials", "meetings", "studies", "documents", "manual"
]
ReviewStatus = Literal["pending", "approved", "returned"]


class AssessmentInput(BaseModel):
    """所有写入拒绝未知字段；字符串先去除首尾空白。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnnualScope(AssessmentInput):
    org_unit_id: str = Field(min_length=1, max_length=36)
    year: int = Field(ge=2000, le=2100)


class SourceOptions(AssessmentInput):
    measure: Literal["count", "attendance_rate", "material_rate", "sum"] = "count"
    stages: list[Literal["applicant", "activist", "candidate", "probationary", "formal"]] = Field(
        default_factory=list, max_length=5
    )
    org_types: list[Literal["school", "department", "branch"]] = Field(
        default_factory=list, max_length=3
    )
    required_materials: list[str] = Field(default_factory=list, max_length=50)
    document_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("required_materials", "document_ids")
    @classmethod
    def validate_names(cls, value: list[str]) -> list[str]:
        """清单去重且不接受空项。"""
        if any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("清单项目不能为空或超过100字")
        return sorted({item.strip() for item in value})


class IndicatorCreate(AnnualScope):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=4000)
    formula: Literal["count", "percentage", "sum"] = "count"
    source: SourceName
    source_options: SourceOptions = Field(default_factory=SourceOptions)
    target: FiniteFloat = Field(ge=0, le=1e12)
    comparison: Literal["gte", "lte", "eq"] = "gte"
    unit: str = Field(default="项", min_length=1, max_length=20)
    period_start: date
    period_end: date
    effective_from: datetime | None = None
    required_evidence: list[str] = Field(default_factory=list, max_length=50)
    confirmed: bool = False
    confirmation_note: str = Field(default="", max_length=2000)
    expected_version: int = Field(default=0, ge=0)

    @field_validator("required_evidence")
    @classmethod
    def evidence_names(cls, value: list[str]) -> list[str]:
        return SourceOptions.validate_names(value)

    @model_validator(mode="after")
    def validate_rule(self) -> "IndicatorCreate":
        """只允许已定义的计算口径，禁止执行自由文本公式。"""
        if self.period_start.year != self.year or self.period_end.year != self.year:
            raise ValueError("统计期间必须属于所选年度")
        if self.period_start > self.period_end:
            raise ValueError("统计开始日期不得晚于结束日期")
        measures = {
            "count": {"count"},
            "percentage": {"attendance_rate", "material_rate"},
            "sum": {"sum"},
        }
        if self.source_options.measure not in measures[self.formula]:
            raise ValueError("公式与数据源统计口径不匹配")
        if self.source == "manual" and self.formula != "sum":
            raise ValueError("人工特色项使用有依据的求和口径")
        if self.formula == "sum" and self.source != "manual":
            raise ValueError("求和只用于人工特色项")
        if self.source_options.measure == "attendance_rate" and self.source not in {
            "meetings",
            "studies",
        }:
            raise ValueError("参学/参会率仅用于会议或学习数据")
        if self.source_options.measure == "material_rate" and self.source not in {
            "member_materials",
            "meetings",
            "studies",
        }:
            raise ValueError("材料完整率的数据源不匹配")
        if self.source == "member_materials" and self.source_options.measure != "material_rate":
            raise ValueError("人员材料使用材料完整率口径")
        if self.confirmed and not self.confirmation_note:
            raise ValueError("确认学校指标须填写确认依据")
        return self


class TaskCreate(AnnualScope):
    indicator_code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=36)
    due_date: date
    declared_progress: int = Field(default=0, ge=0, le=100)
    manual_value: FiniteFloat | None = Field(default=None, ge=0, le=1e12)
    completed_on: date | None = None
    basis: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_task(self) -> "TaskCreate":
        if self.due_date.year != self.year:
            raise ValueError("任务期限必须属于所选年度")
        if self.manual_value is not None and not self.basis:
            raise ValueError("人工数值必须有录入依据")
        if self.manual_value is not None and self.completed_on is None:
            raise ValueError("人工数值必须登记实际完成日期")
        if self.completed_on and (
            self.completed_on.year != self.year or self.completed_on > date.today()
        ):
            raise ValueError("实际完成日期须在任务年度且不得晚于今天")
        return self


class TaskUpdate(TaskCreate):
    expected_revision: int = Field(ge=1)


class ReviewRequest(AssessmentInput):
    status: Literal["approved", "returned"]
    opinion: str = Field(min_length=1, max_length=2000)
    expected_revision: int = Field(ge=1)


class EvidenceCreate(AnnualScope):
    indicator_code: str = Field(min_length=1, max_length=64)
    requirement_key: str = Field(min_length=1, max_length=100)
    doc_id: str = Field(min_length=1, max_length=100)


class PlanCreate(AssessmentInput):
    run_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(default=0, ge=0)
    content: str | None = Field(default=None, min_length=1, max_length=30000)


class PolicyUpdate(AssessmentInput):
    org_unit_id: str = Field(min_length=1, max_length=36)
    archive_enabled: bool = False
    reminder_advance_days: int = Field(default=14, ge=0, le=90)
    confirmation_note: str = Field(default="", max_length=2000)
    expected_version: int = Field(default=0, ge=0)
    expected_archive_version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_confirmation(self) -> "PolicyUpdate":
        if self.archive_enabled and not self.confirmation_note:
            raise ValueError("启用电子归档须填写学校确认依据")
        return self


class ReminderHandle(AssessmentInput):
    note: str = Field(min_length=1, max_length=2000)


class IndicatorResult(BaseModel):
    """每个数字附可授权钻取的来源；未知值使用 null，不默认零。"""

    code: str
    name: str
    rule_id: str
    rule_version: int
    requirement: str
    formula: str
    source: str
    target: float
    actual: float | None
    satisfied: bool | None
    unit: str
    period_start: str
    period_end: str
    sources: list[dict]
    evidence: list[dict]
    missing: list[str]


class AssessmentWorkspace(BaseModel):
    """工作台的统一统计、状态、版本与权限范围。"""

    org_unit_id: str
    org_name: str
    school_org_id: str
    year: int
    as_of: str
    fingerprint: str
    engine_version: str
    indicators: list[dict]
    results: list[IndicatorResult]
    tasks: list[dict]
    evidence: list[dict]
    owners: list[dict]
    runs: list[dict]
    plan: dict | None
    policy: dict
    reminders: list[dict]
    needs_recalculation: bool
    notices: list[str]
