"""组织关系接转（T-MEM-14）纯函数与输入契约：不需要数据库与会话。"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.rules.member_stages import STAGE_LABELS, MemberStage, load_stage_rules
from app.schemas.member_transfer import TransferCreate, TransferRevoke, TransferSettle
from app.services.member_transfer_service import (
    DEFAULT_LETTER_VALID_DAYS,
    DIRECTION_LABELS,
    STATE_LABELS,
    STATUS_LABELS,
    TRANSFER_STAGES,
    days_left,
    is_overdue,
    letter_validity,
    load_rules,
    state_from_records,
    stage_label,
)

TODAY = date(2026, 10, 16)
# 契约里"介绍信不能未到先开"是按运行当天判断的，用例用相对日期，避免写死的日期过期
ISSUED = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def test_letter_validity_counts_days_from_issue_and_falls_back_on_bad_config():
    # 有效期按"开具日期 + 配置天数"，跨月跨年都要算对
    assert letter_validity(date(2026, 1, 1), 90) == date(2026, 4, 1)
    assert letter_validity(date(2026, 12, 31), 1) == date(2027, 1, 1)
    # 配置写坏了不能算出离谱的有效期：回落默认 90 天
    assert letter_validity(date(2026, 1, 1), 0) == date(2026, 4, 1)
    assert letter_validity(date(2026, 1, 1), -30) == date(2026, 4, 1)
    assert DEFAULT_LETTER_VALID_DAYS == 90


def test_overdue_only_applies_to_waiting_letters():
    # 到期当天还不算逾期：过期是"超过"有效期
    assert is_overdue("pending", TODAY, TODAY) is False
    assert is_overdue("pending", TODAY - timedelta(days=1), TODAY) is True
    assert days_left(TODAY - timedelta(days=1), TODAY) == -1
    assert days_left(TODAY + timedelta(days=80), TODAY) == 80
    # 已回执、已作废都不再提示逾期，否则"已办结"的事会一直挂着红了
    assert is_overdue("settled", TODAY - timedelta(days=100), TODAY) is False
    assert is_overdue("revoked", TODAY - timedelta(days=100), TODAY) is False


def test_state_derivation_is_ledger_order_and_ignores_revoked():
    assert state_from_records([]) == "in_place"
    assert state_from_records([("out", "pending")]) == "out_pending"
    assert state_from_records([("out", "settled")]) == "transferred_out"
    # 转入视为人在本组织：转出后又转回，不会被上一次转出粘住
    assert state_from_records([("out", "settled"), ("in", "pending")]) == "in_place"
    # 作废视同未发生，其余记录照常推导
    assert state_from_records([("out", "settled"), ("out", "revoked")]) == "transferred_out"
    assert state_from_records([("out", "revoked")]) == "in_place"
    # 作废的是另一次接转，不能顺手把还挂着的"待接收"也一起关掉
    assert state_from_records([("out", "pending"), ("out", "revoked")]) == "out_pending"
    assert state_from_records([("out", "revoked"), ("in", "settled")]) == "in_place"


def test_labels_and_stage_snapshot_are_readable():
    assert DIRECTION_LABELS == {"in": "转入", "out": "转出"}
    assert STATUS_LABELS["pending"] == "待接收"
    assert STATUS_LABELS["settled"] == "已接收"
    assert STATUS_LABELS["revoked"] == "已作废"
    assert STATE_LABELS["transferred_out"] == "已转出"
    assert stage_label("member") == STAGE_LABELS[MemberStage.MEMBER]
    assert stage_label("probationary") == STAGE_LABELS[MemberStage.PROBATIONARY]
    # 历史行里的阶段值可能已不在枚举内：读不出来留空，而不是抛错让整条台账打不开
    assert stage_label("legacy-stage") == ""
    assert stage_label(None) == ""


def test_rules_come_from_config_and_are_adjustable():
    rules = load_rules()
    assert rules["letter_valid_days"] == 90
    assert rules["remind_advance_days"] == 15


def test_transfer_applies_to_probationary_and_full_members_only():
    # "党员组织关系"是预备党员与正式党员的事；培养对象转的是培养材料，不是组织关系
    assert TRANSFER_STAGES == (MemberStage.PROBATIONARY.value, MemberStage.MEMBER.value)


def test_materials_for_stage_unions_existing_requirements_along_the_path():
    rules = load_stage_rules()
    # 与阶段流转同一来源：沿"入党申请人 → 当前阶段"逐步累加，不另维护一份转入清单
    path = [
        MemberStage.APPLICANT,
        MemberStage.ACTIVIST,
        MemberStage.CANDIDATE,
        MemberStage.PROBATIONARY,
        MemberStage.MEMBER,
    ]
    for index, stage in enumerate(path):
        expected: list[str] = []
        for step in range(index):
            rule = rules.get_rule(path[step], path[step + 1])
            assert rule is not None
            for name in rule.required_materials:
                if name not in expected:
                    expected.append(name)
        assert list(rules.materials_for_stage(stage)) == expected

    assert rules.materials_for_stage(MemberStage.APPLICANT) == ()
    assert len(rules.materials_for_stage(MemberStage.ACTIVIST)) == 2
    assert len(rules.materials_for_stage(MemberStage.PROBATIONARY)) == 10
    assert len(rules.materials_for_stage(MemberStage.MEMBER)) == 12
    # 预备党员转入时清单里不该出现尚未发生的转正材料
    probationary = rules.materials_for_stage(MemberStage.PROBATIONARY)
    assert "转正申请书" not in probationary
    assert "转正申请书" in rules.materials_for_stage(MemberStage.MEMBER)
    # 非发展阶段（退回）没有可沿用的清单，交由人工核对，不凭空生成要求
    assert rules.materials_for_stage(MemberStage.REJECTED) == ()


def test_outgoing_letter_contract_needs_the_member_and_the_letter_elements():
    created = TransferCreate(
        direction="out",
        profile_id="profile-1",
        counterpart_org="合成外校党委",
        letter_no="转字2026-001",
        issued_on=ISSUED,
        reason="办理转出",
    )
    assert created.valid_until is None  # 不填由配置推导，不在契约里硬编码天数
    # 转出必须指定名册中的党员
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=ISSUED,
            reason="办理转出",
        )
    # 转出沿用名册档案，不接受重复登记姓名 / 阶段
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            name="重名党员",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=ISSUED,
            reason="办理转出",
        )
    # 介绍信要素本身要成立
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=ISSUED,
            valid_until=(date.today() - timedelta(days=30)).isoformat(),
            reason="有效期早于开具日期",
        )
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=TOMORROW,
            reason="未到就开好了",
        )
    # 编号、对方组织与理由都是必填：缺了编号就追溯不到这封介绍信
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            counterpart_org="合成外校党委",
            issued_on=ISSUED,
            reason="办理转出",
        )
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=ISSUED,
        )
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="out",
            profile_id="profile-1",
            counterpart_org="合成外校党委",
            letter_no="转字2026-001",
            issued_on=ISSUED,
            reason="办理转出",
            contact_phone="13800000000",  # 第三人信息不采集，多余字段直接拒
        )


def test_incoming_letter_contract_links_or_creates_but_not_both():
    linked = TransferCreate(
        direction="in",
        profile_id="profile-2",
        org_unit_id="org-1",
        counterpart_org="合成外校党委",
        letter_no="转入字2026-001",
        issued_on=ISSUED,
        reason="接收转入",
    )
    created = TransferCreate(
        direction="in",
        name="合成转入党员",
        org_unit_id="org-1",
        current_stage="member",
        stage_joined_on="2020-07-01",
        counterpart_org="合成外校党委",
        letter_no="转入字2026-002",
        issued_on=ISSUED,
        reason="接收转入",
    )
    assert created.current_stage == "member"
    # 既关联档案又登记姓名会凭空多出一份同人档案
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="in",
            profile_id="profile-2",
            name="合成转入党员",
            org_unit_id="org-1",
            current_stage="member",
            stage_joined_on="2020-07-01",
            counterpart_org="合成外校党委",
            letter_no="转入字2026-003",
            issued_on=ISSUED,
            reason="既关联又新建",
        )
    # 新建档案三项必填（姓名 / 阶段 / 进入阶段日期）缺一不可
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="in",
            name="合成转入党员",
            org_unit_id="org-1",
            counterpart_org="合成外校党委",
            letter_no="转入字2026-004",
            issued_on=ISSUED,
            reason="缺阶段",
        )
    # 转入必须指明接收组织；接转只面对预备党员与正式党员
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="in",
            name="合成转入党员",
            current_stage="member",
            stage_joined_on="2020-07-01",
            counterpart_org="合成外校党委",
            letter_no="转入字2026-005",
            issued_on=ISSUED,
            reason="缺接收组织",
        )
    with pytest.raises(ValidationError):
        TransferCreate(
            direction="in",
            name="合成转入申请人",
            org_unit_id="org-1",
            current_stage="applicant",
            stage_joined_on="2020-07-01",
            counterpart_org="合成外校党委",
            letter_no="转入字2026-006",
            issued_on=ISSUED,
            reason="培养对象不是组织关系",
        )


def test_receipt_and_revoke_contracts_require_a_reason():
    assert TransferSettle(reason="收到回执").settled_on is None
    assert TransferSettle(reason="收到回执", settled_on=ISSUED).receipt_no == ""
    with pytest.raises(ValidationError):
        TransferSettle(reason="回执日期不能是未来", settled_on=TOMORROW)
    with pytest.raises(ValidationError):
        TransferSettle(reason="")
    with pytest.raises(ValidationError):
        TransferRevoke(reason="")
    assert TransferRevoke(reason="介绍信开错").reason == "介绍信开错"
