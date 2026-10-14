"""实际 HTTP 和 SQLite ORM 验证本人关联、私有原件及重试；无外部服务。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth, member_self, qa
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.deps import get_current_user
from app.models.audit import AuditLog
from app.models.member import MemberMaterial, MemberProfile
from app.models.org import OrgUnit
from app.models.qa_session import QASession
from app.models.user import User, UserRole

pytestmark = pytest.mark.integration


class AsyncAdapter:
    """以真实同步 SQLite Session 执行测试中的异步路由。"""

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


def actor(identifier="self", role=UserRole.MEMBER, tenant="tenant-a", org="branch-a"):
    return User(
        id=identifier,
        username=identifier,
        name="合成党员",
        role=role,
        tenant_id=tenant,
        org_unit_id=org,
        is_active=True,
        is_deleted=False,
    )


@pytest.fixture
def workspace():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            OrgUnit.__table__,
            MemberProfile.__table__,
            MemberMaterial.__table__,
            AuditLog.__table__,
            QASession.__table__,
        ],
    )
    with Session(engine, expire_on_commit=False) as session:
        for identifier, tenant, org in [
            ("self", "tenant-a", "branch-a"),
            ("other", "tenant-a", "branch-b"),
            ("foreign", "tenant-b", "branch-a"),
            ("unlinked", "tenant-a", "branch-a"),
        ]:
            session.add(
                User(
                    id=identifier,
                    username=identifier,
                    name="合成党员",
                    password_hash="synthetic",
                    role=UserRole.MEMBER,
                    tenant_id=tenant,
                    org_unit_id=org,
                )
            )
        session.flush()
        for org in ["branch-a", "branch-b"]:
            session.add(
                OrgUnit(id=org, tenant_id="tenant-a", name=org, org_type="branch", path=f"/{org}")
            )
        for identifier, owner, tenant, org in [
            ("self-profile", "self", "tenant-a", "branch-a"),
            ("other-profile", "other", "tenant-a", "branch-b"),
            ("foreign-profile", "self", "tenant-b", "branch-a"),
            ("unlinked-profile", None, "tenant-a", "branch-a"),
        ]:
            session.add(
                MemberProfile(
                    id=identifier,
                    user_id=owner,
                    tenant_id=tenant,
                    name="同名合成党员",
                    org_name=org,
                    org_unit_id=org,
                    current_stage="member",
                    stage_joined_on=date(2020, 1, 1),
                    materials=["组织已核验材料"],
                )
            )
        session.commit()
        state = SimpleNamespace(user=actor(), db=AsyncAdapter(session), session=session)
        application = FastAPI()
        for router in [member_self.router, auth.router, qa.router]:
            application.include_router(router, prefix="/api/v1")
        application.dependency_overrides[get_current_user] = lambda: state.user

        async def database():
            try:
                yield state.db
                session.commit()
            except Exception:
                session.rollback()
                raise

        application.dependency_overrides[get_db] = database
        with TestClient(application) as client:
            state.client = client
            yield state
    engine.dispose()


def submit(workspace, key=None, **overrides):
    fields = {
        "title": "个人思想汇报",
        "category": "thought_report",
        "description": "合成私有说明",
        "submission_key": str(key or uuid4()),
    }
    name = overrides.pop("file_name", "本人材料.txt")
    content = overrides.pop("content", b"synthetic private material")
    fields.update(overrides)
    return workspace.client.post(
        "/api/v1/member/self/materials", data=fields, files={"file": (name, content, "text/plain")}
    )


def test_member_permissions_and_qa_history_remain_available(workspace):
    codes = workspace.client.get("/api/v1/auth/codes").json()["data"]
    assert set(codes) == {
        "qa.ask",
        "knowledge.query",
        "member.self_query",
        "member.material_submit",
    }
    assert workspace.client.get("/api/v1/qa/sessions").status_code == 200


def test_applicant_has_the_same_self_service_boundary_as_member(workspace):
    """申请人与其档案同样可用：权限必须不窄于党员，否则申请人无法使用本人功能。"""
    workspace.session.add(
        User(
            id="applicant-1",
            username="applicant-1",
            name="合成申请人",
            password_hash="synthetic",
            role=UserRole.APPLICANT,
            tenant_id="tenant-a",
            org_unit_id="branch-a",
        )
    )
    workspace.session.flush()
    workspace.session.add(
        MemberProfile(
            id="applicant-profile",
            user_id="applicant-1",
            tenant_id="tenant-a",
            name="合成申请人",
            org_name="branch-a",
            org_unit_id="branch-a",
            current_stage="applicant",
            stage_joined_on=date(2026, 1, 1),
            materials=[],
        )
    )
    workspace.session.commit()
    workspace.user = actor("applicant-1", UserRole.APPLICANT)

    codes = set(workspace.client.get("/api/v1/auth/codes").json()["data"])
    assert codes == {"qa.ask", "knowledge.query", "member.self_query", "member.material_submit"}
    archive = workspace.client.get("/api/v1/member/self/archive")
    assert archive.status_code == 200
    assert archive.json()["data"]["profile"]["id"] == "applicant-profile"
    assert workspace.client.get("/api/v1/member/self/materials").status_code == 200
    assert submit(workspace).status_code == 200


def test_self_archive_uses_account_not_same_name_or_supplied_id(workspace):
    data = workspace.client.get(
        "/api/v1/member/self/archive",
        params={"user_id": "other", "tenant_id": "tenant-b", "profile_id": "other-profile"},
    ).json()["data"]
    assert data["profile"]["id"] == "self-profile"
    assert data["profile"]["stage"] == "member"
    assert data["max_upload_size"] == settings.MAX_UPLOAD_SIZE


def test_unlinked_account_never_matches_a_same_name_profile(workspace):
    workspace.user = actor("unlinked")
    assert workspace.client.get("/api/v1/member/self/archive").json()["data"]["profile"] is None
    assert submit(workspace).status_code == 409
    assert workspace.session.scalar(select(func.count(MemberMaterial.id))) == 0


@pytest.mark.parametrize("changed", ["org", "deleted", "inactive", "deleted_org"])
def test_inactive_or_wrong_org_archive_is_not_available(workspace, changed):
    profile = workspace.session.get(MemberProfile, "self-profile")
    if changed == "org":
        workspace.user.org_unit_id = "branch-b"
    elif changed == "deleted":
        profile.is_deleted = True
    elif changed == "deleted_org":
        workspace.session.get(OrgUnit, "branch-a").is_deleted = True
    else:
        profile.is_active = False
    workspace.session.commit()
    assert workspace.client.get("/api/v1/member/self/archive").json()["data"]["profile"] is None
    assert submit(workspace).status_code == 409


def test_submit_persists_original_and_audit_without_changing_official_archive(workspace):
    response = submit(workspace, user_id="other", tenant_id="tenant-b", profile_id="other-profile")
    assert response.status_code == 200
    record = response.json()["data"]
    assert record["status"] == "submitted" and "content" not in record
    stored = workspace.session.get(MemberMaterial, record["id"])
    assert (stored.user_id, stored.tenant_id, stored.profile_id) == (
        "self",
        "tenant-a",
        "self-profile",
    )
    assert stored.content == b"synthetic private material"
    profile = workspace.session.get(MemberProfile, "self-profile")
    assert profile.materials == ["组织已核验材料"] and profile.current_stage == "member"
    audit = workspace.session.scalars(select(AuditLog)).one()
    assert set(audit.new_value) == {"sha256", "bytes"}
    assert audit.new_value["bytes"] > 0
    assert "私有" not in str(audit.dict())


def test_materials_are_private_and_original_download_is_safe(workspace):
    identifier = submit(workspace).json()["data"]["id"]
    own = workspace.client.get(f"/api/v1/member/self/materials/{identifier}/file")
    assert own.content == b"synthetic private material"
    assert own.headers["content-type"] == "application/octet-stream"
    assert own.headers["x-content-type-options"] == "nosniff"
    assert own.headers["cache-control"] == "no-store"
    assert own.headers["content-disposition"].startswith("attachment;")
    for account in [actor("other", org="branch-b"), actor("foreign", tenant="tenant-b")]:
        workspace.user = account
        assert workspace.client.get("/api/v1/member/self/materials").json()["data"]["items"] == []
        assert (
            workspace.client.get(f"/api/v1/member/self/materials/{identifier}/file").status_code
            == 404
        )


def test_retry_and_unique_constraint_race_do_not_duplicate_material(workspace, monkeypatch):
    key = uuid4()
    original = submit(workspace, key=key).json()["data"]
    assert submit(workspace, key=key).json()["data"]["id"] == original["id"]
    real_execute = workspace.db.execute
    suppressed = False

    async def race(statement):
        nonlocal suppressed
        if not suppressed and statement.column_descriptions[0].get("entity") is MemberMaterial:
            suppressed = True
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result
        return await real_execute(statement)

    monkeypatch.setattr(workspace.db, "execute", race)
    assert submit(workspace, key=key).json()["data"]["id"] == original["id"]
    assert workspace.session.scalar(select(func.count(MemberMaterial.id))) == 1
    assert submit(workspace, key=key, content=b"different").status_code == 409


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"title": "  "}, 422),
        ({"category": "unsupported"}, 422),
        ({"description": "x" * 2001}, 422),
        ({"content": b""}, 422),
        ({"file_name": "payload.html"}, 415),
        ({"file_name": "../secret.txt"}, 422),
    ],
)
def test_invalid_submission_does_not_persist(workspace, overrides, status):
    assert submit(workspace, **overrides).status_code == status
    assert workspace.session.scalar(select(func.count(MemberMaterial.id))) == 0


def test_upload_size_and_pagination_limits(workspace, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE", 4)
    assert submit(workspace, content=b"12345").status_code == 413
    assert submit(workspace, content=b"1234").status_code == 200
    assert (
        workspace.client.get("/api/v1/member/self/materials", params={"page": 0}).status_code == 422
    )
    assert (
        workspace.client.get("/api/v1/member/self/materials", params={"page_size": 101}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "role",
    [role for role in UserRole if role not in (UserRole.MEMBER, UserRole.APPLICANT)],
)
def test_self_service_is_specific_to_member_and_applicant_roles(workspace, role):
    workspace.user = actor(role=role)
    assert workspace.client.get("/api/v1/member/self/archive").status_code == 403
    assert workspace.client.get("/api/v1/member/self/materials").status_code == 403
    assert submit(workspace).status_code == 403


def test_organization_can_bind_an_applicant_account(workspace):
    """申请人账号同样可以被关联到本人档案，否则申请人永远看不到自己的档案。"""
    workspace.session.add(
        User(
            id="applicant-2",
            username="applicant-2",
            name="合成申请人",
            password_hash="synthetic",
            role=UserRole.APPLICANT,
            tenant_id="tenant-a",
            org_unit_id="branch-a",
        )
    )
    workspace.session.commit()
    workspace.user = actor("secretary", UserRole.BRANCH_SECRETARY)
    bound = workspace.client.put(
        "/api/v1/member/roster/unlinked-profile/account", json={"username": "applicant-2"}
    )
    assert bound.status_code == 200 and bound.json()["data"]["user_id"] == "applicant-2"

    workspace.user = actor("applicant-2", UserRole.APPLICANT)
    archive = workspace.client.get("/api/v1/member/self/archive").json()["data"]
    assert archive["profile"]["id"] == "unlinked-profile"


def test_organization_can_bind_account_and_read_only_authorized_submissions(workspace):
    identifier = submit(workspace).json()["data"]["id"]
    workspace.user = actor("secretary", UserRole.BRANCH_SECRETARY)
    bound = workspace.client.put(
        "/api/v1/member/roster/unlinked-profile/account", json={"username": "unlinked"}
    )
    assert bound.status_code == 200 and bound.json()["data"]["user_id"] == "unlinked"
    assert (
        workspace.client.get("/api/v1/member/roster/self-profile/materials").json()["data"][
            "items"
        ][0]["id"]
        == identifier
    )
    assert (
        workspace.client.get(
            f"/api/v1/member/roster/self-profile/materials/{identifier}/file"
        ).status_code
        == 200
    )
    assert workspace.client.get("/api/v1/member/roster/other-profile/materials").status_code == 404
    assert (
        workspace.client.put(
            "/api/v1/member/roster/other-profile/account", json={"username": "other"}
        ).status_code
        == 404
    )
    workspace.user = actor("unlinked")
    assert (
        workspace.client.get("/api/v1/member/self/archive").json()["data"]["profile"]["id"]
        == "unlinked-profile"
    )


def test_binding_cannot_overwrite_or_duplicate_existing_account(workspace):
    workspace.user = actor("secretary", UserRole.BRANCH_SECRETARY)
    assert (
        workspace.client.put(
            "/api/v1/member/roster/self-profile/account", json={"username": "unlinked"}
        ).status_code
        == 409
    )
    assert (
        workspace.client.put(
            "/api/v1/member/roster/unlinked-profile/account", json={"username": "self"}
        ).status_code
        == 409
    )
    assert (
        workspace.client.put(
            "/api/v1/member/roster/unlinked-profile/account", json={"username": "foreign"}
        ).status_code
        == 422
    )
    workspace.user = actor()
    assert (
        workspace.client.put(
            "/api/v1/member/roster/unlinked-profile/account", json={"username": "unlinked"}
        ).status_code
        == 403
    )
