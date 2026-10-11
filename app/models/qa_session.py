"""长期问答记录，与 Redis 中有期限的多轮上下文分别保存。"""

from typing import Any

from sqlalchemy import JSON, Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.qa import DEFAULT_DISCLAIMER


class QASession(Base):
    __tablename__ = "qa_sessions"
    __table_args__ = (Index("ix_qa_sessions_user_created", "tenant_id", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    has_sufficient_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_DISCLAIMER)
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
