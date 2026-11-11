"""电子归档确认状态的纯函数校验；不连库、不依赖会议业务数据。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.v1 import meeting
from app.services.archive_service import archive_policy_ready


def test_archive_policy_requires_enabled_revision_actor_and_evidence():
    assert not archive_policy_ready({})
    assert not archive_policy_ready({"enabled": True})
    assert not archive_policy_ready(
        {"enabled": True, "revision": 1, "confirmed_by": "u1", "evidence": "校党委会决定"}
    )
    assert not archive_policy_ready(
        {
            "enabled": True,
            "revision": 0,
            "confirmed_by": "u1",
            "confirmed_at": "2026-11-09T00:00:00",
            "evidence": "校党委会决定",
        }
    )
    assert archive_policy_ready(
        {
            "enabled": True,
            "revision": 1,
            "confirmed_by": "u1",
            "confirmed_at": "2026-11-09T00:00:00",
            "evidence": "校党委会决定",
        }
    )


@pytest.mark.asyncio
async def test_archive_status_returns_only_enabled_and_reason(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace(trace_id="trace-1"))
    user = SimpleNamespace(tenant_id="tenant-a")

    async def ready(_db, _tenant_id):
        return {
            "enabled": True,
            "revision": 1,
            "confirmed_by": "u1",
            "confirmed_at": "2026-11-09T00:00:00",
            "evidence": "校党委会决定",
        }

    monkeypatch.setattr(meeting, "archive_policy", ready)
    response = await meeting.archive_status(request, user=user, db=MagicMock())
    assert response.data == {"enabled": True, "reason": None}

    async def missing(_db, _tenant_id):
        return {"enabled": False}

    monkeypatch.setattr(meeting, "archive_policy", missing)
    response = await meeting.archive_status(request, user=user, db=MagicMock())
    assert response.data["enabled"] is False
    assert "尚未确认电子记录效力" in response.data["reason"]
    assert "evidence" not in response.data
    assert "confirmed_by" not in response.data
