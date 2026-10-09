"""核心问答链路集成测试：改写 → 检索 → 判定 → 生成 → 引用核验 → 输出（含会话）"""
import pytest

from app.chains.qa_chain import QAChain
from app.chains.session import SessionStore
from app.rag.verifier import RetrievedChunk

pytestmark = pytest.mark.integration


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

    async def retrieve(self, *, question, tenant_id, include_expired=False):
        return self.chunks


class FakeGenerator:
    async def generate(self, *, question, chunks):
        return "根据《发展党员工作细则》，培养期一般不少于一年[1]。"


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        index=1,
        doc_id="doc-1",
        doc_name="中国共产党发展党员工作细则",
        content="第三条 入党积极分子培养期一般不少于一年。",
        article="第三条",
        doc_number="中办发〔2014〕33号",
        issuer="中共中央办公厅",
        status="effective",
    )


async def test_full_chain_produces_unified_response_with_citation():
    chain = QAChain(
        retriever=FakeRetriever([_chunk()]),
        generator=FakeGenerator(),
        session=SessionStore(FakeCache()),
    )
    response = await chain.ask(question="培养期多久？", tenant_id="t1", session_id="s1")

    assert response.refused is False
    assert response.citations and response.citations[0].article == "第三条"
    assert response.disclaimer
    assert "[1]" in response.answer


async def test_chain_refuses_when_no_evidence():
    chain = QAChain(retriever=FakeRetriever([]), generator=FakeGenerator())
    response = await chain.ask(question="库外问题", tenant_id="t1")
    assert response.refused is True
    assert response.citations == []


async def test_chain_warns_on_expired_citation():
    expired = _chunk()
    expired.status = "abolished"
    chain = QAChain(retriever=FakeRetriever([expired]), generator=FakeGenerator())
    response = await chain.ask(question="培养期多久？", tenant_id="t1")
    assert any("已废止" in w for w in response.warnings)
