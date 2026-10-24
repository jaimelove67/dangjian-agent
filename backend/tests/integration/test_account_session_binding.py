"""Real login sessions must not survive an account security edit."""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole
from tests.integration.test_auth_lifecycle import auth_client as lifecycle_auth_client

auth_client = lifecycle_auth_client


@pytest.mark.parametrize("change", ["password", "role", "organization", "updated"])
def test_account_edit_invalidates_access_and_refresh_but_fresh_login_works(auth_client, change):
    client, _ = auth_client
    tokens = client.post(
        "/api/v1/auth/login",
        json={"username": "auth-user", "password": "synthetic-password"},
    ).json()["data"]
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    database = app.dependency_overrides[get_db]()
    user = asyncio.run(database.execute(select(User))).scalar_one_or_none()
    if change == "password":
        user.password_hash = hash_password("replacement-password", rounds=4)
    elif change == "role":
        user.role = UserRole.APPLICANT
    elif change == "organization":
        user.org_unit_id = "different-organization"
    else:
        user.updated_at = datetime(2026, 10, 24, 12, 0, 0)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"Authorization": "Bearer " + tokens["refresh_token"]}
        ).status_code
        == 401
    )
    if change == "organization":
        user.org_unit_id = None
    password = "replacement-password" if change == "password" else "synthetic-password"
    fresh = client.post("/api/v1/auth/login", json={"username": "auth-user", "password": password})
    assert fresh.status_code == 200
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + fresh.json()["data"]["access_token"]},
        ).status_code
        == 200
    )
