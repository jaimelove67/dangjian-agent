"""多轮会话上下文测试（框架文档 5.8）"""
import pytest

from app.chains.session import QATurn, SessionStore


class FakeCache:
    """内存缓存（与 CacheService 接口兼容）"""

    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl=None) -> bool:
        self.store[key] = value
        return True

    async def delete(self, key: str) -> bool:
        self.store.pop(key, None)
        return True


async def test_append_and_get_history():
    store = SessionStore(FakeCache(), ttl_seconds=60, max_turns=3)
    await store.append_turn("t1", "s1", QATurn.create("q1", "a1"))
    history = await store.get_history("t1", "s1")
    assert len(history) == 1
    assert history[0].question == "q1"


async def test_tenant_isolation():
    store = SessionStore(FakeCache())
    await store.append_turn("t1", "s1", QATurn.create("q", "a"))
    assert await store.get_history("t2", "s1") == []


async def test_max_turns_truncates_oldest():
    store = SessionStore(FakeCache(), max_turns=2)
    for i in range(4):
        await store.append_turn("t1", "s1", QATurn.create(f"q{i}", "a"))
    history = await store.get_history("t1", "s1")
    assert [t.question for t in history] == ["q2", "q3"]


async def test_clear():
    store = SessionStore(FakeCache())
    await store.append_turn("t1", "s1", QATurn.create("q", "a"))
    await store.clear("t1", "s1")
    assert await store.get_history("t1", "s1") == []


def test_build_key_requires_tenant():
    with pytest.raises(ValueError):
        SessionStore(FakeCache()).build_key("", "s1")


def test_summarize_citations_strips_content():
    summaries = SessionStore.summarize_citations(
        [{"doc_name": "d", "article": "第一条", "content": "敏感原文"}]
    )
    assert summaries == [{"doc_name": "d", "article": "第一条"}]
