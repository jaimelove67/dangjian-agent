"""学校通知、督办任务与业务角色申请，全部保留版本和处理人。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SchoolBusinessRecord(Base):
    __tablename__ = "school_business_records"

    kind: Mapped[str] = mapped_column(String(20), index=True)
    org_unit_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(36))
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
