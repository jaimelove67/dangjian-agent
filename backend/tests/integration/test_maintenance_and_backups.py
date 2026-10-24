"""Real identity checks for maintenance requests; actual Redis admission quiescence."""

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from app.api.v1 import backups
from app.core import maintenance
from app.core.cache import redis_manager
from app.core.config import settings
from app.models.backup import BackupJob
from app.models.tenant import Tenant
from tests.integration.test_admin_accounts import workspace as account_workspace

workspace = account_workspace


@pytest.fixture
def case(workspace):
    BackupJob.__table__.create(workspace.session.get_bind())
    workspace.client.app.include_router(backups.router, prefix="/api/v1")
    workspace.session.get(Tenant, workspace.actor.tenant_id).tenant_type = "platform"
    workspace.actor.org_unit_id = None
    workspace.session.commit()
    return workspace


def test_disabled_maintenance_never_creates_fake_success(case, monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_API_ENABLED", False)
    response = case.client.post(
        "/api/v1/admin/backups",
        headers=case.headers,
        json={"name": "未启用维护", "dedup_key": str(uuid.uuid4()), "confirm_maintenance": True},
    )
    assert response.status_code == 503
    assert case.session.query(BackupJob).count() == 0


def test_job_idempotency_confirmation_and_no_arbitrary_restore_destination(case, monkeypatch):
    launched = []
    monkeypatch.setattr(
        "app.services.backup_service.capabilities",
        lambda: {"enabled": True, "database_tools": True, "restore_configured": False},
    )
    monkeypatch.setattr(
        "app.services.backup_service.launch",
        lambda tenant, record: launched.append((tenant, record)),
    )
    body = {
        "name": "合成真实任务登记",
        "dedup_key": "same-backup-request",
        "confirm_maintenance": False,
    }
    endpoint = "/api/v1/admin/backups"
    assert case.client.post(endpoint, headers=case.headers, json=body).status_code == 422
    body["confirm_maintenance"] = True
    assert (
        case.client.post(
            endpoint,
            headers=case.headers,
            json={**body, "database_url": "postgresql://arbitrary/destination"},
        ).status_code
        == 422
    )
    first = case.client.post(endpoint, headers=case.headers, json=body)
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "queued"
    again = case.client.post(endpoint, headers=case.headers, json=body)
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    assert len(launched) == 1 and case.session.query(BackupJob).count() == 1
    assert (
        case.client.post(
            endpoint, headers=case.headers, json={**body, "name": "不同参数"}
        ).status_code
        == 409
    )
    assert (
        case.client.post(
            endpoint, headers=case.headers, json={**body, "dedup_key": "another-request"}
        ).status_code
        == 409
    )
    case.session.get(Tenant, case.actor.tenant_id).tenant_type = "school"
    case.session.commit()
    assert case.client.get(endpoint, headers=case.headers).status_code == 403


async def test_real_redis_quiescence_drains_requests_blocks_new_work_and_releases(monkeypatch):
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    monkeypatch.setattr(redis_manager, "_redis", client)
    monkeypatch.setattr(
        settings, "DATABASE_URL", settings.DATABASE_URL + "?maintenance=" + uuid.uuid4().hex
    )
    monkeypatch.setattr(settings, "BACKUP_API_ENABLED", True)
    release, entered = asyncio.Event(), asyncio.Event()
    lock, active = maintenance.keys()
    try:
        assert await maintenance.enter()

        async def work():
            async with maintenance.quiescence():
                entered.set()
                await release.wait()

        task = asyncio.create_task(work())
        for _ in range(100):
            if await client.exists(lock):
                break
            await asyncio.sleep(0.01)
        assert await client.exists(lock)
        assert not entered.is_set()
        assert not await maintenance.enter()
        await maintenance.leave()
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert not await maintenance.enter()
        release.set()
        await asyncio.wait_for(task, timeout=2)
        assert await maintenance.enter()
        await maintenance.leave()
        assert int(await client.get(active) or 0) == 0
        with pytest.raises(RuntimeError):
            async with maintenance.quiescence():
                raise RuntimeError("synthetic backup failure")
        assert not await client.exists(lock)
    finally:
        # Only this test's randomly namespaced keys; never flush a shared Redis database.
        await client.delete(lock, active)
        await client.close()
