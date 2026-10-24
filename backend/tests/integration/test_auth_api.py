"""鉴权接口集成测试（通过依赖覆盖，无需真实数据库）

未安装 redis / httpx 时自动跳过。
"""
import pytest

pytest.importorskip("redis")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

pytestmark = pytest.mark.integration


def _fake_user() -> User:
    user = User(
        username="alice",
        name="爱丽丝",
        password_hash="hashed",
        role=UserRole.BRANCH_SECRETARY,
        tenant_id="t1",
        email="alice@example.com",
        phone="13812345678",
    )
    user.id = "u1"
    user.is_active = True
    return user


def test_me_without_token_returns_401():
    """未携带令牌 → 401"""
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "detail" in response.json()


def test_me_with_override_returns_masked_user():
    """认证通过 → 返回脱敏后的用户信息"""
    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"] == "alice"
    assert data["role"] == "branch_secretary"
    assert data["phone"] == "138****5678"
    assert data["email"] == "a***@example.com"


def test_trace_id_header_present():
    """每个响应都应带 trace_id 头"""
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
