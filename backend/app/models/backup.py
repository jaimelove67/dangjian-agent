"""Backups and isolated restore drills expose actual persisted execution results."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BackupJob(Base):
    __tablename__ = "backup_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "dedup_key", name="uq_backup_job_dedup"),)

    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[str] = mapped_column(String(36))
    source_id: Mapped[str | None] = mapped_column(String(36))
    dedup_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
