"""模块6审查反例：跨租户、撤权、历史泄漏、失败持久化及加密完整性。"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core import encryption, request_audit
from app.core.config import settings, tenant_config
from app.core.encryption import EncryptionError, atomic_write, seal, unseal
from app.core.logging_config import setup_logging
from app.core.tenant import tenant_context
from app.llm.base import DataLevel, DeploymentType, ModelConfig, ModelResponse, ModelType
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import DataLevelGateway
from app.llm.service import ModelService
from app.models.governance import HumanReview
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.governance import JobCreate, ReviewSubmit
from app.services import file_store
from app.services.identity_guard import ensure_active_identity
from app.services.identity_service import IdentityService
from app.services.review_service import ReviewService, fingerprint
from scripts.module6_backup import PURPOSE, unpack_bundle
from scripts.module6_bootstrap import Manifest
from scripts.module6_rotate_files import rotate
from scripts.module6_runtime_role import statements, validate_role


@pytest.fixture
def encrypted(monkeypatch):
    first = base64.b64encode(os.urandom(32)).decode()
    second = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("FILE_ENCRYPTION_KEYS", json.dumps({"old": first, "new": second}))
    monkeypatch.setenv("FILE_ENCRYPTION_ACTIVE_KEY", "old")
    monkeypatch.setattr(settings, "ENV", "testing")
    return first, second


def actor(role=UserRole.SCHOOL_ADMIN, tenant="school", id="actor"):
    return User(
        id=id,
        tenant_id=tenant,
        username=id,
        name="测试人员",
        role=role,
        is_active=True,
        is_deleted=False,
        org_unit_id=None,
    )


def result(row):
    return SimpleNamespace(scalar_one_or_none=lambda: row)


@pytest.mark.parametrize("tamper", ["aad", "ciphertext", "key"])
def test_encrypted_objects_reject_tamper_and_wrong_purpose(encrypted, monkeypatch, tamper):
    raw = seal(b"private material", "original:t:d:1")
    if tamper == "aad":
        with pytest.raises(EncryptionError):
            unseal(raw, "original:other:d:1")
    elif tamper == "ciphertext":
        value = json.loads(raw[len(encryption.MAGIC) :])
        value["ciphertext"] = base64.b64encode(b"changed").decode()
        with pytest.raises(EncryptionError):
            unseal(encryption.MAGIC + json.dumps(value).encode(), "original:t:d:1")
    else:
        monkeypatch.setenv("FILE_ENCRYPTION_KEYS", json.dumps({"new": encrypted[1]}))
        monkeypatch.setenv("FILE_ENCRYPTION_ACTIVE_KEY", "new")
        with pytest.raises(EncryptionError):
            unseal(raw, "original:t:d:1")


def test_original_versions_are_immutable_and_archives_can_retry_after_rollback(
    encrypted, monkeypatch, tmp_path
):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    first = file_store.save_original("tenant", "doc", 1, b"original", "a.txt")
    assert b"original" not in (tmp_path / first["path"]).read_bytes()
    assert file_store.read_original("tenant", "doc", 1, first["sha256"]) == b"original"
    replacement = file_store.save_original("tenant", "doc", 1, b"replacement", "a.txt")
    assert replacement["path"] != first["path"]
    assert file_store.read_original("tenant", "doc", 1, first["sha256"]) == b"original"
    assert file_store.read_original("tenant", "doc", 1, replacement["sha256"]) == b"replacement"
    with pytest.raises(EncryptionError):
        file_store.read_original("tenant", "doc", 1)
    assert file_store.save_original("tenant", "doc", 1, b"original", "a.txt") == first
    one = file_store.save_archive("tenant", "record", 2, {"id": "record", "archived_at": "one"})
    two = file_store.save_archive("tenant", "record", 2, {"id": "record", "archived_at": "two"})
    assert one["path"] != two["path"]
    assert (tmp_path / one["path"]).exists() and (tmp_path / two["path"]).exists()


def test_atomic_write_failure_leaves_no_published_or_partial_version(monkeypatch, tmp_path):
    monkeypatch.setattr(
        encryption.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        atomic_write(tmp_path / "version.bin", b"encrypted")
    assert list(tmp_path.iterdir()) == []


def test_key_rotation_validates_old_and_new_and_preserves_plaintext(
    encrypted, monkeypatch, tmp_path
):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    stored = file_store.save_original("t", "d", 1, b"original", "a.txt")
    original = (tmp_path / stored["path"]).read_bytes()
    monkeypatch.setenv("FILE_ENCRYPTION_ACTIVE_KEY", "new")
    assert rotate(tmp_path)["applied"] is False
    assert (tmp_path / stored["path"]).read_bytes() == original
    assert rotate(tmp_path, apply=True)["migrated"] == 1
    assert file_store.read_original("t", "d", 1, stored["sha256"]) == b"original"
    assert (
        json.loads((tmp_path / stored["path"]).read_bytes()[len(encryption.MAGIC) :])["key_id"]
        == "new"
    )


def test_rotation_stops_before_any_write_when_another_file_is_damaged(
    encrypted, monkeypatch, tmp_path
):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    first = file_store.save_original("t", "d", 1, b"original", "a.txt")
    path = tmp_path / first["path"]
    original = path.read_bytes()
    (path.parent / "broken__v1.bin").write_bytes(b"plain")
    with pytest.raises(EncryptionError):
        rotate(tmp_path, apply=True)
    assert path.read_bytes() == original


def test_pending_manifest_cannot_claim_official_school_or_role_mapping():
    assert Manifest().status == "pending"
    with pytest.raises(ValueError):
        Manifest.model_validate(
            {
                "status": "pending",
                "tenants": [
                    {
                        "key": "school",
                        "parent": "platform",
                        "name": "未确认学校",
                        "tenant_type": "school",
                    }
                ],
            }
        )


@pytest.mark.parametrize("bad", ["loop", "cross_tenant", "wrong_type", "duplicate"])
def test_official_manifest_checks_organization_tree_without_writing(bad):
    tenants = [
        {"key": "s", "parent": "platform", "name": "测试学校", "tenant_type": "school"},
        {"key": "s2", "parent": "platform", "name": "另一个测试学校", "tenant_type": "school"},
    ]
    orgs = [{"key": "root", "tenant": "s", "name": "测试根组织", "org_type": "school"}]
    child = {
        "key": "child",
        "tenant": "s",
        "name": "测试院系",
        "org_type": "department",
        "parent": "root",
    }
    if bad == "loop":
        child["parent"] = "child"
    if bad == "cross_tenant":
        child["tenant"] = "s2"
    if bad == "wrong_type":
        child["org_type"] = "school"
    if bad == "duplicate":
        child["key"] = "root"
    with pytest.raises(ValueError):
        Manifest.model_validate(
            {
                "status": "confirmed",
                "evidence": "仅单元测试合成依据",
                "platform": {
                    "name": "测试平台",
                    "username": "operator",
                    "operator_name": "测试操作者",
                    "password_env": "M6_TEST_PASSWORD",
                },
                "tenants": tenants,
                "organizations": [*orgs, child],
            }
        )


async def test_disabling_parent_blocks_active_child_and_cached_identity(monkeypatch):
    child = Tenant(
        id="child",
        tenant_id="child",
        tenant_type="department",
        parent_id="parent",
        is_active=True,
        is_deleted=False,
        config={},
        config_version=0,
    )
    parent = Tenant(
        id="parent",
        tenant_id="parent",
        tenant_type="school",
        parent_id=None,
        is_active=False,
        is_deleted=False,
        config={},
        config_version=0,
    )
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(child), result(parent)]))
    with pytest.raises(HTTPException) as caught:
        await ensure_active_identity(db, actor(tenant="child"))
    assert caught.value.status_code == 403


async def test_school_admin_cannot_demote_or_disable_existing_system_admin(monkeypatch):
    admin = actor()
    system = actor(UserRole.SYSTEM_ADMIN, id="system")
    tenant = Tenant(id="school", tenant_id="school", tenant_type="school", is_active=True)
    service = IdentityService(SimpleNamespace(), admin)
    monkeypatch.setattr(service, "tenant", AsyncMock(return_value=tenant))
    monkeypatch.setattr(service, "users", AsyncMock(return_value=[system, admin]))
    with pytest.raises(HTTPException) as caught:
        await service.save_user(
            "school", {"role": UserRole.SCHOOL_ADMIN, "is_active": False}, "system"
        )
    assert (
        caught.value.status_code == 403
        and system.role == UserRole.SYSTEM_ADMIN
        and system.is_active
    )


async def test_stale_review_hides_frozen_private_text(monkeypatch):
    service = ReviewService(SimpleNamespace(), actor())
    body = ReviewSubmit(source_kind="score", source_id="profile")
    row = HumanReview(
        id="review",
        tenant_id="school",
        source_kind="score",
        source_id="profile",
        source_version=fingerprint({"private": "old"}),
        status="approved",
        submitted_by="other",
        snapshot={"parameters": body.model_dump(), "content": {"private": "old"}},
        created_at=datetime.utcnow(),
    )
    monkeypatch.setattr(
        service, "current_source", AsyncMock(return_value=({"private": "new"}, None, None))
    )
    view = await service.view(row, include_content=True)
    assert view["stale"] and view["effective_status"] == "pending" and view["snapshot"] is None


async def test_study_restricted_response_cannot_be_replaced_by_raw_snapshot(monkeypatch):
    import app.services.review_service as module

    row = SimpleNamespace(id="record")
    fake = SimpleNamespace(
        initialize=AsyncMock(),
        activity=AsyncMock(return_value=row),
        activity_data=AsyncMock(return_value={"restricted": True, "transcript": ""}),
        _snapshot=AsyncMock(return_value={"transcript": "private marker"}),
    )
    fake.initialize.return_value = fake
    monkeypatch.setattr(module, "StudyService", lambda *_: fake)
    with pytest.raises(HTTPException) as caught:
        await ReviewService(SimpleNamespace(), actor()).source(
            ReviewSubmit(source_kind="study_activity", source_id="record")
        )
    assert caught.value.status_code == 404
    fake._snapshot.assert_not_awaited()


async def test_vote_review_uses_frozen_authorized_candidate_scope(monkeypatch):
    service = ReviewService(SimpleNamespace(), actor())
    body = ReviewSubmit(source_kind="vote", source_id="batch")
    bucket = {"agree": 1, "disagree": 0, "abstain": 0, "voted_by_me": True}
    frozen = {
        "batch_no": "batch",
        "round_no": 1,
        "tally": {"a": dict(bucket)},
        "voter_count": 1,
    }
    row = HumanReview(snapshot={"parameters": body.model_dump(), "content": frozen})
    delegate = SimpleNamespace(
        profile=AsyncMock(), vote_voter_count=AsyncMock(return_value=1)
    )
    fresh = {
        **frozen,
        "tally": {**frozen["tally"], "b": dict(bucket)},
        "voter_count": 2,
    }
    monkeypatch.setattr(service, "source", AsyncMock(return_value=(fresh, delegate, None)))
    current, _, _ = await service.current_source(row)
    assert current == frozen
    delegate.profile.assert_awaited_once_with("a", lock=False)
    # 无记名汇总下只能回服务端计数，不能靠返回的投票人身份再数。
    delegate.vote_voter_count.assert_awaited_once_with("batch", 1, ["a"])


async def test_independent_audit_failure_is_encrypted_and_replay_deduplicates(
    encrypted, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "AUDIT_SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(
        request_audit,
        "async_session_maker",
        lambda: (_ for _ in ()).throw(ConnectionError("offline")),
    )
    event = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "tenant_id": "tenant",
        "user_id": "actor",
        "user_name": "actor",
        "action": "query",
        "resource_type": "member",
        "resource_id": "member",
        "request_id": "request",
        "result": "denied",
        "data_level": "sensitive",
    }
    await request_audit.persist(event)
    path = next(tmp_path.glob("*.audit"))
    assert json.loads(unseal(path.read_bytes(), "audit:" + event["id"])) == event
    db = SimpleNamespace(execute=AsyncMock(return_value=result("already-in-database")))

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(request_audit, "async_session_maker", Session)
    assert await request_audit.replay() == 1
    assert not path.exists()


def test_structlog_and_gateway_never_log_private_context(encrypted, capsys, monkeypatch):
    import structlog

    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    setup_logging()
    structlog.get_logger("module6-test").error(
        "upstream_failed",
        context={"question": "PRIVATE_MATERIAL_MARKER"},
        error="PRIVATE_VENDOR_BODY",
    )
    model = ModelConfig(
        "outside",
        "outside",
        ModelType.LLM,
        DeploymentType.EXTERNAL,
        "test",
        endpoint="https://not-allowed.test",
    )
    with pytest.raises(Exception):
        DataLevelGateway().validate_and_block(
            DataLevel.SENSITIVE, model, {"question": "PRIVATE_MATERIAL_MARKER"}
        )
    output = capsys.readouterr().out
    assert "PRIVATE_MATERIAL_MARKER" not in output and "PRIVATE_VENDOR_BODY" not in output


@pytest.mark.parametrize("stream", [False, True])
async def test_streaming_and_fallback_have_bounded_total_timeout(monkeypatch, stream):
    class Provider:
        def get_model_id(self):
            return "fixture"

        async def generate(self, *_, **__):
            await asyncio.sleep(1)
            return ModelResponse(model_id="fixture", content="late")

    class Streaming(Provider):
        async def generate_stream(self, *_, **__):
            await asyncio.sleep(1)
            yield "late"

    provider = Streaming() if stream else Provider()
    service = ModelService()
    service.router = SimpleNamespace(get_model=lambda **_: provider)
    monkeypatch.setattr(settings, "MODEL_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(ModelUnavailableError):
        _ = [item async for item in service.generate_stream("public test", DataLevel.PUBLIC)]


@pytest.mark.parametrize("role", ["x; DROP TABLE users", "../owner", "a", "OWNER"])
def test_runtime_role_input_cannot_be_sql_or_path(role):
    with pytest.raises(ValueError):
        validate_role(role)


def test_runtime_role_only_grants_audit_select_insert():
    sql = "\n".join(statements("party_runtime"))
    assert 'REVOKE ALL ON audit_logs FROM "party_runtime"' in sql
    assert 'GRANT SELECT, INSERT ON audit_logs TO "party_runtime"' in sql


@pytest.mark.parametrize(
    "name", ["../outside", "/outside", "files/../../outside", "files\\outside"]
)
def test_restore_bundle_rejects_path_escape_before_destination_access(encrypted, name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, b"secret")
        archive.writestr("manifest.json", json.dumps({"format": 1, "files": {}}))
    with pytest.raises(ValueError):
        unpack_bundle(seal(stream.getvalue(), PURPOSE))


async def test_long_job_dedup_key_is_bounded_and_duplicate_reuses_existing_record():
    from app.services.job_service import enqueue

    added = []

    class Savepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    db = SimpleNamespace(
        execute=AsyncMock(return_value=result(None)),
        add=added.append,
        flush=AsyncMock(),
        begin_nested=Savepoint,
    )
    body = JobCreate(kind="assessment_reminders", dedup_key="x" * 160)
    row = await enqueue(db, actor(), body)
    assert len(row.dedup_key) == 64 and len(added) == 1
    db.execute.return_value = result(row)
    assert await enqueue(db, actor(), body) is row
    assert len(added) == 1
