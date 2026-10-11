"""系统详情仅平台管理员可读，公开探针不暴露运行信息。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1 import health
from app.core import cache, security
from app.db import session as db_session
from app.deps import get_current_user
from app.llm import init_models
from app.models.user import User, UserRole

pytestmark = pytest.mark.security


@pytest.fixture
def system_client(monkeypatch):
    """使用实际路由和鉴权依赖，仅替换外部依赖探针。"""
    ping = AsyncMock()
    monkeypatch.setattr(cache, "redis_manager", SimpleNamespace(client=SimpleNamespace(ping=ping)))
    connection = AsyncMock()
    connection.execute.side_effect = [
        None,
        [
            (name,)
            for name in (
                "users",
                "tenants",
                "org_units",
                "knowledge_docs",
                "embedding_chunks",
                "audit_logs",
            )
        ],
    ]
    connection.scalar.return_value = True
    engine = MagicMock()
    engine.connect.return_value.__aenter__.return_value = connection
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(
        init_models,
        "model_readiness",
        lambda: {"chat": "configured", "embedding": "configured", "reranker": "configured"},
    )

    async def fake_readiness_details():
        checks = {"database": "healthy", "redis": "unknown", "schema": "healthy", "models": "healthy"}
        try:
            await ping()
            checks["redis"] = "healthy"
        except Exception:
            checks["redis"] = "unhealthy"
        ready = all(value == "healthy" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "checks": checks,
                "model_capabilities": {"chat": "configured"},
            },
        )

    monkeypatch.setattr(health, "_readiness_details", fake_readiness_details)
    application = FastAPI()
    application.include_router(health.router, prefix="/api/v1")
    with TestClient(application) as client:
        yield application, client, ping


@pytest.mark.parametrize(
    "path,body",
    [
        ("/health", {"status": "healthy"}),
        ("/health/live", {"status": "alive"}),
        ("/health/ready", {"status": "ready"}),
    ],
)
def test_public_probes_return_only_aggregate_status(system_client, path, body):
    _, client, _ = system_client
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200
    assert response.json() == body


def test_public_readiness_preserves_unavailable_status_without_details(system_client):
    _, client, ping = system_client
    ping.side_effect = RuntimeError("synthetic redis failure")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@pytest.mark.parametrize("path", ["/admin/health", "/admin/health/ready"])
def test_system_details_require_authentication(system_client, path):
    _, client, ping = system_client
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 401
    ping.assert_not_awaited()


@pytest.mark.parametrize("path", ["/admin/health", "/admin/health/ready"])
@pytest.mark.parametrize("role", [role for role in UserRole if role != UserRole.SYSTEM_ADMIN])
@pytest.mark.parametrize("has_system_permission", [False, True])
def test_other_roles_cannot_read_system_details(
    system_client, monkeypatch, path, role, has_system_permission
):
    application, client, ping = system_client
    if has_system_permission:
        profile = security.get_role_profile(role)
        monkeypatch.setitem(
            security.ROLE_PROFILES,
            role,
            replace(profile, permissions=profile.permissions | {security.Permission.CONFIG_MANAGE}),
        )
    application.dependency_overrides[get_current_user] = lambda: User(role=role)
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 403
    ping.assert_not_awaited()


def test_platform_admin_can_read_health_details(system_client):
    application, client, _ = system_client
    application.dependency_overrides[get_current_user] = lambda: User(role=UserRole.SYSTEM_ADMIN)
    response = client.get("/api/v1/admin/health")
    assert response.status_code == 200
    assert {"status", "service", "version", "environment"} == response.json().keys()


@pytest.mark.parametrize("ready", [True, False])
def test_platform_admin_can_read_dependency_details(system_client, ready):
    application, client, ping = system_client
    application.dependency_overrides[get_current_user] = lambda: User(role=UserRole.SYSTEM_ADMIN)
    if not ready:
        ping.side_effect = RuntimeError("synthetic redis failure")
    response = client.get("/api/v1/admin/health/ready")
    assert response.status_code == (200 if ready else 503)
    data = response.json()
    assert data["status"] == ("ready" if ready else "not_ready")
    assert data["checks"]["redis"] == ("healthy" if ready else "unhealthy")
    assert {"database", "redis", "schema", "models"} == data["checks"].keys()
    assert "model_capabilities" in data


@pytest.mark.parametrize("path", ["/admin/health", "/admin/health/ready"])
def test_platform_admin_access_is_based_on_role(system_client, monkeypatch, path):
    application, client, _ = system_client
    profile = security.get_role_profile(UserRole.SYSTEM_ADMIN)
    monkeypatch.setitem(
        security.ROLE_PROFILES,
        UserRole.SYSTEM_ADMIN,
        replace(profile, permissions=profile.permissions - {security.Permission.CONFIG_MANAGE}),
    )
    application.dependency_overrides[get_current_user] = lambda: User(role=UserRole.SYSTEM_ADMIN)
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200
