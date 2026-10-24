"""账号访问上限与云端内容密级分离，所有发送内容都不能被降级。"""

from unittest.mock import AsyncMock

import pytest

from app.llm.base import DataLevel
from app.llm.gateway import GatewayError
from app.rag.privacy import content_level, require_cloud_eligible
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


def test_member_material_levels_feed_the_cloud_and_embedding_guards():
    """T-MEM-12：政审 / 群众评议材料的密级直接喂给既有的出网与向量化判定。

    这样"政审类材料默认不出网、不进知识库、不向量化"不是一句文档承诺：材料密级
    一旦按 ``data_sensitivity`` 给出，就套得上同一套 ``require_cloud_eligible`` /
    ``embedding_allowed`` 判定，任何把它送进模型或向量库的路径都会先被拦住。
    """
    from app.rules import data_sensitivity as ds

    for material_type in ("政治审查材料", "群众评议材料"):
        level = ds.material_level(material_type)
        # 声明为该密级时，内容分级不得低于它（等于放行）
        assert content_level("材料正文", DataLevel(level.value)) == DataLevel(level.value)
        assert not ds.cloud_allowed(level)
        with pytest.raises(GatewayError):
            require_cloud_eligible(DataLevel(level.value))
    # 政审材料连向量化都不允许；未登记类型仍按内部处理、可正常走内部路径
    assert not ds.embedding_allowed(ds.material_level("政治审查材料"))
    assert ds.embedding_allowed(ds.material_level("思想汇报"))
