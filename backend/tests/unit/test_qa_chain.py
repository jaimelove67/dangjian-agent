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


class FakeAdvisoryGenerator(FakeGenerator):
    """办理参考生成器；测试里只关心是否被调用、是否清掉引用角标。"""

    async def generate(self, *, question, chunks):
        self.calls += 1
        assert chunks == []
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


async def test_reference_only_basis_refused():
    """非权威参考资料不能作为唯一依据（T-KB-12 / FR-KB-10）。"""
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, authority="reference")]),
        generator=FakeGenerator("根据资料[1]。"),
    )
    response = await chain.ask(question="问", tenant_id="t1")

    assert response.refused is True
    assert response.citations == []
    assert any("非权威或已失效" in warning for warning in response.warnings)


async def test_out_of_force_only_basis_refused():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, validity="repealed")]),
        generator=FakeGenerator("根据文件[1]。"),
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is True


async def test_authoritative_basis_allows_answer():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, authority="superior_document", validity="effective")]),
        generator=FakeGenerator("根据制度[1]。"),
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is False
    assert response.citations[0].authority == "superior_document"


async def test_reference_alongside_authoritative_is_allowed():
    """参考资料与权威文件一同被引用时不是唯一依据，可以输出并给出提示。"""
    chain = QAChain(
        retriever=FakeRetriever(
            [
                _chunk(1, doc_name="参考资料", authority="reference"),
                _chunk(2, authority="party_regulation"),
            ]
        ),
        generator=FakeGenerator("结论[1][2]。"),
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is False
    assert len(response.citations) == 2
    assert any("非权威参考资料" in warning for warning in response.warnings)


async def test_no_chunks_refuses_and_skips_generation():
    generator = FakeGenerator("不应被调用")
    chain = QAChain(retriever=FakeRetriever([]), generator=generator)
    response = await chain.ask(question="无关问题", tenant_id="t1")

    assert response.refused is True
    assert response.citations == []
    assert generator.calls == 0


async def test_no_chunks_advisory_answers_without_citations():
    generator = FakeGenerator("不应被调用")
    advisory = FakeAdvisoryGenerator("可以按以下步骤准备：\n1. 明确活动主题。")
    chain = QAChain(
        retriever=FakeRetriever([]),
        generator=generator,
        advisory_generator=advisory,
    )
    response = await chain.ask(question="帮我起草一份活动方案", tenant_id="t1")

    assert response.refused is False
    assert response.citations == []
    assert generator.calls == 0
    assert advisory.calls == 1
    assert response.answer.startswith("未检索到可引用的制度依据，以下为办理参考：")
    assert any("不构成政策依据" in warning for warning in response.warnings)


async def test_advisory_strips_citation_markers():
    chain = QAChain(
        retriever=FakeRetriever([]),
        generator=FakeGenerator("不应被调用"),
        advisory_generator=FakeAdvisoryGenerator("参考步骤[1][2]。"),
    )
    response = await chain.ask(question="起草方案", tenant_id="t1")

    assert "[1]" not in response.answer
    assert "[2]" not in response.answer
    assert response.refused is False


async def test_advisory_removes_fabricated_clause_references():
    chain = QAChain(
        retriever=FakeRetriever([]),
        generator=FakeGenerator("不应被调用"),
        advisory_generator=FakeAdvisoryGenerator(
            "可以先明确活动主题。\n根据《中国共产党章程》第十条，必须提前3天报备。\n"
            "然后收集党员意见。"
        ),
    )
    response = await chain.ask(question="起草方案", tenant_id="t1")

    assert "第十条" not in response.answer
    assert "必须提前3天报备" not in response.answer
    assert "可以先明确活动主题" in response.answer
    assert "然后收集党员意见" in response.answer
    assert any("具体条款或文号" in warning for warning in response.warnings)


async def test_low_score_refuses_without_advisory():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, score=0.1)]),
        generator=FakeGenerator("x[1]"),
        no_evidence_threshold=0.5,
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is True


async def test_low_score_advisory_answers():
    chain = QAChain(
        retriever=FakeRetriever([_chunk(1, score=0.1)]),
        generator=FakeGenerator("不应被调用"),
        advisory_generator=FakeAdvisoryGenerator("办理思路。"),
        no_evidence_threshold=0.5,
    )
    response = await chain.ask(question="问", tenant_id="t1")
    assert response.refused is False
    assert response.citations == []


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
