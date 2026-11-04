"""外部党建资料采集与审核台账。

外部网页只作为三会一课准备工作的参考资料，不能直接当成正式会议记录。
资料先进入待审核状态，审核通过后写入知识库，供议程草稿引用来源。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExternalUpdate(Base):
    __tablename__ = "external_updates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", name="uq_external_updates_tenant_hash"),
        Index("ix_external_updates_scope", "tenant_id", "status", "fetched_at"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    knowledge_doc_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
