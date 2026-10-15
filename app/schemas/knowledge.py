"""知识文档出入参"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.core.constants import is_review_due


class DocumentStatusUpdate(BaseModel):
    """状态变更请求"""

    status: str = Field(..., description="effective / expired / abolished")
    reason: Optional[str] = Field(None, max_length=500)


class DocumentReviewRequest(BaseModel):
    """公共库内容审核请求（T-KB-12）"""

    decision: Literal["approve", "reject"] = Field(
        ..., description="approve=批准发布；reject=退回（必须填写审核意见）"
    )
    note: Optional[str] = Field(None, max_length=500, description="审核意见")


class DocumentMaintenanceRequest(BaseModel):
    """供给复核确认请求（T-KB-13）

    确认人已核对条目仍现行有效，或已随法规修订同步更新；确认时间写入条目并成为
    下次复核日程的基准。说明只进审计日志，不落库到条目。
    """

    note: Optional[str] = Field(None, max_length=500, description="复核说明（写入审计）")


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
    authority: str = Field("reference", description="权威来源类别")
    validity: str = Field("effective", description="效力状态")
    review_status: str = Field("published", description="公共库审核发布状态")
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    field_levels: Dict[str, str] = Field(default_factory=dict, description="字段级敏感等级")
    owner_unit: Optional[str] = Field(None, description="供给责任部门（取自学校供给机制）")
    owner_name: Optional[str] = Field(None, description="供给责任人（取自学校供给机制）")
    review_cycle_days: Optional[int] = Field(None, description="复核周期（天）")
    maintained_at: Optional[datetime] = Field(None, description="最近一次复核确认或内容更新时间")
    next_review_at: Optional[date] = Field(None, description="下次复核日期")
    review_due: bool = Field(False, description="是否已到复核期限（维护信号，不影响检索）")
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    tags: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    page_count: Optional[int] = Field(None, description="文档页数（PDF等有页码的文档）")
    content_revision: int = 1

    @classmethod
    def from_document(
        cls,
        document: Any,
        page_count: Optional[int] = None,
        supply: Optional[Dict[str, Any]] = None,
    ) -> "DocumentResponse":
        """文档出参

        ``supply`` 是该条目权威来源对应的供给机制
        （``{"owner_unit": ..., "owner_name": ..., "review_cycle_days": ...}``），
        由调用方按租户配置解析后传入——出参不在这里查库。
        """
        rule = dict(supply or {})
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
            authority=document.authority or "reference",
            validity=document.validity or "effective",
            review_status=document.review_status or "published",
            reviewed_by=document.reviewed_by,
            reviewed_at=document.reviewed_at,
            review_note=document.review_note,
            field_levels=dict(document.field_levels or {}),
            owner_unit=rule.get("owner_unit"),
            owner_name=rule.get("owner_name"),
            review_cycle_days=rule.get("review_cycle_days"),
            maintained_at=document.maintained_at,
            next_review_at=document.next_review_at,
            review_due=is_review_due(
                document.next_review_at,
                status=document.status,
                validity=document.validity,
            ),
            effective_date=document.effective_date,
            expiration_date=document.expiration_date,
            tags=list(document.tags or []),
            summary=document.summary,
            page_count=page_count or (document.doc_metadata or {}).get("page_count"),
            content_revision=(document.doc_metadata or {}).get("content_revision", 1),
        )


class DocumentCreateResponse(BaseModel):
    """入库响应"""

    document: DocumentResponse
    chunk_count: int = 0


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = Field(default_factory=dict)
