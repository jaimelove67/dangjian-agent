"""正式问答入口的拒答、引用与分级回归，不调用外部模型。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.chains.session import QATurn
from app.db.session import get_db
from app.deps import get_current_tenant, get_current_user
from app.llm.base import DataLevel
from app.llm.service import ModelService
from app.main import app
from app.models.user import User, UserRole
from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever
from app.schemas.qa import REFUSAL_ANSWER


@pytest.fixture
def qa_client(monkeypatch):
    user = User(
        id="qa-user",
        username="qa-user",
        name="测试用户",
        tenant_id="qa-tenant",
        role=UserRole.MEMBER,
        is_active=True,
    )

    @asynccontextmanager
    async def begin_nested():
        yield

    db = SimpleNamespace(
        add=lambda _: None, flush=AsyncMock(), commit=AsyncMock(), begin_nested=begin_nested
    )
    retrieve = AsyncMock(return_value=[])
    generate = AsyncMock(return_value=SimpleNamespace(content="第一条要求提交申请。[1]"))
    monkeypatch.setattr(HybridRetriever, "retrieve", retrieve)
    monkeypatch.setattr(ModelService, "generate", generate)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: user.tenant_id
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), retrieve, generate
    finally:
        app.dependency_overrides.clear()


def chunk(score=0.9):
    return RetrievalResult(
        "chunk-1",
        "第一条 要求提交申请。",
        score,
        "DOC-QA-1",
        article="第一条",
        metadata={
            "title": "合成制度",
            "issuer": "测试单位",
            "file_name": "synthetic.txt",
            "visibility": "school",
            "security_level": "internal",
            "effective_date": "2020-01-01",
        },
    )


def test_followup_is_rewritten_before_real_retrieval(qa_client, monkeypatch):
    client, retrieve, generate = qa_client
    history = [QATurn.create("积极分子需要培养多久？", "至少一年。")]
    store = SimpleNamespace(get_history=AsyncMock(return_value=history), append_turn=AsyncMock())
    monkeypatch.setattr("app.api.v1.qa._session_store", lambda _: store)
    generate.return_value = SimpleNamespace(content="积极分子培养期需要多久？")
    response = client.post(
        "/api/v1/qa", json={"question": "它需要多久？", "session_id": "followup"}
    )
    assert response.status_code == 200
    assert retrieve.await_args.args[0] == "积极分子培养期需要多久？"
    assert generate.await_args.kwargs["task_type"].value == "rewrite"
    assert "积极分子需要培养多久" in generate.await_args.kwargs["prompt"]


def test_sensitive_history_is_blocked_before_rewrite_model(qa_client, monkeypatch):
    client, retrieve, generate = qa_client
    history = [QATurn.create("合成普通问题", "合成旧记录手机号 13900000000")]
    store = SimpleNamespace(get_history=AsyncMock(return_value=history), append_turn=AsyncMock())
    monkeypatch.setattr("app.api.v1.qa._session_store", lambda _: store)
    response = client.post(
        "/api/v1/qa", json={"question": "它需要多久？", "session_id": "dirty-history"}
    )
    assert response.status_code == 403
    generate.assert_not_awaited()
    retrieve.assert_not_awaited()


def test_low_evidence_refuses_before_generation(qa_client):
    client, retrieve, generate = qa_client
    retrieve.return_value = [chunk(0.1)]
    response = client.post("/api/v1/qa", json={"question": "申请需要什么材料？"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == REFUSAL_ANSWER
    assert data["refused"] is True
    assert data["citations"] == []
    generate.assert_not_awaited()


def test_admin_question_uses_content_level_not_role_clearance(qa_client):
    client, retrieve, generate = qa_client
    app.dependency_overrides[get_current_user]().role = UserRole.SYSTEM_ADMIN
    retrieve.return_value = [chunk()]
    response = client.post("/api/v1/qa", json={"question": "申请需要什么材料？"})
    assert response.status_code == 200
    assert generate.await_args.kwargs["data_level"] == DataLevel.INTERNAL


def test_public_hint_cannot_send_personal_question_to_cloud(qa_client):
    client, retrieve, generate = qa_client
    response = client.post(
        "/api/v1/qa", json={"question": "合成手机号 13900000000", "data_level": "public"}
    )
    assert response.status_code == 403
    retrieve.assert_not_awaited()
    generate.assert_not_awaited()


def test_sensitive_source_is_blocked_before_generation(qa_client):
    client, retrieve, generate = qa_client
    source = chunk()
    source.metadata["security_level"] = "sensitive"
    retrieve.return_value = [source]
    response = client.post("/api/v1/qa", json={"question": "合成普通制度问题"})
    assert response.status_code == 403
    generate.assert_not_awaited()


@pytest.mark.parametrize("field", ["title", "issuer", "doc_number", "article"])
def test_personal_source_metadata_is_blocked_before_generation(qa_client, field):
    client, retrieve, generate = qa_client
    source = chunk()
    source.metadata["security_level"] = "public"
    if field == "article":
        source.article = "合成个人材料 13900000000"
    else:
        source.metadata[field] = "合成个人材料 13900000000"
    retrieve.return_value = [source]
    response = client.post("/api/v1/qa", json={"question": "合成普通制度问题"})
    assert response.status_code == 403
    generate.assert_not_awaited()


def test_invalid_citation_cannot_be_returned_as_supported(qa_client):
    client, retrieve, generate = qa_client
    retrieve.return_value = [chunk()]
    generate.return_value = SimpleNamespace(content="不存在的第二十条允许跳过申请。[99]")
    response = client.post("/api/v1/qa", json={"question": "能跳过申请吗？"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert "[99]" not in data["answer"]
    assert data["refused"] and not data["has_sufficient_evidence"]
    assert data["warnings"]


def test_valid_citation_is_locatable_and_client_cannot_downgrade(qa_client):
    client, retrieve, generate = qa_client
    retrieve.return_value = [chunk()]
    response = client.post(
        "/api/v1/qa", json={"question": "申请需要什么材料？", "data_level": "public"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert generate.await_args.kwargs["data_level"] == DataLevel.INTERNAL
    assert data["has_sufficient_evidence"]
    assert data["citations"][0]["doc_id"] == "DOC-QA-1"
    assert data["citations"][0]["index"] == 1
    assert data["disclaimer"]


@pytest.mark.parametrize("level,expected", [("classified", 403), ("typo", 422)])
def test_invalid_or_classified_data_never_calls_models(qa_client, level, expected):
    client, retrieve, generate = qa_client
    response = client.post("/api/v1/qa", json={"question": "合成问题", "data_level": level})
    assert response.status_code == expected
    retrieve.assert_not_awaited()
    generate.assert_not_awaited()
