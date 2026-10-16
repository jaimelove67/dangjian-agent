"""WF-03（引用核验）/ WF-04（敏感检查）的标准接口契约（T-WF02-13）。

框架 3.4 / 6.3 要求这两个环节后续能被拆成独立工作流：拆分的前提是**契约先固定**。
这里只定义可序列化的出入参（不出现链路内部对象）并给出版本号，调用方只依赖契约与
版本；实现（内联函数 → 独立工作流 → 独立服务）可以替换而不影响调用方。

契约稳定性：出参字段只增不改、语义不变；不兼容调整必须升版本号，并同步调用方与测试。
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.qa import Citation

#: 工作流编号与接口版本（契约变更时才升版本）
WF03_WORKFLOW = "WF-03"
WF04_WORKFLOW = "WF-04"
WF03_VERSION = "wf-03/1"
WF04_VERSION = "wf-04/1"


class CitationInput(BaseModel):
    """被引片段（WF-03 入参；与检索实现解耦的可序列化结构）"""

    index: int
    doc_id: str
    doc_name: str
    content: str
    article: Optional[str] = None
    doc_number: Optional[str] = None
    issuer: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    status: str = "effective"
    score: Optional[float] = None
    file_name: Optional[str] = None
    visibility: Optional[str] = None
    level: Optional[str] = None
    security_level: Optional[str] = None
    chunk_id: Optional[str] = None
    authority: Optional[str] = None
    validity: Optional[str] = None
    # 被引文档的内容修订号（知识库版本留痕；检索实现未提供时为空，不编造）
    content_revision: Optional[int] = None


class CitationCheckRequest(BaseModel):
    """WF-03 入参：待核验答案 + 被引片段 + 核验基准日"""

    answer: str = ""
    citations: List[CitationInput] = Field(default_factory=list)
    today: Optional[date] = Field(
        default=None, description="核验基准日；缺省取当天，便于测试与回溯"
    )


class CitationCheckResponse(BaseModel):
    """WF-03 出参：清洗后的答案、有效引用、风险提示与是否通过核验"""

    workflow: str = WF03_WORKFLOW
    version: str = WF03_VERSION
    answer: str = ""
    valid: bool = True
    citations: List[Citation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SensitiveCheckRequest(BaseModel):
    """WF-04 入参：待检文本 + 声明密级（声明不能降低判定结果）"""

    text: str = ""
    declared_level: Optional[str] = Field(default=None, description="调用方声明的数据级别")
    minimum_level: str = Field(default="internal", description="兜底下限；未标明时按内部内容处理")


class SensitiveCheckResponse(BaseModel):
    """WF-04 出参：判定级别、能否出网、命中原因与可执行指引"""

    workflow: str = WF04_WORKFLOW
    version: str = WF04_VERSION
    level: str
    cloud_allowed: bool
    reasons: List[str] = Field(default_factory=list)
    guidance: str = ""
