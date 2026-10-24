"""教育课程、党日报名及本人学习进度；积分只在服务端完成条件满足后记账。"""

from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EducationOffering(Base):
    __tablename__ = "education_offerings"

    kind: Mapped[str] = mapped_column(String(20), index=True)
    org_unit_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(36))


class EducationEnrollment(Base):
    __tablename__ = "education_enrollments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "offering_id", "user_id", name="uq_education_enrollment"),
    )

    offering_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="enrolled")
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    points: Mapped[int] = mapped_column(Integer, default=0)
