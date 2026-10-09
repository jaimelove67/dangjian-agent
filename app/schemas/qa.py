"""知识问答出入参（统一响应结构，见框架文档 5.6 / 开发规范 7.4）"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

# 统一响应内置文案
DEFAULT_DISCLAIMER = "本回答仅供参考，具体以组织部门确认为准。"
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


class QAResponse(BaseModel):
    """统一问答响应：回答正文 + 引用列表 + 风险提示 + 免责声明"""
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    disclaimer: str = DEFAULT_DISCLAIMER
    refused: bool = Field(False, description="是否因无依据而拒答")
