"""团组织推优资格规则：18周岁与1年团龄的边界。"""

from datetime import date

from app.rules.member_league import age_on, league_eligibility


def test_age_is_counted_by_anniversary():
    assert age_on(date(2000, 5, 1), date(2018, 5, 1)) == 18
    assert age_on(date(2000, 5, 1), date(2018, 4, 30)) == 17
    assert age_on(date(2000, 2, 29), date(2018, 2, 28)) == 18


def test_missing_profile_dates_cannot_be_judged():
    eligible, note = league_eligibility(None, date(2020, 1, 1), date(2026, 1, 1))
    assert eligible is None
    assert "出生年月" in note
    eligible, note = league_eligibility(date(2000, 1, 1), None, date(2026, 1, 1))
    assert eligible is None
    assert "入团时间" in note


def test_age_boundary_is_enforced():
    birth = date(2000, 1, 1)
    joined = date(2014, 1, 1)
    assert league_eligibility(birth, joined, date(2018, 1, 1))[0] is True
    eligible, note = league_eligibility(birth, joined, date(2017, 12, 31))
    assert eligible is False
    assert "年满18周岁" in note


def test_league_tenure_boundary_is_enforced():
    birth = date(2000, 1, 1)
    joined = date(2020, 5, 1)
    assert league_eligibility(birth, joined, date(2021, 5, 1))[0] is True
    eligible, note = league_eligibility(birth, joined, date(2021, 4, 30))
    assert eligible is False
    assert "入团满1年" in note
    # 2月29日入团：非闰年按2月28日满周年处理
    assert league_eligibility(birth, date(2020, 2, 29), date(2021, 2, 28))[0] is True


def test_future_dates_are_rejected_as_inconsistent():
    eligible, note = league_eligibility(date(2000, 1, 1), date(2021, 1, 1), date(2020, 12, 31))
    assert eligible is False
    assert "晚于推荐日期" in note


def test_age_over_28_is_allowed_with_a_scope_reminder():
    eligible, note = league_eligibility(date(1990, 1, 1), date(2008, 1, 1), date(2026, 1, 1))
    assert eligible is True
    assert "超过28周岁" in note
