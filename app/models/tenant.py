"""租户表模型"""

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    """租户表

    支持多级租户结构：平台 -> 学校 -> 院系 -> 支部
    """

    __tablename__ = "tenants"

    # 租户名称
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 租户类型：platform/school/department/branch
    tenant_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # 父级租户ID（平台级为 NULL）
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # 租户层级路径（用于快速查询子树）
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # 租户配置（JSON）
    config: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 联系信息
    contact_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 备注
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name}, type={self.tenant_type})>"
