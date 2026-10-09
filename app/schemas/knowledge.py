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

    @classmethod
    def from_document(cls, document: Any) -> "DocumentResponse":
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
        )


class DocumentCreateResponse(BaseModel):
    """入库响应"""
    document: DocumentResponse
    chunk_count: int = 0
