"""登录会话、终身自主改密记录与一次性审批授权。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoginSession(Base):
    __tablename__ = "login_sessions"

    user_id: Mapped[str] = mapped_column(String(36), index=True)
    identity_stamp: Mapped[str] = mapped_column(String(64))
    client_label: Mapped[str] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class PasswordRequest(Base):
    __tablename__ = "password_requests"

    user_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_comment: Mapped[str | None] = mapped_column(String(300))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PasswordChange(Base):
    __tablename__ = "password_changes"

    user_id: Mapped[str] = mapped_column(String(36), index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
