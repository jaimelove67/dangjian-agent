"""用实际鉴权、HTTP 和 SQLite ORM 验证管理员开户；不连接业务库或 Redis。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin, auth
from app.core.config import settings, tenant_config
from app.core.security import create_access_token, hash_password, verify_password
from app.core.token_revocation import TokenRevocationStore
from app.db.base import Base
from app.db.session import get_db
from app.main import http_exception_handler, validation_exception_handler
from app.models.audit import AuditLog
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole

pytestmark = pytest.mark.integration


class AsyncAdapter:
    """异步路由通过实际 ORM 会话读写合成数据。"""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    def add(self, instance):
        self.session.add(instance)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


class MemoryRedis:
    """保留真实令牌签发与校验，只替换吊销存储。"""

    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def exists(self, *keys):
        return sum(key in self.values for key in keys)


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setattr(settings, "BCRYPT_ROUNDS", 4)
    store = TokenRevocationStore(MemoryRedis())
    monkeypatch.setattr("app.deps.get_token_revocation_store", lambda: store)
    monkeypatch.setattr("app.api.v1.auth.get_token_revocation_store", lambda: store)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(
        engine, tables=[User.__table__, Tenant.__table__, OrgUnit.__table__, AuditLog.__table__]
    )
    with Session(engine, expire_on_commit=False) as session:
        for tenant in ["account-tenant-a", "account-tenant-b"]:
            session.add(
                Tenant(
                    id=tenant,
                    tenant_id=tenant,
                    name="合成学校",
                    tenant_type="school",
                    path=f"/{tenant}",
                )
            )
        for identifier, tenant, kind, deleted in [
            ("school-a", "account-tenant-a", "school", False),
            ("department-a", "account-tenant-a", "department", False),
            ("branch-a", "account-tenant-a", "branch", False),
            ("deleted-a", "account-tenant-a", "branch", True),
            ("invalid-a", "account-tenant-a", "unknown", False),
            ("branch-b", "account-tenant-b", "branch", False),
        ]:
            session.add(
                OrgUnit(
                    id=identifier,
                    tenant_id=tenant,
                    name=f"合成{identifier}",
                    org_type=kind,
                    path=f"/{identifier}",
                    is_deleted=deleted,
                )
            )
        actor = User(
            id="account-root",
            tenant_id="account-tenant-a",
            username="account-root",
            name="合成管理员",
            password_hash=hash_password("root-synthetic-password"),
            role=UserRole.SYSTEM_ADMIN,
            org_unit_id="school-a",
            is_active=True,
        )
        session.add(actor)
        session.commit()
        token = create_access_token(subject=actor.id, tenant_id=actor.tenant_id, role=actor.role)
        state = SimpleNamespace(
            actor=actor,
            session=session,
            db=AsyncAdapter(session),
            headers={"Authorization": f"Bearer {token}"},
        )
        application = FastAPI()
        application.include_router(admin.router, prefix="/api/v1")
        application.include_router(auth.router, prefix="/api/v1")
        application.add_exception_handler(HTTPException, http_exception_handler)
        application.add_exception_handler(RequestValidationError, validation_exception_handler)

        async def database():
            try:
                yield state.db
                session.commit()
            except Exception:
                session.rollback()
                raise

        application.dependency_overrides[get_db] = database
        with TestClient(application, raise_server_exceptions=False) as client:
            state.client = client
            yield state
    tenant_config.reload("account-tenant-a")
    tenant_config.reload("account-tenant-b")
    engine.dispose()


def payload(**overrides):
    return {
        "username": "new-member",
        "name": "合成新党员",
        "password": "synthetic-password",
        "role": "member",
        "org_unit_id": "branch-a",
    } | overrides


def create(workspace, **overrides):
    return workspace.client.post(
        "/api/v1/admin/users", headers=workspace.headers, json=payload(**overrides)
    )


def test_organization_options_exclude_foreign_deleted_and_invalid_units(workspace):
    response = workspace.client.get("/api/v1/admin/org-units", headers=workspace.headers)
    assert response.status_code == 200
    assert {org["id"] for org in response.json()["data"]} == {
        "school-a",
        "department-a",
        "branch-a",
    }


@pytest.mark.parametrize("path", ["/admin/org-units", "/admin/users"])
def test_account_endpoints_require_authentication(workspace, path):
    if path.endswith("users"):
        response = workspace.client.post(f"/api/v1{path}", json=payload())
    else:
        response = workspace.client.get(f"/api/v1{path}")
    assert response.status_code == 401
    assert workspace.session.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize("role", [role for role in UserRole if role != UserRole.SYSTEM_ADMIN])
def test_other_roles_cannot_create_accounts_even_with_an_old_admin_token(workspace, role):
    workspace.actor.role = role
    workspace.session.commit()
    assert create(workspace).status_code == 403
    assert (
        workspace.client.get("/api/v1/admin/org-units", headers=workspace.headers).status_code
        == 403
    )
    assert workspace.session.scalar(select(func.count(User.id))) == 1
    assert workspace.session.scalar(select(func.count(AuditLog.id))) == 0


def test_created_account_is_hashed_audited_and_can_log_in(workspace):
    response = create(workspace, username="  new-member  ", name="  合成新党员  ")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["username"] == "new-member" and data["name"] == "合成新党员"
    assert data["org_name"] == "合成branch-a" and data["tenant_id"] == "account-tenant-a"
    assert "password" not in response.text
    stored = workspace.session.get(User, data["id"])
    assert stored.is_active and stored.role == UserRole.MEMBER
    assert stored.password_hash != "synthetic-password"
    assert verify_password("synthetic-password", stored.password_hash)
    audit = workspace.session.scalars(select(AuditLog)).one()
    assert (audit.user_id, audit.resource_type, audit.resource_id) == (
        "account-root",
        "user",
        stored.id,
    )
    assert set(audit.new_value) == {"sha256", "bytes"}
    assert audit.new_value["bytes"] > 0
    assert "password" not in str(audit.dict()) and stored.password_hash not in str(audit.dict())
    login = workspace.client.post(
        "/api/v1/auth/login", json={"username": "new-member", "password": "synthetic-password"}
    )
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    me = workspace.client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["data"]["id"] == stored.id
    assert (
        workspace.client.post(
            "/api/v1/admin/users", headers=headers, json=payload(username="escalated")
        ).status_code
        == 403
    )
    wrong_password = workspace.client.post(
        "/api/v1/auth/login", json={"username": "new-member", "password": "wrong-password"}
    )
    assert wrong_password.status_code == 401


def test_duplicate_username_is_rejected_without_creating_a_second_account(workspace):
    assert create(workspace, username="new-member").status_code == 201
    duplicate = create(workspace, username="new-member")
    assert duplicate.status_code == 409
    assert "synthetic-password" not in duplicate.text
    assert workspace.session.scalar(select(func.count(User.id))) == 2


@pytest.mark.parametrize(
    "role,org",
    [
        ("system_admin", "school-a"),
        ("school_admin", "school-a"),
        ("department_admin", "department-a"),
        ("branch_secretary", "branch-a"),
        ("organizer", "branch-a"),
        ("member", "branch-a"),
        ("applicant", "branch-a"),
    ],
)
def test_system_admin_can_assign_each_supported_role(workspace, role, org):
    response = create(workspace, role=role, org_unit_id=org)
    assert response.status_code == 201
    assert response.json()["data"]["role"] == role


@pytest.mark.parametrize("organization", ["branch-b", "deleted-a", "invalid-a", "missing"])
def test_foreign_deleted_or_missing_organization_is_rejected(workspace, organization):
    assert create(workspace, org_unit_id=organization).status_code == 403
    assert workspace.session.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize(
    "role,org",
    [("school_admin", "branch-a"), ("department_admin", "school-a"), ("member", "department-a")],
)
def test_role_must_match_organization_type(workspace, role, org):
    assert create(workspace, role=role, org_unit_id=org).status_code == 422
    assert workspace.session.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": "account-tenant-b"},
        {"id": "chosen"},
        {"is_active": False},
        {"password_hash": "chosen"},
    ],
)
def test_client_cannot_control_tenant_identity_or_password_hash(workspace, extra):
    response = create(workspace, **extra)
    assert response.status_code == 422
    assert "synthetic-password" not in response.text
    assert workspace.session.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"username": " "},
        {"username": "a b"},
        {"username": "x" * 51},
        {"name": " "},
        {"password": "short"},
        {"password": " " * 8},
        {"password": "中" * 25},
        {"role": "unknown"},
        {"org_unit_id": ""},
    ],
)
def test_invalid_fields_do_not_write_accounts_or_echo_passwords(workspace, invalid):
    response = create(workspace, **invalid)
    assert response.status_code == 422
    assert "synthetic-password" not in response.text
    assert "input" not in response.json()["detail"][0]
    assert workspace.session.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize("kind", ["active", "inactive", "deleted", "foreign", "race"])
def test_duplicate_username_does_not_overwrite_account_and_transaction_recovers(
    workspace, monkeypatch, kind
):
    existing = User(
        tenant_id="account-tenant-b" if kind == "foreign" else "account-tenant-a",
        username="new-member",
        name="原账号",
        password_hash="original-hash",
        role=UserRole.MEMBER,
        org_unit_id="branch-a",
        is_deleted=kind == "deleted",
        is_active=kind != "inactive",
    )
    workspace.session.add(existing)
    workspace.session.commit()
    if kind == "race":
        execute = workspace.db.execute

        async def hide_precheck(statement):
            # 模拟存在性查询之后另一个请求已提交同名账号，保留实际数据库唯一性检查。
            if statement.column_descriptions[0]["name"] == "id":
                return SimpleNamespace(scalar_one_or_none=lambda: None)
            return await execute(statement)

        monkeypatch.setattr(workspace.db, "execute", hide_precheck)
    response = create(workspace)
    assert response.status_code == 409
    assert "account-tenant-b" not in response.text
    workspace.session.refresh(existing)
    assert existing.name == "原账号" and existing.password_hash == "original-hash"
    assert workspace.session.scalar(select(func.count(AuditLog.id))) == 0
    assert create(workspace, username="different-member").status_code == 201


def test_audit_failure_rolls_back_account_creation(workspace, monkeypatch):
    monkeypatch.setattr(
        admin, "audit_operation", AsyncMock(side_effect=RuntimeError("synthetic audit failure"))
    )
    assert create(workspace).status_code == 500
    assert workspace.session.scalar(select(func.count(User.id))) == 1
    assert workspace.session.scalar(select(func.count(AuditLog.id))) == 0
