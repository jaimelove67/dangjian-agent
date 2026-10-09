"""审计日志表模型"""
from sqlalchemy import Column, String, Text, JSON

from app.db.base import Base


class AuditLog(Base):
    """审计日志表

    记录所有关键操作，只追加不修改
    """
    __tablename__ = "audit_logs"

    # 操作用户ID
    user_id = Column(String(36), nullable=False, index=True)

    # 操作用户名
    user_name = Column(String(50), nullable=False)

    # 操作类型：create/update/delete/query/export
    action = Column(String(50), nullable=False, index=True)

    # 资源类型：user/knowledge_doc/member/meeting等
    resource_type = Column(String(50), nullable=False, index=True)

    # 资源ID
    resource_id = Column(String(36), nullable=True, index=True)

    # 数据级别：public/internal/sensitive/classified
    data_level = Column(String(20), nullable=False, index=True)

    # 请求信息
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    request_id = Column(String(64), nullable=False, index=True)

    # 操作结果：success/failed/denied
    result = Column(String(20), nullable=False, index=True)

    # 错误信息
    error_message = Column(Text, nullable=True)

    # 变更记录（JSON）
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, result={self.result})>"
