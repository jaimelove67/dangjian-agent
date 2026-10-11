"""Audit changes retain safe version pointers without copying private business fields."""

import uuid

import pytest

from app.core.redaction import audit_summary, summary


def test_audit_summary_retains_version_pointer_and_deletion_but_hashes_private_fields():
    snapshot = str(uuid.uuid4())
    change = {
        "revision": 3,
        "snapshot_id": snapshot,
        "is_deleted": True,
        "opinion": "private human review",
        "password": "private password",
        "status": "caller supplied arbitrary text",
    }
    result = audit_summary(change)
    assert result == {
        **summary(change),
        "revision": 3,
        "snapshot_id": snapshot,
        "is_deleted": True,
    }
    assert "private" not in str(result)


@pytest.mark.parametrize("revision", [True, -1, 1.5, "arbitrary private text"])
def test_untrusted_version_fields_cannot_bypass_audit_redaction(revision):
    change = {"revision": revision, "snapshot_id": "private text", "is_deleted": "yes"}
    assert audit_summary(change) == summary(change)
