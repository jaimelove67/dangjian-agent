"""组织单元表模型"""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrgUnit(Base):
    """组织单元表

    包括：学校、院系、支部等组织结构
    """

    __tablename__ = "org_units"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 组织名称
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 组织类型：school/department/branch
    org_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # 父级组织ID
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # 组织层级路径
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # 负责人
    leader_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    leader_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 备注
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OrgUnit(id={self.id}, name={self.name}, type={self.org_type})>"
