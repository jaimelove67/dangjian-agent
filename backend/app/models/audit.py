"""审计日志表模型"""

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """审计日志表

    记录所有关键操作，只追加不修改
    """

    __tablename__ = "audit_logs"

    # 操作用户ID
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 操作用户名
    user_name: Mapped[str] = mapped_column(String(50), nullable=False)

    # 操作类型：create/update/delete/query/export
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # 资源类型：user/knowledge_doc/member/meeting等
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # 资源ID
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # 数据级别：public/internal/sensitive/classified
    data_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 请求信息
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 操作结果：success/failed/denied
    result: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 变更记录（JSON）
    old_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, result={self.result})>"
