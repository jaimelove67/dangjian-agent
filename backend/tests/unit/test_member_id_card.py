"""身份证号补录契约：格式校验、脱敏出口、版本快照不留明文。

身份证号是开户时的登录账号来源，因此既要能补录，也不能让完整号从任何
读接口或版本表里流出去。
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.v1.member_full import profile_payload
from app.models.member import MemberProfile
from app.schemas.member import MemberRosterItem
from app.schemas.member_ext import ProfileUpdate
from app.services.member_service import MemberDevelopment

VALID = "430102199001011234"


class TestProfileUpdateIdCard:
    def test_normalizes_lowercase_x(self):
        body = ProfileUpdate(id_card_no="43010219900101123x", reason="补录")
        assert body.id_card_no == "43010219900101123X"

    def test_rejects_short_number(self):
        with pytest.raises(ValidationError):
            ProfileUpdate(id_card_no="43010219900101", reason="补录")

    def test_rejects_blank_because_clear_is_not_supported(self):
        with pytest.raises(ValidationError):
            ProfileUpdate(id_card_no="   ", reason="补录")

    def test_absent_field_keeps_profile_untouched(self):
        assert ProfileUpdate(reason="只改批次").id_card_no is None


def _profile(**overrides) -> MemberProfile:
    data = {
        "name": "张三",
        "org_name": "测试支部",
        "org_unit_id": "org-1",
        "current_stage": "applicant",
        "stage_joined_on": date.today(),
        "id_card_no": VALID,
    }
    data.update(overrides)
    return MemberProfile(**data)


class TestIdCardNeverLeavesPlaintext:
    def test_profile_payload_masks_id_card(self):
        payload = profile_payload(_profile())
        assert "id_card_no" not in payload
        assert payload["id_card_masked"] == "430102********1234"

    def test_profile_payload_without_id_card_is_null(self):
        payload = profile_payload(_profile(id_card_no=None))
        assert payload["id_card_masked"] is None

    def test_roster_item_exposes_only_masked(self):
        item = MemberRosterItem.from_profile(_profile())
        assert item.id_card_masked == "430102********1234"

    def test_revision_snapshot_masks_id_card(self):
        snapshot = MemberDevelopment._snapshot(_profile())
        assert snapshot["id_card_no"] == "430102********1234"
