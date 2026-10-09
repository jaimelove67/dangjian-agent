"""检索相关Schema定义"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.llm.base import DataLevel


class RetrievalFilters(BaseModel):
    """检索过滤条件"""
    tenant_id: str = Field(..., description="租户ID")
    data_level: DataLevel = Field(..., description="数据级别")
    visibility_levels: List[str] = Field(..., description="可见范围列表")
    exclude_expired: bool = Field(default=True, description="排除失效文件")
    security_levels: Optional[List[str]] = Field(None, description="保密级别过滤")
    doc_levels: Optional[List[str]] = Field(None, description="文档层级过滤")


class RetrievalResult(BaseModel):
    """单个检索结果"""
    chunk_id: str = Field(..., description="片段ID")
    doc_id: str = Field(..., description="文档ID")
    content: str = Field(..., description="片段内容")
    score: float = Field(..., description="相关度分数")
    article: Optional[str] = Field(None, description="条款编号")
    sequence: int = Field(..., description="片段序号")

    # 文档元数据
    doc_title: Optional[str] = Field(None, description="文档标题")
    doc_number: Optional[str] = Field(None, description="文号")
    issuer: Optional[str] = Field(None, description="发文单位")
    effective_date: Optional[str] = Field(None, description="生效日期")

    metadata: Dict[str, Any] = Field(default_factory=dict, description="其他元数据")


class RetrievalResponse(BaseModel):
    """检索响应"""
    results: List[RetrievalResult] = Field(default_factory=list, description="检索结果列表")
    has_evidence: bool = Field(..., description="是否有足够依据")
    total_count: int = Field(..., description="结果总数")
    retrieval_method: str = Field(..., description="检索方法：vector/keyword/hybrid")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="检索元数据")
