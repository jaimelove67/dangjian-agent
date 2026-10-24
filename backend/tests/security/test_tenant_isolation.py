"""租户隔离安全测试（框架文档 9.2 / 开发规范 9.4）"""
import pytest
from sqlalchemy import select

from app.core.tenant import (
    TenantIsolationError,
    _inject_tenant_id_on_flush,
    apply_tenant_filter,
    clear_tenant_context,
    current_tenant_id,
    tenant_context,
)
from app.models.user import User, UserRole

pytestmark = pytest.mark.security


class _FakeSession:
    def __init__(self, new=()):
        self.new = list(new)


def _user_without_tenant() -> User:
    return User(
        username="x",
        name="x",
        password_hash="h",
        role=UserRole.MEMBER,
        tenant_id=None,
    )


@pytest.fixture(autouse=True)
def _clean():
    clear_tenant_context()
    yield
    clear_tenant_context()


def test_context_is_isolated_per_scope():
    with tenant_context("t1"):
        assert current_tenant_id.get() == "t1"
    with tenant_context("t2"):
        assert current_tenant_id.get() == "t2"
    assert current_tenant_id.get() is None


def test_flush_injects_current_tenant():
    user = _user_without_tenant()
    with tenant_context("t9"):
        _inject_tenant_id_on_flush(_FakeSession([user]), None, None)
    assert user.tenant_id == "t9"


def test_flush_without_tenant_rejected():
    user = _user_without_tenant()
    with pytest.raises(TenantIsolationError):
        _inject_tenant_id_on_flush(_FakeSession([user]), None, None)


def test_query_filter_requires_tenant():
    with pytest.raises(TenantIsolationError):
        apply_tenant_filter(select(User), User)


def test_query_filter_binds_tenant():
    stmt = apply_tenant_filter(select(User), User, tenant_id="t1")
    assert "tenant_id" in str(stmt)
