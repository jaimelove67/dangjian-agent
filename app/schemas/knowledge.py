"""知识文档出入参"""
from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class DocumentStatusUpdate(BaseModel):
    """状态变更请求"""
    status: str = Field(..., description="effective / expired / abolished")


class DocumentResponse(BaseModel):
    """文档响应"""
    id: str
    doc_id: str
    file_name: str
    title: str
    issuer: str
    doc_number: Optional[str] = None
    level: str
    visibility: str
    security_level: str
    status: str
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    tags: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    page_count: Optional[int] = Field(None, description="文档页数（PDF等有页码的文档）")

    @classmethod
    def from_document(cls, document: Any, page_count: Optional[int] = None) -> "DocumentResponse":
        return cls(
            id=str(document.id),
            doc_id=document.doc_id,
            file_name=document.file_name,
            title=document.title,
            issuer=document.issuer,
            doc_number=document.doc_number,
            level=document.level,
            visibility=document.visibility,
            security_level=document.security_level,
            status=document.status,
            effective_date=document.effective_date,
            expiration_date=document.expiration_date,
            tags=list(document.tags or []),
            summary=document.summary,
            page_count=page_count or getattr(document, "page_count", None),
        )


class DocumentCreateResponse(BaseModel):
    """入库响应"""
    document: DocumentResponse
    chunk_count: int = 0


class DocumentListResponse(BaseModel):
    """文件列表响应（分页）"""
    total: int = Field(..., description="命中总数")
    items: List[DocumentResponse] = Field(default_factory=list, description="当前页文档")
