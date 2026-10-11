"""Reranking propagates classification and fails safely without disclosing vendor bodies."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.llm.base import DataLevel, RerankResponse, RerankResult
from app.llm.gateway import GatewayError
from app.rag.retrieval import reranker as module
from app.schemas.retrieval import RetrievalResult


def candidates(level="public"):
    return [
        RetrievalResult(
            chunk_id=str(i),
            doc_id="synthetic",
            content="公开合成规定",
            score=0.1,
            sequence=i,
            metadata={"security_level": level},
        )
        for i in range(3)
    ]


@pytest.fixture
def reranking(monkeypatch):
    registry = Mock()
    service = SimpleNamespace(rerank=AsyncMock())
    monkeypatch.setattr(module, "get_model_registry", lambda: registry)
    monkeypatch.setattr(module, "get_model_service", lambda: service)
    return module.Reranker(), registry, service


async def test_short_or_unavailable_reranking_preserves_authorized_candidates(reranking):
    runner, registry, service = reranking
    assert await runner.rerank("公开查询", []) == []
    rows = candidates()
    assert await runner.rerank("公开查询", rows, top_k=3) == rows
    registry.get_provider.return_value = None
    assert await runner.rerank("公开查询", rows, top_k=1) == rows[:1]
    service.rerank.assert_not_awaited()


@pytest.mark.parametrize("level", list(DataLevel))
async def test_reranker_propagates_highest_document_classification(reranking, level):
    runner, _, service = reranking
    rows = candidates(level.value)
    service.rerank.return_value = RerankResponse(
        model_id="synthetic",
        results=[
            RerankResult(index=2, relevance_score=0.9),
            RerankResult(index=-1, relevance_score=1),
            RerankResult(index=99, relevance_score=1),
        ],
    )
    result = await runner.rerank("公开查询", rows, top_k=1)
    assert [row.chunk_id for row in result] == ["2"]
    assert result[0].score == 0.9
    expected = DataLevel.INTERNAL if level == DataLevel.PUBLIC else level
    assert service.rerank.await_args.kwargs["data_level"] == expected


async def test_gateway_denial_returns_original_ranking_and_logs_only_error_type(
    reranking, monkeypatch
):
    runner, _, service = reranking
    secret = "synthetic-sensitive-vendor-body"
    service.rerank.side_effect = GatewayError(secret)
    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    rows = candidates("sensitive")
    assert await runner.rerank("公开查询", rows, top_k=1) == rows[:1]
    assert service.rerank.await_args.kwargs["data_level"] == DataLevel.SENSITIVE
    assert secret not in str(logger.mock_calls)
    logger.error.assert_called_once_with("rerank_failed", error="GatewayError", candidates_count=3)
