"""供给复核日程与更新周期机制（T-KB-13）纯逻辑测试。"""

from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.constants import DocumentStatus, DocumentValidity, is_review_due
from app.models.knowledge import KnowledgeDoc
from app.services.governance_service import GovernanceValues, SupplyRule
from app.services.knowledge_service import review_due, sync_review_schedule

EFFECTIVE = DocumentStatus.EFFECTIVE.value
VALID = DocumentValidity.EFFECTIVE.value


def draft(
    *,
    effective_date=date(2026, 1, 1),
    maintained_at=None,
    next_review_at=None,
    status=EFFECTIVE,
    validity=VALID,
) -> KnowledgeDoc:
    """构造一个未入库的条目对象，只用于日程规则计算"""
    return KnowledgeDoc(
        tenant_id="t1",
        doc_id="D-1",
        file_name="f.txt",
        title="标题",
        issuer="单位",
        level="school",
        visibility="school",
        security_level="public",
        status=status,
        validity=validity,
        effective_date=effective_date,
        maintained_at=maintained_at,
        next_review_at=next_review_at,
    )


class TestReviewSchedule:
    def test_cycle_is_counted_from_effective_date_before_any_review(self):
        document = draft(effective_date=date(2026, 1, 1))
        assert sync_review_schedule(document, review_cycle_days=365) == date(2027, 1, 1)
        assert document.next_review_at == date(2027, 1, 1)

    def test_cycle_is_counted_from_last_maintenance_once_reviewed(self):
        # 复核确认后以确认时间为基准重排，而不是继续沿用旧内容的到期日。
        document = draft(
            effective_date=date(2026, 1, 1),
            maintained_at=datetime(2026, 6, 1, 9, 30),
        )
        assert sync_review_schedule(document, review_cycle_days=90) == date(2026, 8, 30)

    @pytest.mark.parametrize("cycle", [None, 0])
    def test_no_cycle_means_no_schedule(self, cycle):
        document = draft(next_review_at=date(2020, 1, 1))
        assert sync_review_schedule(document, review_cycle_days=cycle) is None
        assert document.next_review_at is None

    def test_missing_base_date_leaves_no_schedule(self):
        document = draft(effective_date=None, maintained_at=None)
        assert sync_review_schedule(document, review_cycle_days=365) is None
        assert document.next_review_at is None


class TestReviewDue:
    def test_not_due_before_the_due_date(self):
        today = date(2026, 5, 1)
        document = draft(next_review_at=today + timedelta(days=1))
        assert review_due(document, today=today) is False

    def test_due_on_the_due_date(self):
        today = date(2026, 5, 1)
        document = draft(next_review_at=today)
        assert review_due(document, today=today) is True

    def test_due_when_overdue(self):
        today = date(2026, 5, 1)
        document = draft(next_review_at=today - timedelta(days=30))
        assert review_due(document, today=today) is True

    def test_entry_without_schedule_is_not_due(self):
        assert review_due(draft(next_review_at=None), today=date(2030, 1, 1)) is False

    @pytest.mark.parametrize(
        ("status", "validity"),
        [
            (DocumentStatus.ABOLISHED.value, VALID),
            (DocumentStatus.EXPIRED.value, VALID),
            (EFFECTIVE, DocumentValidity.REPEALED.value),
            (EFFECTIVE, DocumentValidity.SUPERSEDED.value),
            (EFFECTIVE, DocumentValidity.PENDING.value),
        ],
    )
    def test_non_effective_entry_has_no_review_duty(self, status, validity):
        # 已废止 / 已失效 / 尚未生效的条目不需要复核：维护信号只对现行有效条目成立。
        document = draft(
            status=status,
            validity=validity,
            next_review_at=date(2020, 1, 1),
        )
        assert review_due(document, today=date(2030, 1, 1)) is False

    def test_unset_validity_and_status_are_treated_as_effective(self):
        # 与迁移回填口径一致：缺字段的历史条目不能因此被判成"无需复核"。
        today = date(2030, 1, 1)
        assert is_review_due(date(2029, 1, 1), status=None, validity=None, today=today) is True


class TestSupplyRule:
    def test_rule_requires_owner_and_cycle_together(self):
        # 只写周期不写责任人，到期后没人知道该找谁；三者必须同时给出。
        valid = SupplyRule(owner_unit="党委组织部", owner_name="张老师", review_cycle_days=365)
        assert valid.review_cycle_days == 365

        with pytest.raises(ValidationError):
            SupplyRule(owner_name="张老师", review_cycle_days=365)
        with pytest.raises(ValidationError):
            SupplyRule(owner_unit="党委组织部", review_cycle_days=365)

    @pytest.mark.parametrize("cycle", [0, 29, 3651])
    def test_cycle_bounds_are_enforced(self, cycle):
        with pytest.raises(ValidationError):
            SupplyRule(owner_unit="党委组织部", owner_name="张老师", review_cycle_days=cycle)

    def test_unknown_authority_is_rejected_with_actionable_message(self):
        with pytest.raises(ValidationError) as exc:
            GovernanceValues(
                knowledge_supply={
                    "party_document": {
                        "owner_unit": "党委组织部",
                        "owner_name": "张老师",
                        "review_cycle_days": 365,
                    }
                }
            )
        assert "权威来源" in str(exc.value)
        assert "party_document" in str(exc.value)

    def test_supply_defaults_to_empty(self):
        assert GovernanceValues().knowledge_supply == {}

    def test_supply_round_trips_through_dump(self):
        values = GovernanceValues(
            knowledge_supply={
                "party_constitution": {
                    "owner_unit": "党委办公室",
                    "owner_name": "李老师",
                    "review_cycle_days": 730,
                }
            }
        )
        assert values.model_dump()["knowledge_supply"] == {
            "party_constitution": {
                "owner_unit": "党委办公室",
                "owner_name": "李老师",
                "review_cycle_days": 730,
            }
        }
