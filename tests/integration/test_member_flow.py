"""党员发展状态图（LangGraph）与接口集成测试

未安装 redis / httpx 时跳过；未安装 langgraph 时仅跳过图相关用例。
"""
import pytest

pytest.importorskip("redis")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.chains.member_flow import MemberFlow, build_member_graph  # noqa: E402
from app.deps import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

pytestmark = pytest.mark.integration

_QUAL_PAYLOAD = {
    "current_stage": "activist",
    "target_stage": "candidate",
    "materials": ["思想汇报"],
    "days_in_stage": 100,
}


def _user(role: UserRole) -> User:
    user = User(username="u", name="n", password_hash="x", role=role, tenant_id="t1")
    user.id = "u1"
    user.is_active = True
    return user


def test_member_graph_compiles_and_runs():
    pytest.importorskip("langgraph")
    graph = build_member_graph(MemberFlow())
    result = graph.invoke(dict(_QUAL_PAYLOAD))
    assert result["eligible"] is False
    assert any("材料不齐" in b for b in result["blockers"])
    assert result["todos"]
    assert result["note"]


def test_qualification_endpoint_requires_auth():
    with TestClient(app) as client:
        response = client.post("/api/v1/member/qualification-check", json=_QUAL_PAYLOAD)
    assert response.status_code == 401


def test_qualification_endpoint_member_forbidden():
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.MEMBER)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/member/qualification-check", json=_QUAL_PAYLOAD
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_qualification_endpoint_branch_secretary_ok():
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.BRANCH_SECRETARY)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/member/qualification-check",
                json={
                    "current_stage": "applicant",
                    "target_stage": "activist",
                    "materials": ["入党申请书", "党组织谈话记录"],
                    "days_in_stage": 0,
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["data"]["eligible"] is True
