"""模块 6：配置历史、人工审核、可恢复任务及模型使用记录。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConfigRevision(Base):
    __tablename__ = "config_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    values: Mapped[Any] = mapped_column(JSON, nullable=False)


class HumanReview(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        Index(
            "uq_human_review_pending",
            "tenant_id",
            "source_kind",
            "source_id",
            "source_version",
            unique=True,
            postgresql_where=text("status='pending' AND is_deleted=false"),
        ),
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    submitted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opinion: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class DurableJob(Base):
    __tablename__ = "durable_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "dedup_key"),)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ModelUsage(Base):
    __tablename__ = "model_usage"
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
