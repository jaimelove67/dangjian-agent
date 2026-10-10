"""实际鉴权入口的刷新重放、退出吊销及存储故障回归。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.core.token_revocation import TokenRevocationStore
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def exists(self, *keys):
        return sum(key in self.values for key in keys)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True


@pytest.fixture
def auth_client(monkeypatch):
    user = User(
        id="auth-user",
        tenant_id="auth-tenant",
        username="auth-user",
        name="合成用户",
        role=UserRole.MEMBER,
        is_active=True,
        is_deleted=False,
        password_hash=hash_password("synthetic-password", rounds=4),
    )

    async def execute(stmt):
        entity = stmt.column_descriptions[0].get("entity")
        return SimpleNamespace(scalar_one_or_none=lambda: user if entity is User else None)

    db = SimpleNamespace(execute=execute, add=lambda _: None, flush=AsyncMock(), commit=AsyncMock())
    cache = MemoryRedis()
    store = TokenRevocationStore(cache)
    monkeypatch.setattr("app.deps.get_token_revocation_store", lambda: store)
    monkeypatch.setattr("app.api.v1.auth.get_token_revocation_store", lambda: store)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), cache
    finally:
        app.dependency_overrides.clear()


def test_refresh_is_single_use_and_logout_revokes_whole_session(auth_client):
    client, _ = auth_client
    login = client.post(
        "/api/v1/auth/login", json={"username": "auth-user", "password": "synthetic-password"}
    )
    assert login.status_code == 200
    first = login.json()["data"]
    refresh_headers = {"Authorization": "Bearer " + first["refresh_token"]}
    refresh = client.post("/api/v1/auth/refresh", headers=refresh_headers)
    assert refresh.status_code == 200
    second = refresh.json()["data"]
    assert client.post("/api/v1/auth/refresh", headers=refresh_headers).status_code == 401
    access_headers = {"Authorization": "Bearer " + second["access_token"]}
    assert client.get("/api/v1/auth/me", headers=access_headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=access_headers).status_code == 200
    for access in (first["access_token"], second["access_token"]):
        assert (
            client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + access}).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"Authorization": "Bearer " + second["refresh_token"]}
        ).status_code
        == 401
    )


def test_revocation_storage_failure_does_not_accept_token(auth_client, monkeypatch):
    client, cache = auth_client
    token = client.post(
        "/api/v1/auth/login", json={"username": "auth-user", "password": "synthetic-password"}
    ).json()["data"]["access_token"]
    monkeypatch.setattr(cache, "exists", AsyncMock(side_effect=ConnectionError("synthetic outage")))
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 503
    assert response.json()["code"] == 50301


@pytest.mark.parametrize("operation", ["exists", "set"])
def test_login_does_not_issue_tokens_when_auth_storage_is_unusable(
    auth_client, monkeypatch, operation
):
    client, cache = auth_client
    monkeypatch.setattr(
        cache, operation, AsyncMock(side_effect=ConnectionError("synthetic outage"))
    )
    response = client.post(
        "/api/v1/auth/login", json={"username": "auth-user", "password": "synthetic-password"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == 50301
    assert "access_token" not in response.text
