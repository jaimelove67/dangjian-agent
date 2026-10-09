"""六阶段问答链测试（框架文档 5.6）"""
import pytest

from app.chains.qa_chain import QAChain
from app.chains.session import SessionStore
from app.rag.verifier import RetrievedChunk


class FakeCache:
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


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = 0

    async def retrieve(self, *, question: str, tenant_id: str, include_expired: bool = False):
        self.calls += 1
        return self.chunks


class FakeGenerator:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def generate(self, *, question, chunks):
        self.calls += 1
        return self.text


def _chunk(index: int = 1, **overrides) -> RetrievedChunk:
    base = {
        "index": index,
        "doc_id": f"d{index}",
        "doc_name": f"文件{index}",
        "content": "第一条 培养期一般不少于一年。",
        "article": "第一条",
        "status": "effective",
    }
    base.update(overrides)
    return RetrievedChunk(**base)


async def test_full_chain_success():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1)]),
        generator=FakeGenerator("根据培养期一般不少于一年[1]。"),
    )
    response = await chain.ask(question="培养期多久？", tenant_id="t1")

    assert response.refused is False
    assert len(response.citations) == 1
    assert response.disclaimer
    assert "培养期" in response.answer


async def test_no_chunks_refuses_and_skips_generation():
    generator = FakeGenerator("不应被调用")
    chain = QAChain(retriever=FakeRetriever([]), generator=generator)
    response = await chain.ask(question="无关问题", tenant_id="t1")

    assert response.refused is True
    assert response.citations == []
    assert generator.calls == 0


async def test_low_score_refuses():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, score=0.1)]),
        generator=FakeGenerator("x[1]"),
        no_evidence_threshold=0.5,
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is True


async def test_high_score_proceeds():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, score=0.9)]),
        generator=FakeGenerator("答案[1]"),
        no_evidence_threshold=0.5,
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is False


async def test_session_persisted_with_summary_only():
    session = SessionStore(FakeCache(), max_turns=5)
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1)]),
        generator=FakeGenerator("答案[1]"),
        session=session,
    )
    await chain.ask(question="q1", tenant_id="t1", session_id="s1")

    history = await session.get_history("t1", "s1")
    assert len(history) == 1
    assert history[0].question == "q1"
    # 会话仅保留引用摘要，不含原始片段内容
    assert history[0].citations[0] == {"doc_name": "文件1", "article": "第一条"}
