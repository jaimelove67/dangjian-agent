"""业务路由共用的审计写入，复用当前事务，不记录问题原文或令牌。"""

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.redaction import audit_summary
from app.models.user import User


async def audit_operation(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    data_level: str = "internal",
    **values: Any,
) -> None:
    """记录真实操作人与请求 ID；调用方在业务成功后提交同一事务。"""
    request.state.audit_data_level = data_level
    for key in ("old_value", "new_value"):
        if key in values and values[key] is not None:
            values[key] = audit_summary(values[key])
    await write_audit(
        db,
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        user_name=str(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=getattr(request.state, "trace_id", "unknown")[:64],
        result="success",
        data_level=data_level,
        ip_address=request.client.host if request.client else None,
        user_agent=None,
        **values,
    )
