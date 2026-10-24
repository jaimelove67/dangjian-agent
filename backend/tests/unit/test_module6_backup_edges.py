"""备份必须包含所有登记版本，并在碰触恢复目标前验证内层和续跑身份。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.encryption import EncryptionError, seal
from app.models.audit import AuditLog
from app.models.governance import DurableJob
from app.services import file_store, job_service
from scripts import module6_backup as backup
from scripts import module6_runtime_role as runtime


@pytest.fixture
def crypt(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "FILE_ENCRYPTION_KEYS", json.dumps({"unit": base64.b64encode(os.urandom(32)).decode()})
    )
    monkeypatch.setenv("FILE_ENCRYPTION_ACTIVE_KEY", "unit")
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path / "source"))
    monkeypatch.setattr(settings, "ENV", "testing")


def bundle(items=None, originals=None):
    entries = {"database.dump": b"PGDMP_UNIT_ONLY", "redis.json": b"[]", **(items or {})}
    manifest = {
        "format": 1,
        "database": {"tables": {}, "server_major": 16, "originals": originals or []},
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in entries.items()},
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, raw in entries.items():
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps(manifest))
    return seal(stream.getvalue(), backup.PURPOSE)


def refs(metadata):
    return backup.registered_originals(
        [{"tenant_id": "tenant", "doc_id": "doc", "metadata": metadata}]
    )


def test_missing_registered_historical_original_prevents_success(crypt):
    old = file_store.save_original("tenant", "doc", 1, b"old", "a.txt")
    current = file_store.save_original("tenant", "doc", 2, b"current", "a.txt")
    inventory = refs({"original_file": current, "original_versions": {"1": old, "2": current}})
    assert len(inventory) == 2
    raw = (file_store.storage_root() / current["path"]).read_bytes()
    with pytest.raises(EncryptionError, match="缺失"):
        backup.unpack_bundle(bundle({"files/" + current["path"]: raw}, inventory))


def test_registered_hash_checked_for_legacy_encrypted_filename(crypt):
    path = "tenant/originals/doc__v1.bin"
    metadata = {"path": path, "sha256": hashlib.sha256(b"expected").hexdigest(), "revision": 1}
    raw = seal(b"other content", "original:tenant:doc:1")
    with pytest.raises(EncryptionError, match="SHA256"):
        backup.unpack_bundle(bundle({"files/" + path: raw}, refs({"original_file": metadata})))


def test_legacy_encrypted_original_is_accepted_with_correct_registration(crypt):
    path = "tenant/originals/doc__v1.bin"
    raw = seal(b"expected", "original:tenant:doc:1")
    metadata = {"path": path, "sha256": hashlib.sha256(b"expected").hexdigest(), "revision": 1}
    manifest, items = backup.unpack_bundle(
        bundle({"files/" + path: raw}, refs({"original_file": metadata}))
    )
    assert len(manifest["database"]["originals"]) == 1 and items["files/" + path] == raw


@pytest.mark.parametrize("path", ["other/originals/doc__v1.bin", "../doc.bin", "/tenant/doc.bin"])
def test_database_registration_cannot_reference_other_tenant_or_escape(crypt, path):
    metadata = {"path": path, "sha256": "a" * 64, "revision": 1}
    with pytest.raises(ValueError):
        refs({"original_file": metadata})


async def test_inner_ciphertext_failure_happens_before_database_or_destination_access(
    crypt, tmp_path, monkeypatch
):
    path = "tenant/originals/doc__v1.bin"
    # Outer seal and ZIP checksums are valid; inner encryption belongs to another tenant.
    raw = seal(b"private", "original:other:doc:1")
    source = tmp_path / "bundle"
    source.write_bytes(bundle({"files/" + path: raw}))
    connect = AsyncMock()
    monkeypatch.setattr(backup, "db_connect", connect)
    target = tmp_path / "destination"
    with pytest.raises(EncryptionError):
        await backup.restore(
            source,
            "postgresql://unit:unit@127.0.0.1/module6_restore_unit",
            "redis://127.0.0.1/15",
            target,
            tmp_path / "audit",
            None,
            True,
        )
    connect.assert_not_awaited()
    assert not target.exists()


@pytest.mark.parametrize("marker_exists", [True, False])
async def test_resume_requires_authenticated_matching_checkpoint_before_database_access(
    crypt, tmp_path, monkeypatch, marker_exists
):
    source = tmp_path / "bundle"
    source.write_bytes(bundle())
    target = tmp_path / "destination"
    target.mkdir()
    if marker_exists:
        (target / ".module6-restore-state").write_bytes(
            seal(b'{"bundle_sha256":"another-bundle"}', backup.RESTORE_PURPOSE)
        )
    connect = AsyncMock()
    monkeypatch.setattr(backup, "db_connect", connect)
    with pytest.raises(ValueError, match="检查点"):
        await backup.restore(
            source,
            "postgresql://unit:unit@127.0.0.1/module6_restore_unit",
            "redis://127.0.0.1/15",
            target,
            tmp_path / "audit",
            None,
            True,
            True,
        )
    connect.assert_not_awaited()


async def test_unsafe_runtime_identity_rejected_before_any_grant(monkeypatch):
    conn = SimpleNamespace(scalar=AsyncMock(return_value=True), execute=AsyncMock())

    class Context:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(runtime, "engine", SimpleNamespace(begin=Context))
    with pytest.raises(ValueError):
        await runtime.apply("module6_runtime")
    conn.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "exception, expected",
    [
        (HTTPException(403, "PRIVATE"), "denied"),
        (HTTPException(503, "PRIVATE"), "failed"),
        (ConnectionError("PRIVATE"), "failed"),
    ],
)
async def test_each_failed_worker_attempt_has_durable_actor_object_and_trace_audit(
    monkeypatch, exception, expected
):
    row = DurableJob(
        id="job",
        tenant_id="tenant",
        actor_id="actor",
        kind="member_reminders",
        status="running",
        attempts=1,
        max_attempts=3,
        lease_token="trace",
    )
    recorded = []
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: row)),
        add=recorded.append,
        flush=AsyncMock(),
        commit=AsyncMock(),
    )

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(job_service, "claim", AsyncMock(return_value=("tenant", "job", "trace")))
    monkeypatch.setattr(job_service, "execute", AsyncMock(side_effect=exception))
    monkeypatch.setattr(job_service, "async_session_maker", Session)
    assert await job_service.run_once()
    log = recorded[0]
    assert isinstance(log, AuditLog)
    assert (log.user_id, log.resource_id, log.request_id, log.result) == (
        "actor",
        "job",
        "trace",
        expected,
    )
    assert "PRIVATE" not in json.dumps(log.new_value)
    db.commit.assert_awaited_once()


async def test_exhausted_lease_writes_failure_audit_and_cannot_be_reclaimed(monkeypatch):
    row = DurableJob(
        id="job",
        tenant_id="tenant",
        actor_id="actor",
        kind="member_reminders",
        status="running",
        attempts=3,
        max_attempts=3,
        lease_token="expired-trace",
    )
    recorded = []
    rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))
    empty = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[rows, empty]),
        add=recorded.append,
        flush=AsyncMock(),
        commit=AsyncMock(),
    )

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(job_service, "async_session_maker", Session)
    assert await job_service.claim() is None
    assert (
        row.status == "failed" and row.error_code == "lease_exhausted" and row.lease_token is None
    )
    assert len(recorded) == 1 and recorded[0].request_id == "expired-trace"
    assert recorded[0].result == "failed"
