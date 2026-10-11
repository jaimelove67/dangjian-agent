"""pytest 配置文件"""

import asyncio
import uuid
from typing import AsyncGenerator

import pytest


# 配置 asyncio 事件循环
@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def isolate_rate_limit_counters(monkeypatch):
    """Each test keeps the real limiter but receives its own Redis/memory counter keys."""
    from app.core import rate_limit

    original = rate_limit.acquire
    namespace = "pytest_" + uuid.uuid4().hex

    async def isolated(category, identity, limit):
        await original(namespace + ":" + category, identity, limit)

    monkeypatch.setattr(rate_limit, "acquire", isolated)
