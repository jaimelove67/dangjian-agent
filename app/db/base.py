"""数据模型基类"""

import re
import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Boolean, DateTime, String, Table, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """所有数据模型的基类"""

    # 由子类提供表名
    __table__: ClassVar[Table]
    # UPDATE timestamps are server-generated too; async response serialization must
    # not implicitly fetch expired attributes outside an awaited database operation.
    __mapper_args__ = {"eager_defaults": True}

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """自动生成表名（驼峰转下划线）"""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    # 所有表的公共字段
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    def dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
