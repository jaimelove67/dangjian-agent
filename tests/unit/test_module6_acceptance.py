"""负载工具不能将快速拒绝或没有学校确认当作性能成功。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.module6_acceptance import load


async def test_missing_approval_and_questions_do_not_issue_any_request(monkeypatch):
    monkeypatch.delenv("MODULE6_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("MODULE6_LOAD_TOKEN", raising=False)
    result = await load("https://school.example", [], 10, 2)
    assert result["status"] == "pending_configuration" and result["requests"] == 0


async def test_refused_responses_cannot_pass_latency_target(monkeypatch):
    import scripts.module6_acceptance as module

    monkeypatch.setenv("MODULE6_ADMIN_TOKEN", "synthetic-admin")
    monkeypatch.setenv("MODULE6_LOAD_TOKEN", "synthetic-load")
    policy = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "data": {
                "admission": {"status": "configured"},
                "values": {"model_policy": {"external_enabled": True}},
            }
        },
    )
    denied = SimpleNamespace(status_code=403, json=lambda: {"code": 40301, "data": None})
    delegate = SimpleNamespace(
        get=AsyncMock(return_value=policy), post=AsyncMock(return_value=denied)
    )

    class Client:
        async def __aenter__(self):
            return delegate

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: Client())
    report = await load("https://school.example", ["public"], 4, 2)
    assert report["status"] == "failed" and report["successful_full_qa"] == 0
    assert report["p95_full_successful_seconds"] is None


@pytest.mark.parametrize("approved_route", ["external_enabled", "local_sensitive_enabled"])
async def test_full_successful_grounded_answers_can_pass(monkeypatch, approved_route):
    import scripts.module6_acceptance as module

    monkeypatch.setenv("MODULE6_ADMIN_TOKEN", "synthetic-admin")
    monkeypatch.setenv("MODULE6_LOAD_TOKEN", "synthetic-load")
    policy = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "data": {
                "admission": {"status": "configured"},
                "values": {"model_policy": {approved_route: True}},
            }
        },
    )
    success = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "code": 0,
            "data": {"answer": "public [1]", "citations": [{"index": 1}], "refused": False},
        },
    )
    delegate = SimpleNamespace(
        get=AsyncMock(return_value=policy), post=AsyncMock(return_value=success)
    )

    class Client:
        async def __aenter__(self):
            return delegate

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: Client())
    report = await load("https://school.example", ["public"], 4, 2)
    assert report["status"] == "passed" and report["successful_full_qa"] == 4
    assert report["p95_full_successful_seconds"] < 3


async def test_pending_school_blocks_even_when_tokens_exist(monkeypatch):
    import scripts.module6_acceptance as module

    monkeypatch.setenv("MODULE6_ADMIN_TOKEN", "synthetic-admin")
    monkeypatch.setenv("MODULE6_LOAD_TOKEN", "synthetic-load")
    policy = SimpleNamespace(
        status_code=200, json=lambda: {"data": {"admission": {"status": "pending_configuration"}}}
    )
    delegate = SimpleNamespace(get=AsyncMock(return_value=policy), post=AsyncMock())

    class Client:
        async def __aenter__(self):
            return delegate

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: Client())
    report = await load("https://school.example", ["public"], 4, 2)
    assert report["status"] == "pending_configuration"
    delegate.post.assert_not_awaited()
