"""审计日志模块

统一审计接口，满足框架文档 10.2 与开发规范 8.4：

- 覆盖业务操作：操作人、时间、动作、对象、数据级别、结果、来源地址；
- 敏感操作额外记录变更前后值；
- **只追加不修改**：ORM 层拦截对审计表的更新与删除（数据库权限另行保证）。

本模块不直接提交事务，仅 ``add`` + ``flush``，由调用方（服务层/依赖注入）
决定提交时机，以复用请求事务。
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Select, event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.constants import AuditAction, AuditResult, DataLevel
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)

_VALID_DATA_LEVELS = {level.value for level in DataLevel}


class AuditError(Exception):
    """审计相关错误"""


def _coerce(value: Any, enum_cls: type) -> str:
    """将枚举或字符串统一为字符串值"""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def make_audit_log(
    *,
    tenant_id: str,
    user_id: str,
    user_name: str,
    action: AuditAction | str,
    resource_type: str,
    request_id: str,
    result: AuditResult | str,
    resource_id: Optional[str] = None,
    data_level: DataLevel | str = DataLevel.PUBLIC,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> AuditLog:
    """构造审计日志对象（纯函数，不触碰数据库，便于测试）

    Raises:
        AuditError: 关键字段缺失或取值非法
    """
    data_level_value = _coerce(data_level, DataLevel)
    if data_level_value not in _VALID_DATA_LEVELS:
        raise AuditError(f"非法的数据级别: {data_level_value}")

    if not tenant_id:
        raise AuditError("审计日志缺少 tenant_id")
    if not user_id:
        raise AuditError("审计日志缺少 user_id")
    if not request_id:
        raise AuditError("审计日志缺少 request_id")

    return AuditLog(
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        user_name=user_name,
        action=_coerce(action, AuditAction),
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        data_level=data_level_value,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        result=_coerce(result, AuditResult),
        error_message=error_message,
        old_value=old_value,
        new_value=new_value,
    )


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    user_name: str,
    action: AuditAction | str,
    resource_type: str,
    request_id: str,
    result: AuditResult | str,
    **kwargs: Any,
) -> AuditLog:
    """写入一条审计日志（add + flush，不提交）

    Args:
        session: 异步数据库会话
        **kwargs: 同 ``make_audit_log``

    Returns:
        已写入的审计日志对象
    """
    log = make_audit_log(
        tenant_id=tenant_id,
        user_id=user_id,
        user_name=user_name,
        action=action,
        resource_type=resource_type,
        request_id=request_id,
        result=result,
        **kwargs,
    )
    session.add(log)
    await session.flush()
    logger.info(
        "audit_written",
        extra={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": log.action,
            "resource_type": resource_type,
            "result": log.result,
            "request_id": request_id,
        },
    )
    return log


def query_audit_logs(
    *,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    data_level: Optional[str] = None,
) -> Select:
    """构造审计查询语句（仅构造，不执行）

    支持按用户、动作、对象、数据级别筛选；租户条件由调用方（检索/数据访问层）
    强制注入。
    """
    stmt = select(AuditLog)
    if tenant_id is not None:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if data_level is not None:
        stmt = stmt.where(AuditLog.data_level == data_level)
    return stmt.order_by(AuditLog.created_at.desc())


# ==================== 只追加约束 ====================
@event.listens_for(Session, "before_flush")
def _prevent_audit_mutation(
    session: Session, flush_context: Any, instances: Any
) -> None:
    """阻止对审计表的更新与删除（应用层保证只追加）"""
    for instance in session.dirty:
        if isinstance(instance, AuditLog):
            raise AuditError("审计日志不可修改（只追加）")
    for instance in session.deleted:
        if isinstance(instance, AuditLog):
            raise AuditError("审计日志不可删除（只追加）")
