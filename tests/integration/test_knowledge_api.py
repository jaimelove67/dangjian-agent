"""知识库接口权限集成测试（通过依赖覆盖，无需真实数据库）

未安装 redis / httpx 时自动跳过。
"""
import pytest

pytest.importorskip("redis")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_current_tenant, get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

pytestmark = pytest.mark.integration

_FORM = {
    "doc_id": "doc-x",
    "file_name": "a.txt",
    "title": "测试文档",
    "issuer": "测试单位",
    "level": "school",
    "visibility": "school",
    "security_level": "public",
    "effective_date": "2020-01-01",
    "status": "effective",
    "tags": "发展党员",
}
_FILES = {"file": ("a.txt", "第一条 内容。".encode("utf-8"), "text/plain")}


def _make_user(role: UserRole) -> User:
    user = User(
        username="u",
        name="n",
        password_hash="x",
        role=role,
        tenant_id="t1",
    )
    user.id = "u1"
    user.is_active = True
    return user


def test_ingest_without_token_returns_401():
    with TestClient(app) as client:
        response = client.post("/api/v1/knowledge-docs", data=_FORM, files=_FILES)
    assert response.status_code == 401


def test_ingest_member_forbidden_403():
    app.dependency_overrides[get_current_user] = lambda: _make_user(UserRole.MEMBER)
    app.dependency_overrides[get_current_tenant] = lambda: "t1"
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/knowledge-docs", data=_FORM, files=_FILES)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
