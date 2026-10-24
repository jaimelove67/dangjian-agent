"""三会一课频次合规提醒单元测试（T-ORG-10：周期口径、完成认定与提醒话术）"""
from datetime import date

import pytest

from app.services import activity_frequency as freq
from app.services.activity_frequency import (
    AWAITING_REVIEW,
    MET,
    OPEN,
    RecordFact,
    build_frequency,
    load_requirements,
    period_label,
    period_window,
    periods_in_year,
)
from app.services.activity_service import ACTIVITY_TYPES


def facts(org_id="b1", activity_type="party_lecture", scheduled_on=None, held_on=None, status="draft"):
    return RecordFact(
        org_unit_id=org_id,
        activity_type=activity_type,
        scheduled_on=scheduled_on or held_on or date(2026, 5, 1),
        held_on=held_on,
        review_status=status,
    )


def rows_for(records, as_of=date(2026, 5, 10), branches=None, org_id=None, activity_type=None):
    built = build_frequency(
        load_requirements(), records, branches or [("b1", "第一支部")], as_of
    )
    rows = built["rows"]
    if org_id:
        rows = [row for row in rows if row["org_unit_id"] == org_id]
    if activity_type:
        rows = [row for row in rows if row["activity_type"] == activity_type]
    return rows, built


def only(records, activity_type="party_lecture", **kwargs):
    rows, _ = rows_for(records, activity_type=activity_type, **kwargs)
    assert len(rows) == 1
    return rows[0]


class TestRequirementTable:
    def test_annual_requirement_is_derived_from_the_period(self):
        requirements = load_requirements()
        # 支部工作条例：支部大会、党课每季度至少 1 次；支委会、党小组会每月 1 次
        assert requirements["branch_member_meeting"].annual_required == 4
        assert requirements["branch_committee_meeting"].annual_required == 12
        assert requirements["party_group_meeting"].annual_required == 12
        assert requirements["party_lecture"].annual_required == 4
        assert requirements["other"].annual_required == 0

    def test_period_text_matches_the_configured_frequency(self):
        requirements = load_requirements()
        assert requirements["branch_committee_meeting"].period_text == "每月至少 1 次"
        assert requirements["party_lecture"].period_text == "每季度至少 1 次"
        assert requirements["other"].period_text == "不设固定频次"

    def test_key_set_covers_every_activity_type(self):
        # 频次表与活动类型表各写一份时最容易漏项：这里钉住两者键集相等
        assert set(load_requirements()) == set(ACTIVITY_TYPES)

    def test_other_activity_has_no_period(self):
        assert load_requirements()["other"].period == "none"

    def test_configured_frequency_overrides_the_default(self, tmp_path, monkeypatch):
        path = tmp_path / "business_rules.yaml"
        path.write_text(
            "activity_requirements:\n"
            "  party_lecture:\n"
            "    period: month\n"
            "    per_period: 2\n"
            "    basis: 学校加严要求\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(freq, "RULES_PATH", path)
        requirement = load_requirements()["party_lecture"]
        assert requirement.period == "month"
        assert requirement.annual_required == 24
        assert requirement.period_text == "每月至少 2 次"
        assert requirement.basis == "学校加严要求"

    def test_invalid_config_falls_back_per_field(self, tmp_path, monkeypatch):
        path = tmp_path / "business_rules.yaml"
        path.write_text(
            "activity_requirements:\n"
            "  party_lecture:\n"
            "    period: weekly\n"
            "    per_period: 不是数字\n"
            "  branch_committee_meeting:\n"
            "    period: none\n"
            "    per_period: -3\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(freq, "RULES_PATH", path)
        requirements = load_requirements()
        # 非法周期回落到默认周期；非法次数回落到默认次数
        assert requirements["party_lecture"].period == "quarter"
        assert requirements["party_lecture"].per_period == 1
        # 学校可以显式关掉某类提醒（如未划分党小组）
        assert requirements["branch_committee_meeting"].period == "none"
        assert requirements["branch_committee_meeting"].per_period == 1

    def test_missing_config_uses_builtin_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(freq, "RULES_PATH", tmp_path / "missing.yaml")
        assert load_requirements()["party_lecture"].annual_required == 4


class TestPeriodMath:
    def test_month_window(self):
        assert period_window("month", date(2026, 5, 10)) == (date(2026, 5, 1), date(2026, 5, 31))

    def test_month_window_crosses_december(self):
        assert period_window("month", date(2026, 12, 31)) == (
            date(2026, 12, 1),
            date(2026, 12, 31),
        )

    def test_quarter_window(self):
        assert period_window("quarter", date(2026, 5, 10)) == (date(2026, 4, 1), date(2026, 6, 30))
        assert period_window("quarter", date(2026, 1, 1)) == (date(2026, 1, 1), date(2026, 3, 31))
        assert period_window("quarter", date(2026, 12, 1)) == (
            date(2026, 10, 1),
            date(2026, 12, 31),
        )

    def test_leap_february(self):
        assert period_window("month", date(2024, 2, 5))[1] == date(2024, 2, 29)
        assert period_window("month", date(2026, 2, 5))[1] == date(2026, 2, 28)

    def test_no_period_has_no_window(self):
        assert period_window("none", date(2026, 5, 10)) is None

    def test_period_labels(self):
        assert period_label("month", date(2026, 5, 1)) == "2026 年 5 月"
        assert period_label("quarter", date(2026, 10, 1)) == "2026 年第 4 季度"
        assert period_label("year", date(2026, 1, 1)) == "2026 年度"
        assert period_label("none", date(2026, 1, 1)) == "2026 年度"

    def test_periods_in_year(self):
        assert len(periods_in_year("month", 2026)) == 12
        assert len(periods_in_year("quarter", 2026)) == 4
        assert periods_in_year("year", 2026) == [(date(2026, 1, 1), date(2026, 12, 31))]
        assert periods_in_year("none", 2026) == []

    def test_year_window_covers_the_whole_year(self):
        assert period_window("year", date(2026, 5, 10)) == (date(2026, 1, 1), date(2026, 12, 31))
        assert period_window("year", date(2026, 12, 31)) == (date(2026, 1, 1), date(2026, 12, 31))


class TestOrganizationalLifeMeeting:
    """组织生活会按年度计频次：季度口径套不上去（一年只有一次，且一般排在第四季度）。"""

    def test_organizational_life_is_annual(self):
        requirement = load_requirements()["organizational_life_meeting"]
        assert requirement.period == "year"
        assert requirement.per_period == 1
        assert requirement.annual_required == 1
        assert requirement.period_text == "每年至少 1 次"

    def test_current_year_not_yet_held_is_open_not_a_gap(self):
        rows, built = rows_for([], activity_type="organizational_life_meeting")
        assert rows[0]["state"] == OPEN
        assert rows[0]["period_label"] == "2026 年度"
        # 本年度还没结束，不算"已结束周期缺口"：不能把未到期说成违规
        assert [
            gap for gap in built["gaps"] if gap["activity_type"] == "organizational_life_meeting"
        ] == []

    def test_organizational_life_approved_meets_the_year(self):
        row = only(
            [facts(activity_type="organizational_life_meeting", held_on=date(2026, 4, 2), status="approved")],
            activity_type="organizational_life_meeting",
        )
        assert row["state"] == MET
        assert row["annual_required"] == 1

    def test_reminder_names_the_year_deadline(self):
        row = only([], activity_type="organizational_life_meeting")
        assert "2026 年度" in row["reminder"]
        assert "2026-12-31" in row["reminder"]


class TestCurrentPeriod:
    def test_approved_record_meets_the_requirement(self):
        row = only([facts(held_on=date(2026, 5, 6), status="approved")])
        assert row["state"] == MET
        assert row["performed"] == 1 and row["missing"] == 0
        assert "已达要求" in row["reminder"]

    def test_awaiting_review_is_not_counted_as_done(self):
        row = only([facts(held_on=date(2026, 5, 6), status="pending")])
        assert row["state"] == AWAITING_REVIEW
        assert row["performed"] == 0 and row["awaiting_review"] == 1 and row["missing"] == 1
        # 已召开但没审不等于没开：提醒必须指向"去完成审核"
        assert "尚未通过人工审核" in row["reminder"]
        assert "完成纪要审核" in row["reminder"]

    def test_draft_held_record_also_awaits_review(self):
        row = only([facts(held_on=date(2026, 5, 6), status="draft")])
        assert row["state"] == AWAITING_REVIEW

    def test_rejected_record_awaits_review(self):
        row = only([facts(held_on=date(2026, 5, 6), status="rejected")])
        assert row["state"] == AWAITING_REVIEW

    def test_open_state_gives_deadline_and_scheduled_count(self):
        row = only(
            [facts(activity_type="branch_committee_meeting", scheduled_on=date(2026, 5, 20))],
            activity_type="branch_committee_meeting",
        )
        assert row["state"] == OPEN
        assert row["scheduled"] == 1 and row["missing"] == 1
        assert "最晚 2026-05-31 前召开" in row["reminder"]
        assert "已安排待召开 1 次" in row["reminder"]
        assert row["days_left"] == 21

    def test_record_held_outside_the_window_is_ignored(self):
        # 4 月的支委会不算 5 月：周期口径不跨期抵扣
        row = only(
            [facts(activity_type="branch_committee_meeting", held_on=date(2026, 4, 30), status="approved")],
            activity_type="branch_committee_meeting",
        )
        assert row["performed"] == 0 and row["state"] == OPEN

    def test_scheduled_outside_the_window_is_ignored(self):
        row = only(
            [facts(activity_type="branch_committee_meeting", scheduled_on=date(2026, 6, 1))],
            activity_type="branch_committee_meeting",
        )
        assert row["scheduled"] == 0

    def test_quarter_window_covers_its_months(self):
        row = only([facts(held_on=date(2026, 4, 2), status="approved")])
        assert row["state"] == MET and row["period_label"] == "2026 年第 2 季度"

    def test_facts_are_scoped_by_activity_type(self):
        # 支委会开过不能让支部大会"达标"：修复前正是把不同活动的记录混在一个池子里
        rows, _ = rows_for(
            [facts(activity_type="branch_committee_meeting", held_on=date(2026, 5, 6), status="approved")]
        )
        by_type = {row["activity_type"]: row for row in rows}
        assert by_type["branch_committee_meeting"]["state"] == MET
        assert by_type["branch_member_meeting"]["state"] == OPEN
        assert by_type["party_lecture"]["state"] == OPEN

    def test_facts_are_scoped_by_org(self):
        rows, _ = rows_for(
            [facts(org_id="b1", held_on=date(2026, 5, 6), status="approved")],
            branches=[("b1", "第一支部"), ("b2", "第二支部")],
        )
        first = [row for row in rows if row["org_unit_id"] == "b1"]
        second = [row for row in rows if row["org_unit_id"] == "b2"]
        assert all(row["performed"] == 1 for row in first if row["activity_type"] == "party_lecture")
        assert all(row["performed"] == 0 for row in second)

    def test_row_carries_the_period_and_basis(self):
        row = only([facts()])
        assert row["period"] == "quarter"
        assert row["required"] == 1 and row["annual_required"] == 4
        assert row["period_start"] == "2026-04-01" and row["period_end"] == "2026-06-30"
        assert "每季度" in row["basis"]

    def test_not_required_activity_has_no_row(self):
        rows, built = rows_for([])
        assert "other" not in {row["activity_type"] for row in rows}
        assert rows and all(row["activity_type"] != "other" for row in built["rows"])


class TestReminders:
    def test_only_actionable_rows_become_reminders(self):
        rows, built = rows_for(
            [
                facts(activity_type="party_lecture", held_on=date(2026, 5, 6), status="approved"),
                facts(activity_type="branch_committee_meeting", held_on=date(2026, 5, 6)),
            ]
        )
        reminded = {row["activity_type"] for row in built["reminders"]}
        assert "branch_committee_meeting" in reminded
        assert "party_lecture" not in reminded
        assert len(built["reminders"]) == len(rows) - 1

    def test_reminder_names_the_org_and_period(self):
        _, built = rows_for(
            [facts(activity_type="branch_committee_meeting", scheduled_on=date(2026, 5, 20))]
        )
        reminder = next(
            row for row in built["reminders"] if row["activity_type"] == "branch_committee_meeting"
        )
        assert reminder["org_unit_name"] == "第一支部"
        assert reminder["period_label"] == "2026 年 5 月"
        assert reminder["reminder"].startswith("2026 年 5 月支委会")


class TestGaps:
    def test_only_ended_periods_become_gaps(self):
        # as_of = 2026-05-10：1—4 月已结束，5 月是当前周期（走提醒，不重复记缺口）
        _, built = rows_for([], activity_type="party_lecture")
        target = [gap for gap in built["gaps"] if gap["activity_type"] == "party_lecture"]
        assert len(target) == 1
        assert target[0]["missed_periods"] == ["2026 年第 1 季度"]
        assert target[0]["missing_total"] == 1

    def test_month_activity_lists_every_ended_month(self):
        _, built = rows_for([])
        target = [gap for gap in built["gaps"] if gap["activity_type"] == "branch_committee_meeting"]
        assert target[0]["missed_periods"] == [
            "2026 年 1 月",
            "2026 年 2 月",
            "2026 年 3 月",
            "2026 年 4 月",
        ]
        assert target[0]["missing_total"] == 4
        assert "本年度已结束 4 个周期中 4 个未达标" in target[0]["text"]

    def test_met_period_is_not_a_gap(self):
        _, built = rows_for(
            [facts(activity_type="party_lecture", held_on=date(2026, 2, 3), status="approved")]
        )
        assert all(gap["activity_type"] != "party_lecture" for gap in built["gaps"])

    def test_gap_distinguishes_held_but_unapproved(self):
        _, built = rows_for(
            [facts(activity_type="party_lecture", held_on=date(2026, 2, 3), status="pending")]
        )
        target = [gap for gap in built["gaps"] if gap["activity_type"] == "party_lecture"][0]
        assert target["missing_total"] == 1 and target["awaiting_total"] == 1
        assert "已召开待审核 1 次" in target["text"]

    def test_gaps_are_per_branch_and_type(self):
        _, built = rows_for(
            [], branches=[("b1", "第一支部"), ("b2", "第二支部")], activity_type="party_lecture"
        )
        keys = {(gap["org_unit_id"], gap["activity_type"]) for gap in built["gaps"]}
        assert ("b1", "party_lecture") in keys and ("b2", "party_lecture") in keys


class TestNoBranches:
    def test_empty_branch_list_yields_nothing(self):
        built = build_frequency(load_requirements(), [facts(held_on=date(2026, 5, 6))], [], date(2026, 5, 10))
        assert built == {"rows": [], "reminders": [], "gaps": []}


@pytest.mark.parametrize("origin", [date(2026, 1, 1), date(2026, 12, 31), date(2026, 7, 1)])
def test_never_raises_on_any_day_of_the_year(origin):
    rows, _ = rows_for([], as_of=origin)
    assert rows and all(row["required"] >= 1 for row in rows)
