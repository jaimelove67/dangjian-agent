"""数据模型基类"""
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, String, DateTime, Boolean, func
from sqlalchemy.orm import as_declarative, declared_attr


@as_declarative()
class Base:
    """所有数据模型的基类"""

    # 由子类提供表名
    __name__: str

    @declared_attr
    def __tablename__(cls) -> str:
        """自动生成表名（驼峰转下划线）"""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    # 所有表的公共字段
    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )
    is_deleted = Column(Boolean, nullable=False, default=False)
    tenant_id = Column(String(36), nullable=False, index=True)

    def dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
