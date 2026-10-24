"""选优结论与团组织推优的边界单元测试（T-MEM-13、T-MEM-06）。

钉住三件不能退让的事：**结论由人填写**（系统不按票数自动出名单）、**必须第二位组织人员
审核**（自审与低权限角色都过不去）、**团组织推优只登记不判断年龄**（缺记录不阻断业务）；
另外钉住密级标注 / 脱敏与请求契约不能伪造结论内容。
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import app
from app.models.member import MemberLeagueRecommendation, MemberProfile, MemberSelection
from app.models.user import UserRole
from app.rules.data_sensitivity import CLASSIFIED_NOTE, REDACTED_NOTE
from app.schemas.member_selection import SelectionCreate
from app.services.member_selection_service import (
    AGE_NOTICE,
    REPORT_HINTS,
    STATUS_LABELS,
    MemberSelectionService,
)

# 发展阶段链上"只能向前"的四个目标阶段（与细则环节一一对应）
TARGET_STAGES = ("activist", "candidate", "probationary", "member")


def build_service(role: UserRole = UserRole.BRANCH_SECRETARY) -> MemberSelectionService:
    """纯逻辑用例用：``__init__`` 不查库（权限由角色推导）。"""
    user = SimpleNamespace(id="u1", tenant_id="t1", role=role)
    return MemberSelectionService(SimpleNamespace(), user)


def full_conclusion(**overrides):
    fields = {
        "review_status": "draft",
        "basis": "依据第 2 轮选优投票汇总与培养记录评分",
        "candidates": [{"profile_id": "p1", "member_name": "张三", "stage": "activist"}],
        "research_on": date.today(),
        "target_stage": "candidate",
        "revision": 1,
        "submitted_by": None,
    }
    return MemberSelection(**{**fields, **overrides})


def test_conclusion_needs_human_list_and_basis():
    """名单与依据都是人填的：空名单 / 空依据逐条说清，缺一项不许送审。"""
    service = build_service()
    empty = full_conclusion(candidates=[], basis="")
    assert service.missing(empty) == [
        "拟推荐名单不能为空",
        "结论依据待填（请写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录）",
    ]
    assert service.missing(full_conclusion()) == []


def test_future_research_date_is_rejected():
    """研究日期不能在未来：结论要有已经发生的研究程序。"""
    service = build_service()
    service._check_research_date(date.today())
    with pytest.raises(HTTPException) as exc:
        service._check_research_date(date.today() + timedelta(days=1))
    assert exc.value.status_code == 422
    assert "研究日期不能晚于今天" in exc.value.detail
    assert service.missing(full_conclusion(research_on=date.today() + timedelta(days=1)))


def test_target_stage_must_move_forward():
    """结论是"往哪推"的依据：同阶段、回退、非发展阶段都不许登记。"""
    service = build_service()
    activist = MemberProfile(name="张三", current_stage="activist", org_unit_id="o1")
    service._check_forward_stage(activist, "candidate")
    for target in ("activist", "applicant"):
        with pytest.raises(HTTPException) as exc:
            service._check_forward_stage(activist, target)
        assert exc.value.status_code == 422
    rejected = MemberProfile(name="李四", current_stage="rejected", org_unit_id="o1")
    with pytest.raises(HTTPException):
        service._check_forward_stage(rejected, "candidate")


def test_only_approved_is_effective_and_self_review_is_blocked():
    service = build_service()
    pending = full_conclusion(review_status="pending", submitted_by="u2")
    assert service.selection_view(pending)["effective"] is False
    assert service.selection_view(pending)["can_review"] is True
    # 自己提交的不能自己审核：界面给出的"可审核"标记也必须是假
    assert service.selection_view(full_conclusion(review_status="pending", submitted_by="u1"))[
        "can_review"
    ] is False
    assert service.selection_view(full_conclusion(review_status="approved"))["effective"] is True
    assert service.selection_view(full_conclusion(review_status="rejected"))["effective"] is False


def test_lower_role_cannot_review_conclusions():
    """审核走 stage_transition 这条权限线：没有该权限的角色连"可审核"都不给。"""
    assert build_service().can_decide is True
    lower = build_service(UserRole.MEMBER)
    assert lower.can_decide is False
    assert lower.selection_view(full_conclusion(review_status="pending", submitted_by="u2"))[
        "can_review"
    ] is False


def test_conclusion_view_is_marked_with_level_and_boundary():
    view = build_service().selection_view(full_conclusion())
    assert view["data_level"] == "sensitive"
    assert view["data_level_label"] == "敏感"
    assert view["cloud_allowed"] is False
    assert view["embedding_allowed"] is True
    # 结论不自动改阶段、不自动报送：提示只指向人工台账
    assert "不自动改阶段" in view["boundary"]
    assert "台账" in view["next_step_hint"]


def test_report_hints_cover_every_target_stage():
    assert set(REPORT_HINTS) == set(TARGET_STAGES)
    for hint in REPORT_HINTS.values():
        assert hint and "台账" in hint


def test_status_labels_cover_all_review_states():
    assert set(STATUS_LABELS) == {"draft", "pending", "approved", "rejected"}
    assert set(STATUS_LABELS.values()) == {"草稿", "待审核", "已通过", "已退回"}


def test_recommendation_note_is_redacted_for_lower_level_viewer():
    """推优说明是第三人信息：同级查看者看到原文，低等级查看者只看到占位。"""
    row = MemberLeagueRecommendation(
        stage="activist",
        league_org="某某学院团委",
        note="团支书反映该同志表现积极，同学评价好",
        data_level="sensitive",
        revision=1,
    )
    visible = build_service(UserRole.BRANCH_SECRETARY).recommendation_view(row)
    assert visible["note"] == "团支书反映该同志表现积极，同学评价好"
    assert visible["redacted_fields"] == []
    masked = build_service(UserRole.MEMBER).recommendation_view(row)
    assert masked["note"] == REDACTED_NOTE
    assert masked["redacted_fields"] == ["note"]


def test_raised_recommendation_level_hides_note_and_blocks_embedding():
    """学校把推优口径调高到涉密时：连组织人员也看不到正文，且不进向量库。"""
    row = MemberLeagueRecommendation(
        stage="candidate",
        league_org="某某学院团委",
        note="团组织意见原文",
        data_level="classified",
        revision=1,
    )
    view = build_service(UserRole.BRANCH_SECRETARY).recommendation_view(row)
    assert view["note"] == CLASSIFIED_NOTE
    assert view["cloud_allowed"] is False
    assert view["embedding_allowed"] is False


def test_age_is_never_judged_and_missing_record_never_blocks():
    """名册里没有出生年月：推优只提示、不判断年龄、也不阻断业务。"""
    assert "系统不判断年龄" in AGE_NOTICE
    assert "不阻断" in AGE_NOTICE
    view = build_service().recommendation_view(
        MemberLeagueRecommendation(
            stage="activist", league_org="某某学院团委", note="", data_level="sensitive"
        )
    )
    assert view["age_notice"] == AGE_NOTICE
    # 缺推优记录不进"送审必填项"：不阻断选优与阶段流转
    assert build_service().missing(full_conclusion()) == []


def test_request_cannot_forge_conclusion_content():
    base = {
        "batch_no": "2026-1",
        "round_no": 1,
        "target_stage": "candidate",
        "candidate_ids": ["p1"],
        "basis": "依据第 2 轮投票汇总",
        "research_on": date.today(),
        "research_method": "committee",
        "reason": "支部研究登记",
    }
    SelectionCreate(**base)
    forged = (
        {"review_status": "approved"},
        {"submitted_by": "u2"},
        {"reviewed_by": "u3"},
        {"candidates": [{"profile_id": "p1"}]},
        {"evidence": {"voter_count": 99}},
        {"data_level": "public"},
        {"revision": 5},
    )
    for extra in forged:
        with pytest.raises(ValidationError):
            SelectionCreate(**{**base, **extra})
    with pytest.raises(ValidationError):
        SelectionCreate(**{**base, "candidate_ids": ["p1", "p1"]})
    with pytest.raises(ValidationError):
        SelectionCreate(**{**base, "target_stage": "applicant"})
    with pytest.raises(ValidationError):
        SelectionCreate(**{**base, "basis": "   "})


def test_create_contract_only_takes_human_inputs():
    """接口只收"人填的东西"：结论内容、审核状态与证据快照都不在契约里。"""
    properties = app.openapi()["components"]["schemas"]["SelectionCreate"]["properties"]
    assert set(properties) == {
        "batch_no",
        "round_no",
        "target_stage",
        "candidate_ids",
        "basis",
        "research_on",
        "research_method",
        "reason",
    }
