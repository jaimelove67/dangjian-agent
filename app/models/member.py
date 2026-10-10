"""培养对象台账；阶段登记由组织人员完成，规则建议不修改台账。"""

from datetime import date

from sqlalchemy import JSON, Boolean, Column, Date, Index, Integer, String

from app.db.base import Base


class MemberProfile(Base):
    __tablename__ = "member_profiles"
    __table_args__ = (
        Index("ix_member_profiles_stage", "tenant_id", "current_stage", "created_at"),
        Index("ix_member_profiles_org_created", "tenant_id", "org_unit_id", "created_at"),
    )

    name = Column(String(50), nullable=False)
    org_name = Column(String(200), nullable=False)
    org_unit_id = Column(String(36), nullable=True)
    current_stage = Column(String(20), nullable=False, default="applicant")
    stage_joined_on = Column(Date, nullable=False, default=date.today)
    materials = Column(JSON, nullable=False, default=list)
    pending = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
