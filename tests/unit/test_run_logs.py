"""运行日志单元测试（T-SYS-06E：查询构造、口径说明与行映射）"""
from datetime import datetime

from app.core.audit import make_audit_log
from app.core.constants import AuditResult
from app.services.run_log_service import (
    EVENT_CHOICES,
    RUN_EVENTS,
    RUN_KINDS,
    RunLogFilters,
    RunLogRow,
    build_run_log_query,
)


def _audit(action="job_completed", result="success", **new_value):
    row = make_audit_log(
        tenant_id="t1",
        user_id="u1",
        user_name="张三",
        action=action,
        resource_type="job",
        resource_id="job-1",
        request_id="req-1",
        result=result,
        data_level="internal",
        new_value=new_value,
    )
    row.created_at = datetime(2026, 3, 1, 2, 0)
    return row


def _params(stmt) -> dict:
    return stmt.compile().params


class TestRunLogQuery:
    def test_never_leaves_the_run_event_set(self):
        stmt = build_run_log_query(RunLogFilters(tenant_id="t1"))
        sql = str(stmt)
        assert "audit_logs.tenant_id = " in sql
        assert "audit_logs.action IN" in sql
        assert "audit_logs.is_deleted" in sql
        # 收录的事件就是运行日志的那几个：一次普通请求审计（action=query）不在内
        assert set(EVENT_CHOICES) == set(_params(stmt)["action_1"])

    def test_applies_event_result_and_window(self):
        stmt = build_run_log_query(
            RunLogFilters(
                tenant_id="t1",
                event="job_attempt_failed",
                result="denied",
                start_at=datetime(2026, 3, 1, 1, 0),
                end_at=datetime(2026, 3, 1, 3, 0),
            )
        )
        sql = str(stmt)
        assert "audit_logs.action = " in sql
        assert "audit_logs.result = " in sql
        assert "audit_logs.created_at >= " in sql and "audit_logs.created_at <= " in sql
        values = {value for value in _params(stmt).values() if not isinstance(value, list)}
        assert "job_attempt_failed" in values and "denied" in values
        assert datetime(2026, 3, 1, 1, 0) in values and datetime(2026, 3, 1, 3, 0) in values

    def test_kind_filter_uses_the_task_table(self):
        sql = str(build_run_log_query(RunLogFilters(tenant_id="t1", kind="embedding")))
        assert "durable_jobs.kind" in sql
        assert "audit_logs.resource_id IN" in sql

    def test_newest_first(self):
        sql = str(build_run_log_query(RunLogFilters(tenant_id="t1"))).lower()
        assert "order by audit_logs.created_at desc" in sql

    def test_kinds_match_the_task_model_values(self):
        assert set(RUN_KINDS) == {"member_reminders", "assessment_reminders", "embedding"}


class TestScopeNote:
    def test_blank_note_only_names_the_tenant(self):
        assert RunLogFilters(tenant_id="t1").scope_note() == "租户 t1"

    def test_note_translates_events_and_uses_beijing_time(self):
        note = RunLogFilters(
            tenant_id="t1",
            event="job_attempt_failed",
            kind="member_reminders",
            result="failed",
            start_at=datetime(2026, 3, 1, 2, 0),
        ).scope_note()
        assert "事件 执行失败" in note
        assert "任务类型 member_reminders" in note
        assert "结果 failed" in note
        assert "起 2026-03-01 10:00" in note

    def test_unknown_event_falls_back_to_raw_value(self):
        note = RunLogFilters(tenant_id="t1", event="job_something").scope_note()
        assert "事件 job_something" in note
        assert RUN_EVENTS["job_enqueue"] == "任务入队"
        assert len(RUN_EVENTS) == len(set(RUN_EVENTS.values()))


class TestRowMapping:
    def test_completion_carries_kind_processed_and_duration(self):
        row = _audit(kind="member_reminders", processed=3, duration_ms=120)
        view = RunLogRow.from_audit(row, "member_reminders")
        assert view.event == "job_completed" and view.event_text == "执行完成"
        assert view.kind == "member_reminders"
        assert view.processed == 3 and view.duration_ms == 120
        assert view.attempt is None and view.error_code is None
        assert view.created_at == datetime(2026, 3, 1, 2, 0)

    def test_failure_carries_attempt_status_and_error_code(self):
        row = _audit(
            action="job_attempt_failed",
            result="denied",
            kind="embedding",
            attempt=2,
            status="failed",
            error_code="HTTPException",
            duration_ms=8,
        )
        view = RunLogRow.from_audit(row)
        assert view.result == "denied" and view.status == "failed"
        assert view.attempt == 2 and view.error_code == "HTTPException" and view.duration_ms == 8

    def test_task_table_kind_wins_over_hashed_payload(self):
        # 入队审计的 new_value 是摘要（只有 sha256 / bytes），类型必须来自任务表
        row = _audit(action="job_enqueue", sha256="deadbeef", bytes=42)
        view = RunLogRow.from_audit(row, "assessment_reminders")
        assert view.kind == "assessment_reminders"
        assert view.processed is None and view.duration_ms is None

    def test_scan_event_maps_to_its_label_and_count(self):
        row = _audit(action="member_scheduled_scan", reminder_count=4)
        row.resource_type = "member_reminder"
        view = RunLogRow.from_audit(row)
        assert view.event_text == "党员提醒扫描"
        assert view.kind is None and view.reminder_count == 4

    def test_unknown_event_keeps_raw_action(self):
        row = _audit(action="job_enqueue")
        row.action = "something_else"
        assert RunLogRow.from_audit(row).event_text == "something_else"

    def test_untrusted_payload_types_do_not_leak_into_numbers(self):
        row = _audit(kind=123, processed="3", duration_ms=True, attempt=None)
        view = RunLogRow.from_audit(row)
        assert view.processed is None and view.duration_ms is None
        assert view.attempt is None and view.kind is None

    def test_result_is_always_plain_text(self):
        row = _audit(action="job_completed", result=AuditResult.DENIED)
        view = RunLogRow.from_audit(row)
        assert view.result == "denied" and view.event == "job_completed"
