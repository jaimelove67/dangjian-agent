"""培养对象台账；阶段登记由组织人员完成，规则建议不修改台账。"""

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import deferred

from app.db.base import Base


class MemberProfile(Base):
    __tablename__ = "member_profiles"
    __table_args__ = (
        Index("ix_member_profiles_stage", "tenant_id", "current_stage", "created_at"),
        Index("ix_member_profiles_org_created", "tenant_id", "org_unit_id", "created_at"),
        UniqueConstraint("tenant_id", "user_id", name="uq_member_profiles_tenant_user"),
    )

    name = Column(String(50), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    org_name = Column(String(200), nullable=False)
    org_unit_id = Column(String(36), nullable=True)
    current_stage = Column(String(20), nullable=False, default="applicant")
    stage_joined_on = Column(Date, nullable=False, default=date.today)
    materials = Column(JSON, nullable=False, default=list)
    pending = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class MemberMaterial(Base):
    """个人提交材料：私有原件不进入知识库或模型调用。"""

    __tablename__ = "member_materials"
    __table_args__ = (
        Index("ix_member_materials_owner", "tenant_id", "user_id", "created_at"),
        UniqueConstraint(
            "tenant_id", "user_id", "submission_key", name="uq_member_material_submission"
        ),
    )

    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    profile_id = Column(String(36), ForeignKey("member_profiles.id"), nullable=False)
    title = Column(String(200), nullable=False)
    category = Column(String(30), nullable=False)
    description = Column(Text, nullable=False, default="")
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    submission_key = Column(String(36), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    content = deferred(Column(LargeBinary, nullable=False))
