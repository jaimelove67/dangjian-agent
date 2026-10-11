"""Native governance HTTP acceptance with signed tokens, live identities and isolated data."""

import base64
import os
import uuid
from decimal import Decimal

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.security import create_access_token
from app.core.tenant import bypass_tenant_filter
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.governance import ModelUsage
from app.models.member import MemberCultivation, MemberProfile
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import job_service
from app.services.member_service import _load_scoring_rules
from tests.integration import test_module6_governance as fixtures

governance_url = fixtures.governance_url
native = fixtures.native
seed = fixtures.seed

pytestmark = pytest.mark.integration


@pytest.fixture
async def http_case(native, monkeypatch, tmp_path):
    _, maker = native
    async with maker() as db:
        school, root, branch, author, admin = await seed(db)
        other_school, _, _, _, other_admin = await seed(db)
    client_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await client_redis.ping()
    monkeypatch.setattr(redis_manager, "_redis", client_redis)
    monkeypatch.setattr(settings, "AUDIT_SPOOL_DIR", str(tmp_path / "audit"))

    async def database():
        async with maker() as db:
            yield db

    assert get_db not in app.dependency_overrides
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://isolated-test"
        ) as client:
            yield {
                "http": client,
                "maker": maker,
                "school": school,
                "root": root,
                "branch": branch,
                "author": author,
                "admin": admin,
                "other_school": other_school,
                "other_admin": other_admin,
            }
    finally:
        app.dependency_overrides.pop(get_db, None)
        await client_redis.aclose()


def authorization(user, role=None):
    token = create_access_token(str(user.id), str(user.tenant_id), role or user.role)
    return {"Authorization": "Bearer " + token}


async def call(case, actor, method, path, body=None, status=200, headers=None):
    result = await case["http"].request(
        method, "/api/v1" + path, json=body, headers=headers or authorization(actor)
    )
    assert result.status_code == status, result.text
    if status == 200:
        assert result.json()["code"] == 0, result.text
        return result.json()["data"]
    return result


async def test_school_admin_http_configuration_identity_conflicts_and_safe_responses(http_case):
    c, admin = http_case, http_case["admin"]
    policy = await call(c, admin, "GET", "/admin/governance")
    assert policy["admission"]["status"] == "pending"
    policy["values"]["prompt_versions"] = {"qa": "v2"}
    update = {
        "expected_version": policy["version"],
        "reason": "isolated test revision",
        "values": policy["values"],
    }
    changed = await call(c, admin, "PATCH", "/admin/governance", update)
    assert changed["version"] == policy["version"] + 1
    await call(c, admin, "PATCH", "/admin/governance", update, status=409)
    history = await call(c, admin, "GET", "/admin/config-history")
    assert history["items"][0]["version"] == changed["version"]
    assert history["items"][0]["actor_id"] == admin.id
    tenants = await call(c, admin, "GET", "/admin/tenants")
    assert {row["id"] for row in tenants["items"]} == {c["school"].id}
    await call(
        c,
        admin,
        "POST",
        "/admin/tenants",
        {"name": "cannot create school", "parent_id": c["school"].id},
        status=403,
    )
    department = await call(
        c,
        admin,
        "POST",
        "/admin/organizations",
        {"name": "isolated department", "org_type": "department", "parent_id": c["root"].id},
    )
    moved = await call(
        c, admin, "PATCH", "/admin/organizations/" + c["branch"].id, {"parent_id": department["id"]}
    )
    assert moved["path"] == department["path"] + "/" + c["branch"].id
    await call(
        c,
        admin,
        "PATCH",
        "/admin/organizations/" + department["id"],
        {"parent_id": c["branch"].id},
        status=422,
    )
    body = {
        "username": "native_" + uuid.uuid4().hex,
        "name": "synthetic admin",
        "password": "Isolated_Test_2026!",
        "role": "department_admin",
        "org_unit_id": department["id"],
    }
    user = await call(c, admin, "POST", "/admin/users", body)
    assert "password" not in str(user) and "hash" not in str(user)
    await call(c, admin, "POST", "/admin/users", body, status=409)
    await call(
        c, admin, "PATCH", "/admin/users/" + user["id"], {"role": "school_admin"}, status=422
    )
    users = await call(c, admin, "GET", "/admin/users")
    assert (
        next(row for row in users["items"] if row["id"] == user["id"])["role"] == "department_admin"
    )
    await call(
        c, admin, "GET", "/admin/organizations?tenant_id=" + c["other_school"].id, status=403
    )
    await call(
        c,
        admin,
        "GET",
        "/admin/metrics",
        status=403,
        headers=authorization(admin, UserRole.SYSTEM_ADMIN),
    )


async def test_same_signed_token_observes_role_user_and_ancestor_revocation(http_case):
    c, admin = http_case, http_case["admin"]
    created = await call(
        c,
        admin,
        "POST",
        "/admin/users",
        {
            "username": "native_" + uuid.uuid4().hex,
            "name": "synthetic school admin",
            "password": "Isolated_Test_2026!",
            "role": "school_admin",
            "org_unit_id": c["root"].id,
        },
    )
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            actor = await db.get(User, created["id"])
    same_token = authorization(actor)
    await call(c, actor, "GET", "/admin/users", headers=same_token)
    await call(
        c,
        admin,
        "PATCH",
        "/admin/users/" + actor.id,
        {"role": "member", "org_unit_id": c["branch"].id},
    )
    await call(c, actor, "GET", "/admin/users", headers=same_token, status=403)
    await call(c, actor, "GET", "/admin/jobs", headers=same_token)
    await call(c, admin, "PATCH", "/admin/users/" + actor.id, {"is_active": False})
    await call(c, actor, "GET", "/admin/jobs", headers=same_token, status=403)
    await call(c, admin, "PATCH", "/admin/users/" + admin.id, {"is_active": False}, status=409)
    author_token = authorization(c["author"])
    await call(c, c["author"], "GET", "/admin/jobs", headers=author_token)
    await call(c, admin, "PATCH", "/admin/organizations/" + c["branch"].id, {"is_active": False})
    await call(c, c["author"], "GET", "/admin/jobs", headers=author_token, status=403)


async def test_http_reviews_reject_self_stale_cross_school_and_freeze_current_evidence(http_case):
    c = http_case
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            profile = MemberProfile(
                tenant_id=c["school"].id,
                name="synthetic candidate",
                org_name=c["branch"].name,
                org_unit_id=c["branch"].id,
            )
            db.add(profile)
            await db.flush()
            for category in _load_scoring_rules()["weights"]:
                db.add(
                    MemberCultivation(
                        tenant_id=c["school"].id,
                        profile_id=profile.id,
                        org_unit_id=c["branch"].id,
                        category=category,
                        score=Decimal("50"),
                        period="2026",
                        source_note="synthetic test evidence",
                    )
                )
            await db.commit()
    body = {"source_kind": "score", "source_id": profile.id, "year": 2026}
    review = await call(c, c["author"], "POST", "/admin/reviews", body)
    decision = {
        "decision": "approved",
        "source_version": review["source_version"],
        "opinion": "synthetic human check",
    }
    path = "/admin/reviews/" + review["id"]
    await call(c, c["author"], "POST", path + "/decision", decision, status=403)
    await call(
        c,
        c["admin"],
        "POST",
        path + "/decision",
        {**decision, "source_version": "f" * 64},
        status=409,
    )
    await call(c, c["other_admin"], "GET", path, status=404)
    approved = await call(c, c["admin"], "POST", path + "/decision", decision)
    assert approved["status"] == "approved"
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            evidence = (
                (
                    await db.execute(
                        select(MemberCultivation).where(MemberCultivation.profile_id == profile.id)
                    )
                )
                .scalars()
                .first()
            )
            evidence.score = Decimal("80")
            await db.commit()
    stale = await call(c, c["admin"], "GET", path)
    assert stale["stale"] and stale["snapshot"] is None
    fresh = await call(c, c["author"], "POST", "/admin/reviews", body)
    assert fresh["id"] != review["id"]
    listing = await call(c, c["admin"], "GET", "/admin/reviews?status=pending")
    assert listing["total"] == 1
    missing = "/admin/reviews/" + str(uuid.uuid4())
    await call(c, c["admin"], "GET", missing, status=404)


async def test_jobs_are_actor_private_and_operations_use_only_school_durable_evidence(http_case):
    c = http_case
    body = {"kind": "member_reminders", "dedup_key": "bounded-http-retry"}
    job = await call(c, c["author"], "POST", "/admin/jobs", body)
    assert (await call(c, c["author"], "POST", "/admin/jobs", body))["id"] == job["id"]
    own = await call(c, c["author"], "GET", "/admin/jobs")
    assert [row["id"] for row in own["items"]] == [job["id"]]
    assert (await call(c, c["admin"], "GET", "/admin/jobs"))["items"] == []
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            db.add(
                ModelUsage(
                    tenant_id=c["school"].id,
                    request_id=uuid.uuid4().hex,
                    config_version=0,
                    model_type="llm",
                    model_name="synthetic-only",
                    result="success",
                    duration_seconds=0.5,
                )
            )
            for _ in range(5):
                db.add(
                    AuditLog(
                        tenant_id=c["school"].id,
                        user_id=c["admin"].id,
                        user_name="synthetic",
                        action="export",
                        resource_type="synthetic",
                        request_id=uuid.uuid4().hex,
                        result="denied",
                        data_level="internal",
                    )
                )
            await db.commit()
    ops = await call(c, c["admin"], "GET", "/admin/operations")
    assert ops["jobs"]["queued"] == 1
    assert ops["admission"]["status"] == "pending"
    assert any(row["calls"] == 1 and row["type"] == "llm" for row in ops["model_usage"])
    assert any(row["result"] == "denied" and row["count"] >= 5 for row in ops["alerts"])
    foreign = await call(c, c["other_admin"], "GET", "/admin/operations")
    assert foreign["jobs"] == {} and foreign["model_usage"] == []
    assert await job_service.run_once()
    finished = await call(c, c["author"], "GET", "/admin/jobs")
    assert finished["items"][0]["status"] == "done"
    assert finished["items"][0]["result"] == {"processed": 0}
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            completed = (
                (
                    await db.execute(
                        select(AuditLog).where(
                            AuditLog.resource_id == job["id"], AuditLog.action == "job_completed"
                        )
                    )
                )
                .scalars()
                .all()
            )
    assert len(completed) == 1


async def test_production_readiness_keeps_unconfirmed_school_and_models_unready(
    http_case, native, monkeypatch
):
    import app.db.session as sessions

    engine, maker = native
    monkeypatch.setattr(sessions, "engine", engine)
    monkeypatch.setattr(sessions, "async_session_maker", maker)
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "synthetic-readiness-only-secret-2026")
    monkeypatch.setenv(
        "FILE_ENCRYPTION_KEYS", '{"acceptance":"' + base64.b64encode(os.urandom(32)).decode() + '"}'
    )
    monkeypatch.setenv("FILE_ENCRYPTION_ACTIVE_KEY", "acceptance")
    response = await http_case["http"].get("/api/v1/health/ready")
    assert response.status_code == 503, response.text
    checks = response.json()["checks"]
    for dependency in ("database", "redis", "schema", "encryption", "audit_storage", "jwt_secret"):
        assert checks[dependency] == "healthy"
    assert checks["school_admission"] == "configuration_required"
    assert checks["runtime_role"] == "configuration_required"
    assert checks["models"] != "healthy"


async def test_encrypted_original_versions_survive_update_and_reject_foreign_downloads(
    http_case, monkeypatch, tmp_path
):
    c = http_case
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path / "originals"))
    identifier = "M6-HTTP-" + uuid.uuid4().hex
    path = "/api/v1/knowledge-docs/" + identifier
    initial = "第一条 合成公开验收规定。\n第二条 原件应保留版本。".encode()
    revised = "第一条 合成公开验收新规定。\n第二条 原件应保留历史版本。".encode()
    form = {
        "doc_id": identifier,
        "file_name": "initial.txt",
        "title": "合成公开验收规定",
        "issuer": "合成机构",
        "level": "school",
        "visibility": "school",
        "effective_date": "2026-01-01",
        "tags": "验收",
        "security_level": "public",
    }
    headers = authorization(c["admin"])
    created = await c["http"].post(
        "/api/v1/knowledge-docs",
        data=form,
        files={"file": ("initial.txt", initial)},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    updated = await c["http"].put(
        path + "/content",
        data={"expected_revision": "1"},
        files={"file": ("revised.txt", revised)},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    for revision, expected in ((1, initial), (2, revised)):
        download = await c["http"].get(path + f"/file?revision={revision}", headers=headers)
        assert download.status_code == 200 and download.content == expected
        foreign = await c["http"].get(
            path + f"/file?revision={revision}", headers=authorization(c["other_admin"])
        )
        assert foreign.status_code == 404
    conflict = await c["http"].put(
        path + "/content",
        data={"expected_revision": "1"},
        files={"file": ("stale.txt", initial)},
        headers=headers,
    )
    assert conflict.status_code == 409
    for filename, content, expected in (("empty.txt", b"", 422), ("bad.exe", b"binary", 415)):
        invalid = await c["http"].put(
            path + "/content",
            data={"expected_revision": "2"},
            files={"file": (filename, content)},
            headers=headers,
        )
        assert invalid.status_code == expected
    missing = await c["http"].get(path + "/file?revision=3", headers=headers)
    assert missing.status_code == 404
    encrypted_files = list((tmp_path / "originals").rglob("*.bin"))
    assert len(encrypted_files) == 2
    assert all(
        initial not in item.read_bytes() and revised not in item.read_bytes()
        for item in encrypted_files
    )


async def test_platform_scope_school_registration_and_process_metrics_require_real_platform(
    http_case,
):
    c = http_case
    platform_id = str(uuid.uuid4())
    platform_actor = User(
        id=str(uuid.uuid4()),
        tenant_id=platform_id,
        username="platform_" + uuid.uuid4().hex,
        name="synthetic platform admin",
        password_hash="synthetic",
        role=UserRole.SYSTEM_ADMIN,
        is_active=True,
    )
    async with c["maker"]() as db:
        with bypass_tenant_filter():
            db.add(
                Tenant(
                    id=platform_id,
                    tenant_id=platform_id,
                    tenant_type="platform",
                    name="synthetic platform",
                    path="/" + platform_id,
                    config={},
                    is_active=True,
                )
            )
            db.add(platform_actor)
            await db.commit()
    school = await call(
        c,
        platform_actor,
        "POST",
        "/admin/tenants",
        {"name": "synthetic school", "parent_id": platform_id},
    )
    department = await call(
        c,
        platform_actor,
        "POST",
        "/admin/tenants",
        {"name": "synthetic department", "tenant_type": "department", "parent_id": school["id"]},
    )
    await call(
        c,
        platform_actor,
        "POST",
        "/admin/tenants",
        {"name": "invalid branch", "tenant_type": "branch", "parent_id": platform_id},
        status=422,
    )
    listing = await call(c, platform_actor, "GET", "/admin/tenants")
    assert {row["id"] for row in listing["items"]} == {platform_id, school["id"], department["id"]}
    await call(c, platform_actor, "PATCH", "/admin/tenants/" + school["id"], {"is_active": False})
    await call(
        c,
        platform_actor,
        "PATCH",
        "/admin/tenants/" + platform_id,
        {"is_active": False},
        status=409,
    )
    metrics = await c["http"].get("/api/v1/admin/metrics", headers=authorization(platform_actor))
    assert metrics.status_code == 200 and "text/plain" in metrics.headers["content-type"]
    await call(c, c["admin"], "GET", "/admin/metrics", status=403)
