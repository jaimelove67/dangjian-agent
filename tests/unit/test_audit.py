"""审计模块单元测试（统一接口 + 只追加约束）"""
import pytest

from app.core.audit import (
    AuditError,
    _prevent_audit_mutation,
    make_audit_log,
    query_audit_logs,
)
from app.core.constants import AuditAction, AuditResult, DataLevel
from app.models.audit import AuditLog


def _valid_log() -> AuditLog:
    return make_audit_log(
        tenant_id="t1",
        user_id="u1",
        user_name="张三",
        action=AuditAction.CREATE,
        resource_type="knowledge_doc",
        resource_id="d1",
        request_id="req-1",
        result=AuditResult.SUCCESS,
        data_level=DataLevel.SENSITIVE,
        old_value={"title": "旧"},
        new_value={"title": "新"},
    )


class TestMakeAuditLog:
    def test_fields_populated(self):
        log = _valid_log()
        assert isinstance(log, AuditLog)
        assert log.tenant_id == "t1"
        assert log.user_id == "u1"
        assert log.action == "create"
        assert log.result == "success"
        assert log.data_level == "sensitive"
        assert log.resource_id == "d1"
        assert log.old_value == {"title": "旧"}
        assert log.new_value == {"title": "新"}

    def test_accepts_plain_strings(self):
        log = make_audit_log(
            tenant_id="t1", user_id="u1", user_name="x",
            action="query", resource_type="user", request_id="r1",
            result="success", data_level="public",
        )
        assert log.action == "query"
        assert log.result == "success"

    def test_invalid_data_level_rejected(self):
        with pytest.raises(AuditError):
            make_audit_log(
                tenant_id="t1", user_id="u1", user_name="x",
                action="create", resource_type="user", request_id="r1",
                result="success", data_level="bogus",
            )

    @pytest.mark.parametrize("field", ["tenant_id", "user_id", "request_id"])
    def test_missing_required_rejected(self, field):
        kwargs = dict(
            tenant_id="t1", user_id="u1", user_name="x", action="create",
            resource_type="user", request_id="r1", result="success",
        )
        kwargs[field] = ""
        with pytest.raises(AuditError):
            make_audit_log(**kwargs)


class TestAppendOnly:
    class _FakeSession:
        def __init__(self, dirty=(), deleted=(), new=()):
            self.dirty = list(dirty)
            self.deleted = list(deleted)
            self.new = list(new)

    def test_update_rejected(self):
        with pytest.raises(AuditError):
            _prevent_audit_mutation(self._FakeSession(dirty=[_valid_log()]), None, None)

    def test_delete_rejected(self):
        with pytest.raises(AuditError):
            _prevent_audit_mutation(self._FakeSession(deleted=[_valid_log()]), None, None)

    def test_new_allowed(self):
        # 新增不应报错
        _prevent_audit_mutation(self._FakeSession(new=[_valid_log()]), None, None)


class TestQueryBuilder:
    def test_applies_filters(self):
        stmt = query_audit_logs(tenant_id="t1", action="create", resource_type="user")
        sql = str(stmt)
        assert "audit_logs" in sql
        assert "tenant_id" in sql
        assert "action" in sql
