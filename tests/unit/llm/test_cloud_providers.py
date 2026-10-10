"""云端接口契约测试：使用 HTTP 模拟传输，不调用公网模型。"""

import asyncio
import json

import httpx
import pytest

from app.llm.base import DeploymentType, ModelType
from app.llm.errors import ModelUnavailableError
from app.llm.providers.dashscope_embedding import create_dashscope_embedding_provider
from app.llm.providers.dashscope_reranker import create_dashscope_reranker_provider
from app.llm.providers.qwen import create_dashscope_provider


def install_transport(monkeypatch, handler):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.llm.providers.cloud_http.httpx.AsyncClient",
        lambda **kwargs: client(transport=transport, **kwargs),
    )


async def test_chat_uses_selected_model_and_per_request_key(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "合成答案 [1]"}, "finish_reason": "stop"}]},
        )

    install_transport(monkeypatch, respond)
    result = await create_dashscope_provider(api_key="test-only-key").generate("合成问题")
    assert result.content == "合成答案 [1]"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "qwen3.8-flash"
    assert payload["messages"][0]["content"] == "合成问题"
    assert requests[0].url.path == "/compatible-mode/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-only-key"


async def test_chat_preserves_nested_token_usage(monkeypatch):
    usage = {
        "prompt_tokens": 20,
        "completion_tokens": 4,
        "total_tokens": 24,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "合成答案"}}], "usage": usage}
        ),
    )
    result = await create_dashscope_provider(api_key="test-only-key").generate("合成问题")
    assert result.content == "合成答案"
    assert result.usage == usage


async def test_duplicate_batch_indices_retry_individually_without_guessing_order(monkeypatch):
    requests = []

    def respond(request):
        batch = json.loads(request.content)["input"]
        requests.append(batch)
        rows = [{"index": 0, "embedding": [float(value)] * 1024} for value in batch[::-1]]
        return httpx.Response(200, json={"data": rows})

    install_transport(monkeypatch, respond)
    provider = create_dashscope_embedding_provider(api_key="test-only-key")
    result = await provider.embed(["10", "20"])
    assert [row[0] for row in result.embeddings] == [10, 20]
    assert requests[0] == ["10", "20"]
    assert sorted(requests[1:]) == [["10"], ["20"]]
    requests.clear()
    result = await provider.embed(["30", "40"])
    assert [row[0] for row in result.embeddings] == [30, 40]
    assert sorted(requests) == [["30"], ["40"]]


async def test_embedding_batches_and_restores_response_order(monkeypatch):
    batches = []

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "qwen3.7-text-embedding-flash"
        assert body["dimensions"] == 1024
        batches.append(body["input"])
        rows = [
            {"index": i, "embedding": [float(value)] * 1024}
            for i, value in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": rows[::-1]})

    install_transport(monkeypatch, respond)
    response = await create_dashscope_embedding_provider(api_key="test-only-key").embed(
        [str(i) for i in range(21)]
    )
    assert [len(batch) for batch in batches] == [20, 1]
    assert [vector[0] for vector in response.embeddings] == list(range(21))
    assert response.dimensions == 1024


@pytest.mark.parametrize("failure", ["upstream", "timeout"])
async def test_single_retry_limits_concurrency_and_cancels_remaining_requests(monkeypatch, failure):
    active = 0
    peak = 0
    started = []
    waiting = asyncio.Event()

    async def respond(request):
        nonlocal active, peak
        batch = json.loads(request.content)["input"]
        if len(batch) > 1:
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [0.0] * 1024} for _ in batch]}
            )
        active += 1
        peak = max(peak, active)
        started.extend(batch)
        try:
            if failure == "upstream" and batch == ["0"]:
                await asyncio.sleep(0.01)
                return httpx.Response(500, json={"message": "synthetic failure"})
            await waiting.wait()
            raise AssertionError("blocked request unexpectedly completed")
        finally:
            active -= 1

    install_transport(monkeypatch, respond)
    provider = create_dashscope_embedding_provider(api_key="test-only-key")
    expected = ModelUnavailableError if failure == "upstream" else TimeoutError
    with pytest.raises(expected):
        await asyncio.wait_for(provider.embed([str(i) for i in range(8)]), timeout=0.1)
    await asyncio.sleep(0)
    assert peak == 4
    assert active == 0
    assert len(started) == 4


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"index": 1, "embedding": [0.0] * 1024}],
        [{"index": 0, "embedding": [0.0] * 768}],
        [{"index": 0, "embedding": [True] * 1024}],
    ],
)
async def test_embedding_rejects_incomplete_or_invalid_vectors(monkeypatch, rows):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={"data": rows}))
    with pytest.raises(ModelUnavailableError):
        await create_dashscope_embedding_provider(api_key="test-only-key").embed(["合成文档"])


async def test_rerank_returns_standard_results_and_translates_top_k(monkeypatch):
    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "qwen3.7-text-rerank"
        assert body["parameters"] == {"top_n": 1, "return_documents": False}
        return httpx.Response(
            200, json={"output": {"results": [{"index": 1, "relevance_score": 0.9}]}}
        )

    install_transport(monkeypatch, respond)
    response = await create_dashscope_reranker_provider(api_key="test-only-key").rerank(
        "合成查询", ["A", "B"], top_k=1
    )
    assert response.results[0].index == 1
    assert response.results[0].relevance_score == 0.9


@pytest.mark.parametrize(
    "rows",
    [
        [{"index": -1, "relevance_score": 0.8}],
        [{"index": 2, "relevance_score": 0.8}],
        [{"index": 0, "relevance_score": 1.2}],
        [{"index": 0, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.7}],
    ],
)
async def test_rerank_rejects_invalid_or_duplicate_indices(monkeypatch, rows):
    install_transport(
        monkeypatch, lambda request: httpx.Response(200, json={"output": {"results": rows}})
    )
    with pytest.raises(ModelUnavailableError):
        await create_dashscope_reranker_provider(api_key="test-only-key").rerank(
            "合成查询", ["A", "B"], top_k=2
        )


async def test_provider_error_does_not_echo_response_body(monkeypatch):
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(401, json={"message": "test-only-secret-and-private-text"}),
    )
    with pytest.raises(ModelUnavailableError) as error:
        await create_dashscope_provider(api_key="test-only-key").generate("合成问题")
    assert "401" in str(error.value)
    assert "secret" not in str(error.value)


def test_initialization_registers_three_cloud_capabilities_without_requests(monkeypatch):
    from app.core.config import settings
    from app.llm import init_models
    from app.llm.registry import ModelRegistry

    registry = ModelRegistry()
    monkeypatch.setattr(init_models, "get_model_registry", lambda: registry)
    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", "test-only-key")
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "qwen3.8-flash")
    init_models.init_models()
    init_models.init_models()
    assert len(registry.list_models()) == 3
    assert {
        registry.get_provider(model).config.model_type for model in registry.list_models()
    } == set(ModelType)
    assert all(
        registry.get_provider(model).config.deployment_type == DeploymentType.EXTERNAL
        for model in registry.list_models()
    )
    assert set(init_models.model_readiness().values()) == {"configured"}
