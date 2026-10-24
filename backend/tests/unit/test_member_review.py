"""民主评议党员单元测试（T-ORG-11：必填项、等次口径、测评票数、进度与来源边界）。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.user import UserRole
from app.rules import data_sensitivity as ds
from app.schemas.member_review import ReviewCreate, ReviewTest
from app.services import member_review_service as reviews
from app.services.member_review_service import (
    DEFAULT_GRADES,
    GRADE_LABELS,
    MemberReviewService,
    load_rules,
    stage_label,
)


def service(role=UserRole.BRANCH_SECRETARY, user_id="u-secretary"):
    user = SimpleNamespace(tenant_id="t1", id=user_id, role=role)
    return MemberReviewService(db=SimpleNamespace(), user=user)


def row(**overrides):
    values = {
        "id": "r1",
        "profile_id": "p1",
        "member_name": "合成党员",
        "stage": "member",
        "org_unit_id": "b1",
        "org_name": "第一支部",
        "revision": 3,
        "review_status": "draft",
        "submitted_by": None,
        "grade": "",
        "basis": "",
        "rectification": "",
        "procedure": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestEvaluationTest:
    """测评票数是汇总，不是逐人明细；但汇总本身不能自相矛盾。"""

    def test_attendance_cannot_exceed_eligible(self):
        with pytest.raises(ValidationError):
            ReviewTest(eligible=10, attended=11)

    def test_votes_cannot_exceed_attendance(self):
        with pytest.raises(ValidationError):
            ReviewTest(eligible=10, attended=5, outstanding=3, qualified=3)

    def test_abstention_is_allowed(self):
        test = ReviewTest(eligible=10, attended=5, outstanding=2, qualified=1)
        assert test.attended == 5

    def test_zero_attendance_skips_the_sum_check(self):
        # 未登记人数时不该被"票数 > 实到 0"误伤
        assert ReviewTest(outstanding=1).attended == 0


class TestGradeContract:
    def test_grade_must_be_one_of_the_configured_levels(self):
        with pytest.raises(ValidationError):
            ReviewCreate(year=2026, profile_id="p1", grade="excellent", reason="录入")

    @pytest.mark.parametrize("grade", sorted(GRADE_LABELS))
    def test_every_configured_grade_is_accepted(self, grade):
        body = ReviewCreate(year=2026, profile_id="p1", grade=grade, reason="录入")
        assert body.grade == grade

    def test_grade_is_optional_until_grading(self):
        assert ReviewCreate(year=2026, profile_id="p1", reason="录入").grade is None


class TestSubmissionRequirements:
    def test_missing_lists_every_blocking_field_once(self):
        assert service().missing(row()) == [
            "个人自评待录",
            "支部评定意见待录",
            "评定等次待定",
            "评定依据待填",
        ]

    def test_filled_record_has_nothing_missing(self):
        filled = row(
            grade="qualified",
            procedure={"self_assessment": "自评", "branch_opinion": "支部意见"},
            basis="民主测评与日常表现",
        )
        assert service().missing(filled) == []

    def test_peer_review_and_test_are_advisories_not_blockers(self):
        # 线上线下混用时互评与测评可能没留下汇总：提示但不逼组织编造
        filled = row(
            grade="qualified",
            procedure={"self_assessment": "自评", "branch_opinion": "支部意见"},
            basis="民主测评与日常表现",
        )
        assert service().missing(filled) == []
        assert service().advisories(filled) == ["未登记党员互评意见", "未登记民主测评票数"]

    def test_whitespace_is_not_content(self):
        blank = row(
            grade="qualified",
            procedure={"self_assessment": "   ", "branch_opinion": "\n"},
            basis="  ",
        )
        assert service().missing(blank) == ["个人自评待录", "支部评定意见待录", "评定依据待填"]


class TestRules:
    def test_defaults_cover_the_four_standard_grades(self):
        rules = load_rules()
        assert rules["grades"] == list(DEFAULT_GRADES)
        assert rules["outstanding_notice"]
        assert rules["unqualified_notice"]

    def test_config_drives_the_grade_list(self, tmp_path, monkeypatch):
        path = tmp_path / "business_rules.yaml"
        path.write_text(
            "democratic_review:\n"
            "  grades: [outstanding, qualified]\n"
            "  outstanding_notice: 本校优秀比例不超过 30%\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(reviews, "RULES_PATH", Path(path))
        rules = load_rules()
        assert rules["grades"] == ["outstanding", "qualified"]
        assert rules["outstanding_notice"] == "本校优秀比例不超过 30%"

    def test_unknown_grade_keys_are_dropped_with_a_fallback(self, tmp_path, monkeypatch):
        path = tmp_path / "business_rules.yaml"
        path.write_text("democratic_review:\n  grades: [excellent]\n", encoding="utf-8")
        monkeypatch.setattr(reviews, "RULES_PATH", Path(path))
        assert load_rules()["grades"] == list(DEFAULT_GRADES)

    def test_missing_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reviews, "RULES_PATH", Path(tmp_path / "absent.yaml"))
        assert load_rules()["grades"] == list(DEFAULT_GRADES)


class TestTargetView:
    def test_not_started_row_is_explicit(self):
        view = service().target_view(SimpleNamespace(
            id="p1", name="合成党员", current_stage="member", org_unit_id="b1", org_name="第一支部"
        ), None, "第一支部")
        assert view["review_status"] == "not_started"
        assert view["review_id"] is None
        assert view["stage_label"] == "正式党员"
        assert view["missing"] == []
        assert view["can_review"] is False

    def test_grade_is_labelled_from_the_single_source(self):
        view = service().target_view(None, row(grade="unqualified"), "第一支部")
        assert view["grade_label"] == "不合格"
        assert view["in_roster"] is False

    def test_submitter_cannot_be_offered_the_review_button(self):
        pending = row(review_status="pending", submitted_by="u-secretary")
        assert service(user_id="u-secretary").target_view(None, pending, "支部")["can_review"] is False
        assert service(user_id="u-other").target_view(None, pending, "支部")["can_review"] is True

    def test_without_review_permission_there_is_no_review_button(self):
        pending = row(review_status="pending", submitted_by="u-other")
        assert service(role=UserRole.MEMBER).target_view(None, pending, "支部")["can_review"] is False

    def test_only_pending_rows_are_reviewable(self):
        approved = row(review_status="approved", submitted_by="u-other")
        assert service(user_id="u-secretary").target_view(None, approved, "支部")["can_review"] is False


class TestStageLabel:
    def test_reads_back_the_two_participating_stages(self):
        assert stage_label("member") == "正式党员"
        assert stage_label("probationary") == "预备党员"

    def test_unknown_or_empty_stage_does_not_raise(self):
        # 历史行里可能出现已不在枚举内的阶段值，读不出就留空而不是整页 500
        assert stage_label("") == ""
        assert stage_label("gone") == ""


class TestNotices:
    def test_notice_does_not_promise_automatic_grading(self):
        assert "不按票数" in reviews.REVIEW_NOTICE

    def test_outstanding_notice_defers_the_ratio_to_the_upper_level(self):
        assert "系统不自动" in load_rules()["outstanding_notice"]

    def test_unqualified_notice_leaves_disposal_to_the_party_organization(self):
        assert "党章党规" in load_rules()["unqualified_notice"]


class TestThirdPartyRedaction:
    """字段级敏感分级（T-MEM-12）：党员互评等第三人字段按查看者等级收敛。"""

    def test_same_level_viewer_reads_the_full_procedure(self):
        data = service().visible_review(
            {"procedure": {"self_assessment": "自评", "peer_review": "张三说他最近不积极"}},
            "sensitive",
        )
        assert data["procedure"]["peer_review"] == "张三说他最近不积极"
        assert data["redacted_fields"] == []
        assert data["data_level"] == "sensitive" and data["cloud_allowed"] is False

    def test_lower_level_viewer_loses_the_peer_review_text(self):
        data = service(role=UserRole.MEMBER).visible_review(
            {"procedure": {"self_assessment": "自评", "peer_review": "张三说他最近不积极"}},
            "sensitive",
        )
        assert data["procedure"]["peer_review"] == ds.REDACTED_NOTE
        assert data["procedure"]["self_assessment"] == "自评"
        assert data["redacted_fields"] == ["procedure.peer_review"]

    def test_history_snapshots_are_redacted_too(self):
        data = service(role=UserRole.MEMBER).visible_review(
            {"procedure": {}, "revisions": [{"revision": 2, "snapshot": {"procedure": {"peer_review": "互评"}}}]},
            "sensitive",
        )
        assert data["revisions"][0]["snapshot"]["procedure"]["peer_review"] == ds.REDACTED_NOTE
        assert data["redacted_fields"] == ["revisions.snapshot.procedure.peer_review"]

    def test_classified_review_hides_the_text_from_everyone(self):
        data = service().visible_review(
            {"procedure": {"peer_review": "互评"}}, "classified"
        )
        assert data["procedure"]["peer_review"] == ds.CLASSIFIED_NOTE

    def test_redaction_placeholder_is_never_written_back(self):
        assert MemberReviewService._without_placeholders(
            {"peer_review": ds.REDACTED_NOTE, "branch_opinion": "同意"}
        ) == {"branch_opinion": "同意"}
        assert MemberReviewService._without_placeholders(
            {"peer_review": "张三说他最近不积极"}
        ) == {"peer_review": "张三说他最近不积极"}
