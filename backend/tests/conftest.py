"""pytest 配置文件"""

import asyncio
import os
import uuid

import pytest

# 本地 .env 通常把 ENV 设为 development，此时应用引擎走连接池（见 app/db/session.py）；
# 而 pytest 每个用例使用独立的事件循环，池化连接会跨已关闭的循环泄漏，长跑会把
# Postgres 的 max_connections 顶穿（实测全量跑到峰值 104 / 上限 100，失败全是
# TooManyConnectionsError）。CI 由工作流显式设置 ENV=testing，应用引擎改用 NullPool，
# 因此这里显式对齐，保证本地与 CI 跑的是同一套连接策略。
# 注：settings.ENV 的其它判断都是「是否等于 production」，故此处只改变连接池策略。
os.environ.setdefault("ENV", "testing")


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
