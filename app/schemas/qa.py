"""问答Schema扩展"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """问答请求"""
    question: str = Field(..., description="用户问题", min_length=1, max_length=500)
    session_id: Optional[str] = Field(None, description="会话ID（用于多轮对话）")
    context: Optional[Dict[str, Any]] = Field(None, description="额外上下文")


class Citation(BaseModel):
    """引用"""
    doc_id: str = Field(..., description="文档ID")
    doc_title: str = Field(..., description="文档标题")
    doc_number: Optional[str] = Field(None, description="文号")
    article: Optional[str] = Field(None, description="条款编号")
    excerpt: str = Field(..., description="引用片段")
    relevance_score: float = Field(..., description="相关度分数")


class QAResponse(BaseModel):
    """问答响应"""
    answer: str = Field(..., description="答案文本")
    citations: List[Citation] = Field(default_factory=list, description="引用列表")
    has_evidence: bool = Field(..., description="是否有足够依据")
    warnings: List[str] = Field(default_factory=list, description="警告信息（引用核验）")
    disclaimer: str = Field(..., description="免责声明")
