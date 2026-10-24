"""Real HTTP, credentials and ORM; no browser storage can grant password permissions."""

import pytest

from app.api.v1 import account_security, governance
from app.core.security import create_access_token, hash_password
from app.models.account_security import PasswordChange, PasswordRequest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration.test_admin_accounts import workspace as account_workspace

workspace = account_workspace


@pytest.fixture
def case(workspace):
    workspace.client.app.include_router(account_security.router, prefix="/api/v1")
    workspace.client.app.include_router(governance.router, prefix="/api/v1")
    platform = workspace.session.get(Tenant, "account-tenant-a")
    platform.tenant_type = "platform"
    workspace.actor.org_unit_id = None
    workspace.session.get(Tenant, "account-tenant-b").parent_id = platform.id
    workspace.session.add(
        User(
            id="password-member",
            tenant_id="account-tenant-b",
            username="password-member",
            name="合成改密对象",
            role=UserRole.MEMBER,
            org_unit_id="branch-b",
            password_hash=hash_password("synthetic-original", rounds=4),
            is_active=True,
        )
    )
    workspace.session.commit()
    return workspace


def login(case, password="synthetic-original"):
    response = case.client.post(
        "/api/v1/auth/login", json={"username": "password-member", "password": password}
    )
    assert response.status_code == 200
    return response.json()["data"]


def headers(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def change(case, tokens, current, password):
    return case.client.post(
        "/api/v1/auth/password-change",
        headers=headers(tokens),
        json={
            "current": current,
            "password": password,
            "confirmation": password,
        },
    )


def test_lifetime_change_and_atomic_approved_grant(case):
    first = login(case)
    assert change(case, first, "wrong-current", "synthetic-second").status_code == 422
    assert case.client.get("/api/v1/auth/password-state", headers=headers(first)).json()["data"][
        "canChange"
    ]
    assert change(case, first, "synthetic-original", "synthetic-second").status_code == 200
    assert case.client.get("/api/v1/auth/me", headers=headers(first)).status_code == 401
    assert (
        case.client.post(
            "/api/v1/auth/refresh", headers={"Authorization": "Bearer " + first["refresh_token"]}
        ).status_code
        == 401
    )
    second = login(case, "synthetic-second")
    assert change(case, second, "synthetic-second", "synthetic-third").status_code == 409
    application = case.client.post(
        "/api/v1/auth/password-requests",
        headers=headers(second),
        json={"reason": "合成测试的安全维护申请"},
    )
    assert application.status_code == 200
    row = application.json()["data"]
    assert (
        case.client.post(
            "/api/v1/auth/password-requests",
            headers=headers(second),
            json={"reason": "合成测试的重复申请"},
        ).status_code
        == 409
    )
    endpoint = f"/api/v1/admin/password-requests/{row['id']}/review?tenant_id=account-tenant-b"
    decision = {"decision": "approved", "comment": "已完成合成身份核验", "version": row["version"]}
    assert case.client.post(endpoint, headers=headers(second), json=decision).status_code == 403
    assert case.client.post(endpoint, headers=case.headers, json=decision).status_code == 200
    assert case.client.post(endpoint, headers=case.headers, json=decision).status_code == 409
    assert change(case, second, "wrong-current", "synthetic-third").status_code == 422
    state = case.client.get("/api/v1/auth/password-state", headers=headers(second)).json()["data"]
    assert state["approved"] and state["canChange"]
    assert change(case, second, "synthetic-second", "synthetic-third").status_code == 200
    third = login(case, "synthetic-third")
    state = case.client.get("/api/v1/auth/password-state", headers=headers(third)).json()["data"]
    assert state["used"] and not state["canChange"] and state["history"][0]["status"] == "consumed"
    case.session.expire_all()
    assert case.session.query(PasswordChange).count() == 2


def test_admin_reset_preserves_lifetime_usage_and_cancels_grant(case):
    first = login(case)
    assert change(case, first, "synthetic-original", "synthetic-second").status_code == 200
    second = login(case, "synthetic-second")
    result = case.client.post(
        "/api/v1/auth/password-requests",
        headers=headers(second),
        json={"reason": "用于核验管理员重置行为"},
    )
    row = result.json()["data"]
    response = case.client.patch(
        "/api/v1/admin/users/password-member?tenant_id=account-tenant-b",
        headers=case.headers,
        json={"password": "synthetic-admin-reset"},
    )
    assert response.status_code == 200
    case.session.expire_all()
    assert case.session.get(PasswordRequest, row["id"]).status == "cancelled"
    token = login(case, "synthetic-admin-reset")
    state = case.client.get("/api/v1/auth/password-state", headers=headers(token)).json()["data"]
    assert state["used"] and not state["canChange"]


def test_selected_session_revocation_preserves_other_login(case):
    first, second = login(case), login(case)
    listing = case.client.get(
        "/api/v1/admin/login-sessions?tenant_id=account-tenant-b", headers=case.headers
    )
    assert listing.status_code == 200
    sessions = listing.json()["data"]["items"]
    assert len(sessions) == 2
    session_id = sessions[0]["id"]
    assert (
        case.client.post(
            f"/api/v1/admin/login-sessions/{session_id}/revoke?tenant_id=account-tenant-b",
            headers=case.headers,
        ).status_code
        == 200
    )
    results = [
        case.client.get("/api/v1/auth/me", headers=headers(token)).status_code
        for token in [first, second]
    ]
    assert sorted(results) == [200, 401]
    results = [
        case.client.post(
            "/api/v1/auth/refresh", headers={"Authorization": "Bearer " + token["refresh_token"]}
        ).status_code
        for token in [first, second]
    ]
    assert sorted(results) == [200, 401]


def test_management_role_cannot_use_self_change_and_cross_school_sessions(case):
    assert case.client.get("/api/v1/auth/password-state", headers=case.headers).status_code == 403
    other = User(
        id="school-scope",
        tenant_id="account-tenant-b",
        username="scope-admin",
        name="合成学校管理员",
        password_hash="unused",
        role=UserRole.SCHOOL_ADMIN,
        org_unit_id="branch-b",
        is_active=True,
    )
    case.session.add(other)
    case.session.commit()
    token = create_access_token(subject=other.id, tenant_id=other.tenant_id, role=other.role)
    # A school administrator cannot read the platform's sessions even with a valid JWT.
    response = case.client.get(
        "/api/v1/admin/login-sessions?tenant_id=account-tenant-a",
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code in {403, 401}
