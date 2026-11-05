"""会议文书版式模板：控制章节顺序、标题、显示与字段名称。

模板不保存会议业务内容，也不允许脚本或任意 HTML。每次正式发布形成不可变版本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingDocumentTemplate(Base):
    __tablename__ = "meeting_document_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "org_unit_id",
            "version",
            name="uq_meeting_document_template_version",
        ),
        Index(
            "ix_meeting_document_template_scope",
            "tenant_id",
            "org_unit_id",
            "status",
        ),
    )

    # 空字符串表示学校默认模板，避免 nullable 唯一约束在 PostgreSQL 中失效。
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_data: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
