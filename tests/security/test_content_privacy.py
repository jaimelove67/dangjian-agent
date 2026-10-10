"""账号访问上限与云端内容密级分离，所有发送内容都不能被降级。"""

from unittest.mock import AsyncMock

import pytest

from app.llm.base import DataLevel
from app.llm.gateway import GatewayError
from app.rag.privacy import content_level
from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever


def test_public_hint_cannot_lower_actual_personal_identifiers():
    assert content_level("合成测试手机号 13900000000", DataLevel.PUBLIC) == DataLevel.SENSITIVE
    assert content_level("合成身份证 110101200001010019", DataLevel.PUBLIC) == DataLevel.SENSITIVE
    assert content_level("入党申请书的材料有哪些？", DataLevel.PUBLIC) == DataLevel.INTERNAL
    assert content_level("密级：机密\n合成档案", DataLevel.PUBLIC) == DataLevel.CLASSIFIED
    assert content_level("涉密材料的登记原则是什么？", DataLevel.PUBLIC) == DataLevel.INTERNAL


async def test_sensitive_document_never_reaches_cloud_reranker(monkeypatch):
    retriever = HybridRetriever(None, data_level=DataLevel.INTERNAL)
    rerank = AsyncMock()
    monkeypatch.setattr(retriever._model_service, "rerank", rerank)
    candidate = RetrievalResult(
        "chunk", "合成敏感档案", 0.9, "doc", metadata={"security_level": "sensitive"}
    )
    with pytest.raises(GatewayError):
        await retriever._rerank("合成普通问题", [candidate], top_k=1)
    rerank.assert_not_awaited()


async def test_rewritten_personal_query_is_blocked_before_embedding(monkeypatch):
    retriever = HybridRetriever(None, data_level=DataLevel.INTERNAL)
    embedding = AsyncMock()
    monkeypatch.setattr(retriever.vector_retriever, "retrieve", embedding)
    with pytest.raises(GatewayError):
        await retriever.retrieve("前文提到的合成手机号 13900000000 应如何处理？")
    embedding.assert_not_awaited()
