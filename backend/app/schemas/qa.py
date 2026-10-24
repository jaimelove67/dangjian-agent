"""知识问答出入参（统一响应结构，见框架文档 5.6 / 开发规范 7.4）"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.decision_boundary import QA_DISCLAIMER

# 统一响应内置文案（标注口径见 app/core/decision_boundary.py，禁止在本模块自拟）
DEFAULT_DISCLAIMER = QA_DISCLAIMER
REFUSAL_ANSWER = "知识库中未找到直接依据，建议向上一级党组织确认。"


class AskRequest(BaseModel):
    """知识问答请求"""

    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: Optional[str] = Field(None, max_length=64, description="会话ID（多轮对话）")
    include_expired: bool = Field(False, description="是否包含已失效文件")


class Citation(BaseModel):
    """引用条目（含文件名、文号、条款、发文单位、生效日期）"""

    index: int = Field(..., description="引用编号（对应正文中的 [n]）")
    doc_id: str
    doc_name: str
    content: str
    article: Optional[str] = None
    doc_number: Optional[str] = None
    issuer: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    file_name: Optional[str] = None
    visibility: Optional[str] = None
    level: Optional[str] = None
    security_level: Optional[str] = None
    chunk_id: Optional[str] = None
    score: float = 0.0
    # 权威来源（reference 为非权威）与效力状态（effective 为现行有效）
    authority: Optional[str] = None
    validity: Optional[str] = None
    # 被引文档的内容修订号（SEC-11 知识库版本留痕）：这条答案引的是哪一版，
    # 只能跟着引用逐条记录——事后按"当前版本"倒推会把旧答案说成新版本的产物。
    content_revision: Optional[int] = None


class QAResponse(BaseModel):
    """统一问答响应：回答正文 + 引用列表 + 风险提示 + 免责声明"""

    answer: str
    citations: List[Citation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    disclaimer: str = DEFAULT_DISCLAIMER
    refused: bool = Field(False, description="是否因无依据而拒答")
