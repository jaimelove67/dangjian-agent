"""事件→通知渠道的抽象层。

设计约束来自《党建工作智能体_LangChain实现项目文档》：
- 5.9.4：提前量、触发条件、通知对象、**渠道全部可配置**，提醒记录进入审计；
- 15.10：通知渠道“实现通知接口并登记”，一个实现即可起步；
- 待办生成的边界：系统不替组织决定是否外发（不代发通知），只有被显式配置的
  路由、或被人工确认后，才会真正投递。

因此本模块默认**不投递任何东西**：``NOTIFICATION_ROUTES`` 默认为空。站内渠道是
第一个（也是当前唯一实现的）渠道，外部渠道（企业微信、邮件）实现同一协议并注册
即可接入，凭据齐备前 ``configured()`` 返回 False，不参与投递也不静默失败。

渠道实现只负责“一次投递尝试”，失败必须抛异常；去重、重试、台账和审计由
:func:`dispatch` 统一处理。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.models.notification import (
    CHANNEL_IN_APP,
    ERROR_DELIVERY_FAILED,
    ERROR_NOT_CONFIGURED,
    ERROR_UNKNOWN_CHANNEL,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    NotificationDelivery,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationMessage:
    """一条待投递的通知；``dedup_key`` 为空时按内容派生，保证重放不会重复外发。"""

    tenant_id: str
    event: str
    subject: str
    body: str
    recipient_id: str | None = None
    recipient_address: str | None = None
    dedup_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def resolved_dedup_key(self) -> str:
        if self.dedup_key:
            return self.dedup_key[:128]
        seed = json.dumps(
            [self.event, self.recipient_id or "", self.subject, self.body],
            ensure_ascii=False,
            sort_keys=True,
        )
        return "auto-" + hashlib.sha256(seed.encode()).hexdigest()[:32]


class NotificationChannel(Protocol):
    """通知渠道协议。

    ``name`` 是配置里引用的渠道标识；``configured()`` 表示凭据/主机是否齐备；
    ``deliver()`` 只做一次尝试，失败抛异常（不要把凭据或异常原文写进日志）。
    """

    name: str
    description: str

    def configured(self) -> bool: ...

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None: ...


class InAppChannel:
    """站内渠道：台账落库即用户可见提醒，不产生任何外部调用。

    保留为一等渠道，是为了让站内与外部渠道共用同一条路由、去重、重试与审计链路；
    这样以后接入企业微信/邮件时，业务侧代码不需要再改一遍。
    """

    name = CHANNEL_IN_APP
    description = "站内：投递记录即用户可见提醒，不外发"

    def configured(self) -> bool:
        return True

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None:
        # 站内渠道没有外部依赖，台账写入即达；用户端读取同一张台账。
        return None


class ChannelRegistry:
    """已登记渠道的登记表；新增渠道 = 实现协议 + 注册。"""

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}

    def register(self, channel: NotificationChannel) -> None:
        if not channel.name:
            raise ValueError("通知渠道必须有名称")
        self._channels[channel.name] = channel

    def get(self, name: str) -> NotificationChannel | None:
        return self._channels.get(name)

    def names(self) -> list[str]:
        return sorted(self._channels)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": channel.name,
                "description": channel.description,
                "configured": bool(channel.configured()),
            }
            for _, channel in sorted(self._channels.items())
        ]


registry = ChannelRegistry()
registry.register(InAppChannel())


def register_channel(channel: NotificationChannel) -> None:
    """登记一个渠道实现（供外部渠道接入与测试替身使用）。"""
    registry.register(channel)


def routes_for(event: str) -> list[str]:
    """解析事件→渠道；未配置即返回空列表（默认不外发）。"""
    routes = settings.NOTIFICATION_ROUTES or {}
    return [str(name) for name in routes.get(event, [])]


@dataclass(frozen=True)
class DeliveryResult:
    """一次投递的结果；``skipped`` 表示此前已投递成功（去重命中）。"""

    channel: str
    status: str
    attempts: int
    skipped: bool = False
    error: str | None = None


def _safe_error(exc: BaseException) -> str:
    """只保留失败分类与异常类型名。

    渠道异常原文可能带主机、账号或正文，一律不写进台账与日志；运维需要的是
    “哪个渠道、哪一类失败、试了几次”，而不是原始堆栈。
    """
    return f"{ERROR_DELIVERY_FAILED}:{type(exc).__name__}"[:60]


async def _find(db: AsyncSession, dedup_key: str, channel: str) -> NotificationDelivery | None:
    return (
        await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.dedup_key == dedup_key,
                NotificationDelivery.channel == channel,
            )
        )
    ).scalar_one_or_none()


async def _claim(
    db: AsyncSession, message: NotificationMessage, channel: str, actor_id: str | None
) -> NotificationDelivery:
    """取得该 (事件, 去重键, 渠道) 的台账行；不存在则新建。

    用 SAVEPOINT 兜住并发下的唯一键冲突，不再回滚调用方的业务事务。
    """
    dedup_key = message.resolved_dedup_key()
    existing = await _find(db, dedup_key, channel)
    if existing is not None:
        return existing
    row = NotificationDelivery(
        tenant_id=message.tenant_id,
        event=message.event,
        dedup_key=dedup_key,
        channel=channel,
        recipient_id=message.recipient_id,
        recipient_address=message.recipient_address,
        subject=message.subject[:200],
        body=message.body,
        status=STATUS_PENDING,
        attempts=0,
        actor_id=actor_id,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # 并发下另一个请求先写入了同一台账行；复用它即代表本请求不再外发。
        found = await _find(db, dedup_key, channel)
        if found is None:
            raise
        row = found
    return row


async def _record(
    db: AsyncSession,
    row: NotificationDelivery,
    status: str,
    attempts: int,
    error: str | None,
    *,
    actor_id: str | None,
) -> DeliveryResult:
    """落定台账状态并写审计；审计与业务同事务，由调用方提交。"""
    row.status = status
    row.attempts = attempts
    row.last_error = error
    if status == STATUS_SENT:
        row.delivered_at = datetime.utcnow()
    await db.flush()
    await write_audit(
        db,
        tenant_id=row.tenant_id,
        user_id=actor_id or "system",
        user_name=actor_id or "system",
        action="notification_dispatch",
        resource_type="notification",
        resource_id=row.id,
        request_id=uuid.uuid4().hex,
        result="success" if status == STATUS_SENT else "failed",
        data_level="internal",
        new_value={
            "event": row.event,
            "channel": row.channel,
            "status": status,
            "attempts": attempts,
            "error": error,
            "recipient_id": row.recipient_id,
        },
    )
    return DeliveryResult(channel=row.channel, status=status, attempts=attempts, error=error)


async def dispatch(
    db: AsyncSession,
    message: NotificationMessage,
    *,
    channels: list[str] | None = None,
    max_attempts: int | None = None,
    actor_id: str | None = None,
) -> list[DeliveryResult]:
    """按配置把事件投递到各渠道。

    - ``channels`` 为空时读取 ``NOTIFICATION_ROUTES[event]``；两者都没有就什么都不做；
    - 已投递成功的台账号会被跳过：补偿扫描/重复请求不重复外发，也不重复写审计；
    - 未登记或未配置的渠道记为失败并留痕，不静默丢弃；
    - 任何渠道异常都不会冒泡到业务事务，也不阻断其它渠道。
    """
    names = channels if channels is not None else routes_for(message.event)
    if not names:
        return []
    limit = max(1, max_attempts if max_attempts is not None else settings.NOTIFICATION_MAX_ATTEMPTS)
    results: list[DeliveryResult] = []
    for name in names:
        row = await _claim(db, message, name, actor_id)
        if row.status == STATUS_SENT:
            results.append(DeliveryResult(name, STATUS_SENT, row.attempts, skipped=True))
            continue
        channel = registry.get(name)
        if channel is None:
            results.append(
                await _record(db, row, STATUS_FAILED, 0, ERROR_UNKNOWN_CHANNEL, actor_id=actor_id)
            )
            continue
        if not channel.configured():
            results.append(
                await _record(db, row, STATUS_FAILED, 0, ERROR_NOT_CONFIGURED, actor_id=actor_id)
            )
            continue
        error: str | None = None
        attempt = 0
        for attempt in range(1, limit + 1):
            try:
                await channel.deliver(message, attempt=attempt)
            except Exception as exc:  # noqa: BLE001 - 渠道异常不能影响业务事务
                error = _safe_error(exc)
                logger.warning(
                    "notification_delivery_failed channel=%s event=%s attempt=%s error=%s",
                    name,
                    message.event,
                    attempt,
                    type(exc).__name__,
                )
                if attempt < limit and settings.NOTIFICATION_BACKOFF_SECONDS:
                    await asyncio.sleep(settings.NOTIFICATION_BACKOFF_SECONDS * attempt)
                continue
            error = None
            break
        status = STATUS_SENT if error is None else STATUS_FAILED
        results.append(await _record(db, row, status, attempt, error, actor_id=actor_id))
    return results


def delivery_view(row: NotificationDelivery) -> dict[str, Any]:
    """投递台账的公开视图；不返回接收人地址等尽可能少的信息。"""
    return {
        "id": row.id,
        "event": row.event,
        "channel": row.channel,
        "recipient_id": row.recipient_id,
        "subject": row.subject,
        "status": row.status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
