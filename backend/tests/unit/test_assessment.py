"""考核规则的反例：缺数据、零分母、重复活动、组织范围及审核不能变成完成。"""

from dataclasses import replace
from datetime import date

import pytest
from pydantic import ValidationError

from app.rules.assessment import (
    SourceBatch,
    SourceRecord,
    batch_snapshot,
    calculate_indicator,
    fingerprint,
    task_state,
)
from app.schemas.assessment import IndicatorCreate, TaskCreate

AS_OF = date(2026, 10, 10)


def rule(**changes):
    return {
        "id": "rule",
        "code": "COUNT",
        "name": "合成指标",
        "version": 1,
        "confirmed": True,
        "source": "meetings",
        "formula": "count",
        "source_options": {"measure": "count"},
        "target": "2",
        "comparison": "gte",
        "unit": "次",
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
        "required_evidence": [],
        "requirement": "合成活动不少于2次",
        **changes,
    }


def record(record_id="activity-1", **changes):
    return SourceRecord(
        id=record_id,
        tenant_id="tenant",
        org_unit_id="branch",
        occurred_on=date(2026, 3, 1),
        version="1",
        **changes,
    )


def calculate(batch, *, current_rule=None, evidence=None):
    return calculate_indicator(
        current_rule or rule(),
        batch,
        evidence or [],
        tenant_id="tenant",
        org_ids={"branch"},
        as_of=AS_OF,
    )


def test_duplicates_are_counted_once_and_order_does_not_change_snapshot():
    first, second = record(), record("activity-2")
    a, b = SourceBatch((first, second, first), True), SourceBatch((second, first), True)
    assert calculate(a)["actual"] == calculate(b)["actual"] == 2
    assert calculate(a)["satisfied"] is True
    assert fingerprint(batch_snapshot(a)) == fingerprint(batch_snapshot(b))


def test_conflicting_source_versions_are_not_resolved_by_input_order():
    a, b = record(), replace(record(), version="2")
    for entries in ((a, b, a), (b, a, b)):
        result = calculate(SourceBatch(entries, True))
        assert result["actual"] == 0
        assert result["satisfied"] is None
        assert result["sources"] == []
        assert "冲突版本" in "".join(result["missing"])


def test_unavailable_source_is_unknown_and_explicitly_complete_empty_source_is_zero():
    unknown = calculate(SourceBatch())
    assert unknown["actual"] is None and unknown["satisfied"] is None
    known = calculate(SourceBatch((), True), current_rule=rule(target="0"))
    assert known["actual"] == 0 and known["satisfied"] is True


def test_other_tenants_organizations_deleted_and_cross_year_records_are_excluded():
    allowed = record()
    entries = (
        allowed,
        replace(record("foreign"), tenant_id="other"),
        replace(record("other-org"), org_unit_id="other"),
        replace(record("deleted"), status="deleted"),
        replace(record("old-year"), occurred_on=date(2025, 12, 31)),
        replace(record("future"), occurred_on=date(2026, 12, 31)),
    )
    result = calculate(SourceBatch(entries, True))
    assert result["actual"] == 1
    assert [source["record_id"] for source in result["sources"]] == [allowed.id]


@pytest.mark.parametrize("measure", ["attendance_rate", "material_rate"])
def test_zero_denominator_is_missing_and_never_passed(measure):
    result = calculate(
        SourceBatch((), True),
        current_rule=rule(formula="percentage", source_options={"measure": measure}, target="0"),
    )
    assert result["actual"] is None and result["satisfied"] is None
    assert any("分母为零" in message for message in result["missing"])


def test_attendance_uses_stable_person_ids_per_activity():
    first = record(participants=("a", "a", "b"), expected_participants=("a", "a", "b", "c"))
    second = record("activity-2", participants=("a",), expected_participants=("a",))
    result = calculate(
        SourceBatch((first, first, second), True),
        current_rule=rule(
            formula="percentage", source_options={"measure": "attendance_rate"}, target="75"
        ),
    )
    assert result["actual"] == 75 and result["satisfied"] is True


def test_attendees_outside_expected_list_block_ratio():
    result = calculate(
        SourceBatch((record(participants=("unknown",), expected_participants=("a",)),), True),
        current_rule=rule(formula="percentage", source_options={"measure": "attendance_rate"}),
    )
    assert result["actual"] is None and result["satisfied"] is None


def test_material_names_cannot_imply_verified_files():
    result = calculate(
        SourceBatch((record(material_complete=None),), True),
        current_rule=rule(
            source="member_materials",
            formula="percentage",
            source_options={"measure": "material_rate"},
        ),
    )
    assert result["actual"] is None and "核验" in "".join(result["missing"])


@pytest.mark.parametrize(
    "status", ["pending", "已废止或失效", "无权限或原材料已删除", "源文件已修订，须重新绑定及审核"]
)
def test_evidence_failure_is_visible_and_blocks_satisfaction(status):
    result = calculate(
        SourceBatch((record(),), True),
        current_rule=rule(target="1", required_evidence=["纪要"]),
        evidence=[{"requirement_key": "纪要", "status": status}],
    )
    assert result["actual"] == 1 and result["satisfied"] is None
    assert status in "".join(result["missing"])


def test_pending_records_and_unconfirmed_school_rule_are_not_formal_results():
    result = calculate(
        SourceBatch((record(status="pending"),), True),
        current_rule=rule(confirmed=False, target="0"),
    )
    assert result["satisfied"] is None and result["actual"] == 0
    assert any("未审核" in message for message in result["missing"])
    assert any("学校指标" in message for message in result["missing"])


def test_future_period_not_started_is_not_zero_completion():
    result = calculate(
        SourceBatch((), True), current_rule=rule(target="0", period_start="2026-11-01")
    )
    assert result["satisfied"] is None
    assert any("尚未开始" in message for message in result["missing"])


def test_deadlines_and_reported_100_percent_cannot_override_missing_evidence():
    task = {"due_date": "2026-10-01", "declared_progress": 100, "review_status": "approved"}
    missing_result = {
        "missing": ["材料待补"],
        "satisfied": None,
        "source": "members",
        "actual": 2,
        "target": 2,
    }
    outcome = task_state(task, missing_result, as_of=AS_OF, advance_days=14)
    assert not outcome["complete"] and outcome["overdue"]
    result = {**missing_result, "missing": [], "satisfied": True}
    complete = task_state(task, result, as_of=AS_OF, advance_days=14)
    assert complete["complete"] and complete["progress"] == 100 and not complete["overdue"]


def test_invalid_free_form_formula_cross_year_and_missing_manual_basis_are_rejected():
    body = {
        "org_unit_id": "school",
        "year": 2026,
        "code": "COUNT",
        "name": "合成",
        "requirement": "合成要求",
        "source": "members",
        "target": 1,
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
    }
    for change in (
        {"formula": "eval(source)"},
        {"period_start": "2025-12-31"},
        {"target": float("nan")},
        {"confirmed": True},
        {"tenant_id": "forged"},
        {"name": "   "},
    ):
        with pytest.raises(ValidationError):
            IndicatorCreate(**{**body, **change})
    with pytest.raises(ValidationError):
        TaskCreate(
            org_unit_id="branch",
            year=2026,
            indicator_code="MANUAL",
            title="合成",
            owner_id="owner",
            due_date="2026-12-31",
            manual_value=0,
            basis="",
            completed_on="2026-01-01",
        )
