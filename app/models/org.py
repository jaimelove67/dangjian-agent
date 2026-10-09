"""组织单元表模型"""
from sqlalchemy import Column, String, Text

from app.db.base import Base


class OrgUnit(Base):
    """组织单元表

    包括：学校、院系、支部等组织结构
    """
    __tablename__ = "org_units"

    # 组织名称
    name = Column(String(100), nullable=False)

    # 组织类型：school/department/branch
    org_type = Column(String(20), nullable=False)

    # 父级组织ID
    parent_id = Column(String(36), nullable=True, index=True)

    # 组织层级路径
    path = Column(String(500), nullable=False, index=True)

    # 负责人
    leader_name = Column(String(50), nullable=True)
    leader_phone = Column(String(20), nullable=True)

    # 备注
    remark = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OrgUnit(id={self.id}, name={self.name}, type={self.org_type})>"
