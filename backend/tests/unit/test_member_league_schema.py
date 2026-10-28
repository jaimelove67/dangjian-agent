"""推优资格字段的入参契约与名册摘要。"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.api.v1.member_full import profile_payload
from app.models.member import MemberProfile
from app.schemas.member import MemberCreateRequest, MemberRosterItem
from app.schemas.member_ext import ProfileUpdate

TODAY = date.today()


def test_create_accepts_birth_and_league_dates():
    body = MemberCreateRequest(
        name="张三",
        birth_date=date(TODAY.year - 20, 1, 1),
        league_joined_on=date(TODAY.year - 2, 1, 1),
    )
    assert body.birth_date and body.league_joined_on


def test_create_rejects_future_dates_and_league_before_birth():
    with pytest.raises(ValidationError):
        MemberCreateRequest(name="张三", birth_date=TODAY + timedelta(days=1))
    with pytest.raises(ValidationError):
        MemberCreateRequest(
            name="张三",
            birth_date=date(2000, 1, 1),
            league_joined_on=date(1999, 1, 1),
        )


def test_profile_update_accepts_dates_and_requires_reason():
    body = ProfileUpdate(
        birth_date=date(2000, 1, 1),
        league_joined_on=date(2018, 1, 1),
        reason="补录档案",
    )
    assert body.birth_date == date(2000, 1, 1)
    with pytest.raises(ValidationError):
        ProfileUpdate(birth_date=date(2000, 1, 1))


def test_roster_item_reports_eligibility_without_exposing_dates():
    profile = MemberProfile(
        name="张三",
        org_name="测试支部",
        org_unit_id="org-1",
        current_stage="activist",
        stage_joined_on=TODAY,
        birth_date=date(TODAY.year - 20, 1, 1),
        league_joined_on=date(TODAY.year - 2, 1, 1),
    )
    item = MemberRosterItem.from_profile(profile)
    assert item.league_eligible is True
    assert "年满18周岁" in item.league_eligibility_note
    assert "birth_date" not in item.model_dump()
    # 档案详情是补录入口，需回传日期；名册列表只回摘要。
    payload = profile_payload(profile)
    assert payload["birth_date"] == date(TODAY.year - 20, 1, 1).isoformat()
    assert payload["league_joined_on"] == date(TODAY.year - 2, 1, 1).isoformat()


def test_roster_item_marks_missing_dates_as_unverified():
    profile = MemberProfile(
        name="李四",
        org_name="测试支部",
        org_unit_id="org-1",
        current_stage="activist",
        stage_joined_on=TODAY,
    )
    item = MemberRosterItem.from_profile(profile)
    assert item.league_eligible is None
    assert "缺少" in item.league_eligibility_note


def test_roster_item_marks_underage_as_ineligible():
    profile = MemberProfile(
        name="王五",
        org_name="测试支部",
        org_unit_id="org-1",
        current_stage="activist",
        stage_joined_on=TODAY,
        birth_date=date(TODAY.year - 17, 1, 1),
        league_joined_on=date(TODAY.year - 2, 1, 1),
    )
    item = MemberRosterItem.from_profile(profile)
    assert item.league_eligible is False
    assert "18周岁" in item.league_eligibility_note
