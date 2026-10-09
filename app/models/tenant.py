"""租户表模型"""
from sqlalchemy import Column, String, JSON, Text

from app.db.base import Base


class Tenant(Base):
    """租户表

    支持多级租户结构：平台 -> 学校 -> 院系 -> 支部
    """
    __tablename__ = "tenants"

    # 租户名称
    name = Column(String(100), nullable=False)

    # 租户类型：platform/school/department/branch
    tenant_type = Column(String(20), nullable=False)

    # 父级租户ID（平台级为 NULL）
    parent_id = Column(String(36), nullable=True, index=True)

    # 租户层级路径（用于快速查询子树）
    path = Column(String(500), nullable=False, index=True)

    # 租户配置（JSON）
    config = Column(JSON, nullable=True)

    # 联系信息
    contact_name = Column(String(50), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    contact_email = Column(String(100), nullable=True)

    # 备注
    remark = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name}, type={self.tenant_type})>"
