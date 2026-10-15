"""通知渠道与投递台账接口。

- 渠道与路由只读查询：看得见“配了哪些渠道、哪个渠道还没凭据”；
- 投递台账只读查询：看得见每一次投递的渠道、次数与失败分类；
- 人工确认后的一次投递：系统不替组织自动外发，确认动作与结果都进审计。

凭据（企业微信密钥、SMTP 主机账号）不进接口、不进台账、不进日志；渠道实现通过
``app.services.notifications.register_channel`` 登记，未配置的渠道不会参与投递。
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.notification import (
    KNOWN_EVENTS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    NotificationDelivery,
)
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.notification import DispatchRequest
from app.services import notifications
from app.services.notifications import NotificationMessage

router = APIRouter()
_read = require_permissions(Permission.OPS_QUERY)
_confirm = require_permissions(Permission.CONFIG_MANAGE)


def response(request: Request, data: object) -> APIResponse:
    return APIResponse(
        data=jsonable_encoder(data), trace_id=getattr(request.state, "trace_id", None)
    )


@router.get(
    "/admin/notification-channels",
    response_model=APIResponse[dict],
    summary="已登记的通知渠道与事件路由",
)
async def channels(
    request: Request,
    user: User = Depends(_read),
) -> APIResponse[dict]:
    """列出已登记渠道、是否已配置凭据，以及当前事件路由（默认空：不外发）。"""
    return response(
        request,
        {
            "items": notifications.registry.describe(),
            "events": sorted(KNOWN_EVENTS),
            "routes": settings.NOTIFICATION_ROUTES or {},
            "max_attempts": settings.NOTIFICATION_MAX_ATTEMPTS,
        },
    )


@router.get(
    "/admin/notification-deliveries",
    response_model=APIResponse[dict],
    summary="通知投递台账（按渠道与失败分类）",
)
async def deliveries(
    request: Request,
    event: str | None = Query(None, max_length=40),
    status: str | None = Query(None, pattern="^(pending|sent|failed)$"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """当前租户内的投递记录；重复键只留一行，重试用尽保留失败分类。"""
    statement = select(NotificationDelivery)
    if event:
        statement = statement.where(NotificationDelivery.event == event)
    if status:
        statement = statement.where(NotificationDelivery.status == status)
    rows = (
        (await db.execute(statement.order_by(NotificationDelivery.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return response(
        request,
        {
            "items": [notifications.delivery_view(row) for row in rows],
            "statuses": [STATUS_PENDING, STATUS_SENT, STATUS_FAILED],
        },
    )


@router.post(
    "/admin/notifications/dispatch",
    response_model=APIResponse[dict],
    summary="人工确认后投递一次通知（写入台账与审计）",
)
async def dispatch_notification(
    body: DispatchRequest,
    request: Request,
    user: User = Depends(_confirm),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """按事件路由或显式渠道投递一次；重复请求命中台账去重，不重复外发。"""
    message = NotificationMessage(
        tenant_id=str(user.tenant_id),
        event=body.event,
        subject=body.subject,
        body=body.body,
        recipient_id=body.recipient_id,
        dedup_key=body.dedup_key or "",
    )
    results = await notifications.dispatch(
        db, message, channels=body.channels, actor_id=str(user.id)
    )
    await audit_operation(
        db,
        request,
        user,
        action="notification_dispatch_confirmed",
        resource_type="notification",
        new_value={
            "event": body.event,
            "channels": body.channels or notifications.routes_for(body.event),
            "results": [result.status for result in results],
        },
    )
    await db.commit()
    return response(
        request,
        {
            "results": [
                {
                    "channel": result.channel,
                    "status": result.status,
                    "attempts": result.attempts,
                    "skipped": result.skipped,
                    "error": result.error,
                }
                for result in results
            ]
        },
    )
