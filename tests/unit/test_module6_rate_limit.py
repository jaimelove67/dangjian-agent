"""Exercise runtime limits and fail-closed behavior with independent test counters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import rate_limit
from app.core.config import settings


@pytest.mark.parametrize(
    "path,setting,category",
    [
        ("/api/v1/auth/login", "LOGIN_RATE_LIMIT_PER_MINUTE", "login"),
        ("/api/v1/qa", "MODEL_RATE_LIMIT_PER_MINUTE", "model"),
        ("/api/v1/member-profiles", "RATE_LIMIT_PER_MINUTE", "api"),
    ],
)
async def test_http_categories_use_real_atomic_limit_and_reject_next_request(
    monkeypatch, path, setting, category
):
    monkeypatch.setattr(settings, setting, 2)
    evaluate = AsyncMock(side_effect=[1, 2, 3])
    monkeypatch.setattr(
        rate_limit, "redis_manager", SimpleNamespace(client=SimpleNamespace(eval=evaluate))
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("192.0.2.1", 1234),
            "scheme": "http",
        }
    )
    await rate_limit.check_rate_limit(request)
    await rate_limit.check_rate_limit(request)
    with pytest.raises(HTTPException) as caught:
        await rate_limit.check_rate_limit(request)
    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "60"
    keys = [call.args[2] for call in evaluate.await_args_list]
    assert len(set(keys)) == 1 and (":" + category + ":") in keys[0]


async def test_production_redis_failure_cannot_fall_back_to_memory(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    evaluate = AsyncMock(side_effect=ConnectionError("private upstream detail"))
    monkeypatch.setattr(
        rate_limit, "redis_manager", SimpleNamespace(client=SimpleNamespace(eval=evaluate))
    )
    with pytest.raises(HTTPException) as caught:
        await rate_limit.acquire("api", "synthetic-user", 2)
    assert caught.value.status_code == 503
    assert "private" not in caught.value.detail


async def test_nonproduction_memory_fallback_still_enforces_the_same_limit(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "testing")
    evaluate = AsyncMock(side_effect=ConnectionError("unavailable"))
    monkeypatch.setattr(
        rate_limit, "redis_manager", SimpleNamespace(client=SimpleNamespace(eval=evaluate))
    )
    await rate_limit.acquire("api", "synthetic-user", 1)
    with pytest.raises(HTTPException) as caught:
        await rate_limit.acquire("api", "synthetic-user", 1)
    assert caught.value.status_code == 429
