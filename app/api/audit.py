"""业务路由共用的审计写入，复用当前事务，不记录问题原文或令牌。"""

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
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
    await write_audit(
        db,
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        user_name=user.username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=getattr(request.state, "trace_id", "unknown")[:64],
        result="success",
        data_level=data_level,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
        **values,
    )
