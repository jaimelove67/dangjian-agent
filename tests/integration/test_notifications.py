"""通知渠道抽象层：事件→渠道路由、去重、重试、失败留痕与审计。

用真实 PostgreSQL（跑到迁移 head，顺带验证 ``013_notification_delivery``）加假发送器，
不依赖任何外部凭据：外部渠道由测试替身代替，因此这里证明的是“链路正确”，
不是“企业微信/邮件可用”。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.tenant import tenant_context
from app.models.audit import AuditLog
from app.models.notification import (
    CHANNEL_IN_APP,
    ERROR_DELIVERY_FAILED,
    ERROR_NOT_CONFIGURED,
    ERROR_UNKNOWN_CHANNEL,
    EVENT_CHANNEL_SELF_TEST,
    STATUS_FAILED,
    STATUS_SENT,
    NotificationDelivery,
)
from app.services import notifications
from app.services.notifications import NotificationMessage, register_channel

pytestmark = pytest.mark.integration


@pytest.fixture
def tenant() -> str:
    """每个用例一个独立租户，避免共享一次性库导致台账/审计互相污染。"""
    return str(uuid.uuid4())


def message(tenant: str, **overrides) -> NotificationMessage:
    payload = {
        "tenant_id": tenant,
        "event": EVENT_CHANNEL_SELF_TEST,
        "subject": "渠道自检",
        "body": "这是一条合成通知，不含真实人员信息。",
        "recipient_id": "22222222-2222-2222-2222-222222222222",
    }
    payload.update(overrides)
    return NotificationMessage(**payload)


class RecordingChannel:
    """测试替身：始终成功，记录每次尝试。"""

    name = "recording"
    description = "测试替身：记录消息，始终成功"

    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []
        self.attempts: list[int] = []

    def configured(self) -> bool:
        return True

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None:
        self.attempts.append(attempt)
        self.messages.append(message)


class FlakyChannel(RecordingChannel):
    """测试替身：前 N 次失败，之后成功。"""

    name = "flaky"

    def __init__(self, fail_times: int = 2) -> None:
        super().__init__()
        self.fail_times = fail_times

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None:
        self.attempts.append(attempt)
        if attempt <= self.fail_times:
            raise RuntimeError("synthetic delivery failure")
        self.messages.append(message)


class BrokenChannel(RecordingChannel):
    """测试替身：永远失败。"""

    name = "broken"

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None:
        self.attempts.append(attempt)
        raise TimeoutError("synthetic timeout")


class UnconfiguredChannel(RecordingChannel):
    """外部渠道占位：凭据未配置，不应被调用。"""

    name = "wecom-like"
    description = "外部渠道占位：凭据未配置"

    def configured(self) -> bool:
        return False

    async def deliver(self, message: NotificationMessage, *, attempt: int) -> None:
        raise AssertionError("未配置的渠道不应被调用")


@pytest.fixture(scope="module")
def notification_url():
    """建一个一次性数据库并跑到迁移 head，用完删除。"""
    name = "party_nt_test_" + uuid.uuid4().hex[:12]
    admin = make_url(settings.DATABASE_URL).set(database="postgres")
    target = admin.set(database=name)

    async def provision(create: bool) -> None:
        assert name.startswith("party_nt_test_") and len(name) == 26
        engine = create_async_engine(admin, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'{"CREATE" if create else "DROP"} DATABASE "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(provision(True))

    async def migrate() -> None:
        engine = create_async_engine(target, poolclass=NullPool)
        try:
            async with engine.begin() as conn:

                def upgrade(sync) -> None:
                    config = Config("alembic.ini")
                    config.attributes["connection"] = sync
                    command.upgrade(config, "head")
                    # 迁移必须真的建出投递台账，而不是靠模型自动建表兜底。
                    assert sync.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name='notification_deliveries' "
                            "AND column_name='dedup_key'"
                        )
                    ).scalar_one_or_none()

                await conn.run_sync(upgrade)
        finally:
            await engine.dispose()

    try:
        asyncio.run(migrate())
        yield target
    finally:
        asyncio.run(provision(False))


@pytest.fixture
async def db(notification_url, monkeypatch, tmp_path):
    engine = create_async_engine(notification_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "AUDIT_SPOOL_DIR", str(tmp_path / "audit"))
    try:
        yield maker
    finally:
        await engine.dispose()


async def ledger(db, tenant: str) -> list[NotificationDelivery]:
    """读取该租户的投递台账（无租户上下文，不触发自动过滤）。"""
    async with db() as session:
        statement = select(NotificationDelivery).where(
            NotificationDelivery.tenant_id == tenant
        ).order_by(NotificationDelivery.channel)
        return list((await session.execute(statement)).scalars().all())


async def audit_rows(db, tenant: str, action: str) -> list[AuditLog]:
    async with db() as session:
        statement = select(AuditLog).where(
            AuditLog.tenant_id == tenant, AuditLog.action == action
        )
        return list((await session.execute(statement)).scalars().all())


async def test_dispatch_without_route_sends_nothing(db, tenant, monkeypatch):
    """默认不外发：没有配置路由就什么都不投递，也不留台账。"""
    monkeypatch.setattr(settings, "NOTIFICATION_ROUTES", {})
    async with db() as session:
        with tenant_context(tenant):
            results = await notifications.dispatch(session, message(tenant))
            await session.commit()
    assert results == []
    assert await ledger(db, tenant) == []


async def test_configured_route_records_in_app_delivery_and_is_idempotent(
    db, tenant, monkeypatch
):
    """站内渠道按路由投递：台账留痕 + 同键重放不重复外发。"""
    monkeypatch.setattr(
        settings, "NOTIFICATION_ROUTES", {EVENT_CHANNEL_SELF_TEST: [CHANNEL_IN_APP]}
    )
    async with db() as session:
        with tenant_context(tenant):
            first = await notifications.dispatch(
                session, message(tenant, dedup_key="dedup-inapp")
            )
            await session.commit()
    assert [
        (result.channel, result.status, result.attempts, result.skipped) for result in first
    ] == [(CHANNEL_IN_APP, STATUS_SENT, 1, False)]

    async with db() as session:
        with tenant_context(tenant):
            replay = await notifications.dispatch(
                session, message(tenant, dedup_key="dedup-inapp")
            )
            await session.commit()
    assert [(result.status, result.skipped) for result in replay] == [(STATUS_SENT, True)]

    rows = await ledger(db, tenant)
    assert len(rows) == 1 and rows[0].status == STATUS_SENT and rows[0].delivered_at

    # 去重命中不重复写审计：补偿扫描会反复重放，审计只记真实投递事实，避免刷表。
    audits = await audit_rows(db, tenant, "notification_dispatch")
    assert len(audits) == 1 and audits[0].result == "success"


async def test_flaky_channel_retries_until_success(db, tenant, monkeypatch):
    """失败重试：前两次失败、第三次成功，最终记一次发送并保留尝试次数。"""
    channel = FlakyChannel(fail_times=2)
    register_channel(channel)
    monkeypatch.setattr(
        settings, "NOTIFICATION_ROUTES", {EVENT_CHANNEL_SELF_TEST: [channel.name]}
    )
    monkeypatch.setattr(settings, "NOTIFICATION_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_SECONDS", 0)

    async with db() as session:
        with tenant_context(tenant):
            results = await notifications.dispatch(
                session, message(tenant, dedup_key="dedup-flaky")
            )
            await session.commit()

    assert channel.attempts == [1, 2, 3]
    assert [(result.status, result.attempts, result.error) for result in results] == [
        (STATUS_SENT, 3, None)
    ]
    rows = await ledger(db, tenant)
    assert len(rows) == 1 and rows[0].attempts == 3 and rows[0].status == STATUS_SENT


async def test_exhausted_retries_keep_failure_class_without_raising(db, tenant, monkeypatch):
    """重试用尽：不抛异常、不静默丢弃，台账与审计都留下失败分类（不含异常原文）。"""
    channel = BrokenChannel()
    register_channel(channel)
    monkeypatch.setattr(
        settings, "NOTIFICATION_ROUTES", {EVENT_CHANNEL_SELF_TEST: [channel.name]}
    )
    monkeypatch.setattr(settings, "NOTIFICATION_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_SECONDS", 0)

    async with db() as session:
        with tenant_context(tenant):
            results = await notifications.dispatch(
                session, message(tenant, dedup_key="dedup-broken")
            )
            await session.commit()

    expected_error = f"{ERROR_DELIVERY_FAILED}:TimeoutError"
    assert channel.attempts == [1, 2]
    assert [(result.status, result.attempts, result.error) for result in results] == [
        (STATUS_FAILED, 2, expected_error)
    ]
    rows = await ledger(db, tenant)
    assert len(rows) == 1 and rows[0].status == STATUS_FAILED
    assert rows[0].last_error == expected_error
    assert "synthetic timeout" not in (rows[0].last_error or "")

    audits = await audit_rows(db, tenant, "notification_dispatch")
    assert len(audits) == 1 and audits[0].result == "failed"


async def test_unknown_and_unconfigured_channels_are_recorded_not_ignored(
    db, tenant, monkeypatch
):
    """未登记渠道与未配置渠道都要留痕：运维看得见“为什么没发出去”。"""
    unconfigured = UnconfiguredChannel()
    register_channel(unconfigured)
    monkeypatch.setattr(
        settings,
        "NOTIFICATION_ROUTES",
        {EVENT_CHANNEL_SELF_TEST: ["smtp-not-registered", unconfigured.name]},
    )
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_SECONDS", 0)

    async with db() as session:
        with tenant_context(tenant):
            results = await notifications.dispatch(
                session, message(tenant, dedup_key="dedup-missing")
            )
            await session.commit()

    assert {(result.channel, result.error) for result in results} == {
        ("smtp-not-registered", ERROR_UNKNOWN_CHANNEL),
        (unconfigured.name, ERROR_NOT_CONFIGURED),
    }
    assert unconfigured.attempts == []  # 未配置就不该真的调用
    rows = await ledger(db, tenant)
    assert {row.last_error for row in rows} == {
        ERROR_UNKNOWN_CHANNEL,
        ERROR_NOT_CONFIGURED,
    }
    assert all(row.status == STATUS_FAILED for row in rows)


async def test_dedup_key_is_derived_from_content_when_absent(db, tenant, monkeypatch):
    """未显式给去重键时按内容派生：同一内容重放不会重复外发。"""
    channel = RecordingChannel()
    register_channel(channel)
    monkeypatch.setattr(
        settings, "NOTIFICATION_ROUTES", {EVENT_CHANNEL_SELF_TEST: [channel.name]}
    )
    monkeypatch.setattr(settings, "NOTIFICATION_BACKOFF_SECONDS", 0)

    for _ in range(2):
        async with db() as session:
            with tenant_context(tenant):
                await notifications.dispatch(session, message(tenant))
                await session.commit()

    assert len(channel.messages) == 1
    assert len(await ledger(db, tenant)) == 1


async def test_registered_in_app_channel_is_the_shipped_default():
    """出厂即登记站内渠道；渠道清单可直接呈现给运维。"""
    described = {item["name"]: item for item in notifications.registry.describe()}
    assert CHANNEL_IN_APP in described
    assert described[CHANNEL_IN_APP]["configured"] is True
