"""租户隔离单元测试：上下文管理 + 写入注入"""
import pytest
from sqlalchemy import select

from app.core.tenant import (
    TenantIsolationError,
    _inject_tenant_id_on_flush,
    apply_tenant_filter,
    bypass_tenant_filter,
    clear_tenant_context,
    get_tenant_id,
    set_tenant_context,
    tenant_context,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole


class _FakeSession:
    def __init__(self, new=()):
        self.new = list(new)


def _make_user() -> User:
    return User(
        username="u",
        name="张三",
        password_hash="x",
        role=UserRole.MEMBER,
        tenant_id=None,
    )


@pytest.fixture(autouse=True)
def _clean_context():
    clear_tenant_context()
    yield
    clear_tenant_context()


class TestTenantContext:
    def test_set_get_clear(self):
        assert get_tenant_id() is None
        set_tenant_context("t1", user_id="u1", data_level="internal")
        assert get_tenant_id() == "t1"
        clear_tenant_context()
        assert get_tenant_id() is None

    def test_empty_tenant_rejected(self):
        with pytest.raises(TenantIsolationError):
            set_tenant_context("")

    def test_context_manager_restores(self):
        with tenant_context("t2"):
            assert get_tenant_id() == "t2"
        assert get_tenant_id() is None

    def test_bypass_flag_toggles(self):
        from app.core.tenant import _bypass_tenant_filter

        assert _bypass_tenant_filter.get() is False
        with bypass_tenant_filter():
            assert _bypass_tenant_filter.get() is True
        assert _bypass_tenant_filter.get() is False


class TestFlushInjection:
    def test_tenant_injected_from_context(self):
        set_tenant_context("t9")
        user = _make_user()
        _inject_tenant_id_on_flush(_FakeSession([user]), None, None)
        assert user.tenant_id == "t9"

    def test_missing_context_raises(self):
        user = _make_user()
        with pytest.raises(TenantIsolationError):
            _inject_tenant_id_on_flush(_FakeSession([user]), None, None)

    def test_existing_tenant_preserved(self):
        set_tenant_context("t9")
        user = _make_user()
        user.tenant_id = "explicit"
        _inject_tenant_id_on_flush(_FakeSession([user]), None, None)
        assert user.tenant_id == "explicit"


class TestQueryFilter:
    def test_requires_tenant(self):
        with pytest.raises(TenantIsolationError):
            apply_tenant_filter(select(Tenant), Tenant)

    def test_builds_where_clause(self):
        stmt = apply_tenant_filter(select(Tenant), Tenant, tenant_id="t1")
        assert "tenant_id" in str(stmt)
