"""党员发展阶段规则与状态图纯逻辑测试（框架文档 5.9）"""
import pytest

from app.chains.member_flow import MemberFlow
from app.rules.member_stages import (
    MemberStage,
    StageRules,
    load_stage_rules,
)

_FULL_ACTIVIST_TO_CANDIDATE = [
    "思想汇报",
    "培养考察记录",
    "群众评议材料",
    "党课培训证明",
]


class TestRules:
    def test_default_core_transition(self):
        rule = StageRules.default().get_rule(MemberStage.ACTIVIST, MemberStage.CANDIDATE)
        assert rule is not None
        assert rule.min_days == 365
        assert "思想汇报" in rule.required_materials

    def test_load_from_config_yaml(self):
        rules = load_stage_rules()
        rule = rules.get_rule(MemberStage.CANDIDATE, MemberStage.PROBATIONARY)
        assert "政治审查材料" in rule.required_materials
        assert rule.min_days == 90  # candidate_training_days

    def test_next_targets_include_rejected(self):
        targets = StageRules.default().next_targets(MemberStage.ACTIVIST)
        assert MemberStage.CANDIDATE in targets
        assert MemberStage.REJECTED in targets


class TestQualification:
    def setup_method(self):
        self.flow = MemberFlow(StageRules.default())

    def test_eligible_when_materials_and_time_ok(self):
        outcome = self.flow.check_qualification(
            current_stage="activist",
            target_stage="candidate",
            materials=_FULL_ACTIVIST_TO_CANDIDATE,
            days_in_stage=400,
        )
        assert outcome.eligible is True
        assert outcome.blockers == []

    def test_missing_materials_block(self):
        outcome = self.flow.check_qualification(
            current_stage="activist",
            target_stage="candidate",
            materials=["思想汇报"],
            days_in_stage=400,
        )
        assert outcome.eligible is False
        assert any("材料不齐" in b for b in outcome.blockers)
        assert "培养考察记录" in outcome.missing_materials

    def test_min_days_block(self):
        outcome = self.flow.check_qualification(
            current_stage="activist",
            target_stage="candidate",
            materials=_FULL_ACTIVIST_TO_CANDIDATE,
            days_in_stage=100,
        )
        assert outcome.eligible is False
        assert any("最短时限" in b for b in outcome.blockers)

    def test_disallowed_transition(self):
        outcome = self.flow.check_qualification(
            current_stage="applicant", target_stage="member", days_in_stage=0
        )
        assert outcome.eligible is False
        assert any("不允许的流转" in b for b in outcome.blockers)


class TestSuggestionAndTodo:
    def setup_method(self):
        self.flow = MemberFlow(StageRules.default())

    def test_suggestion_eligible_with_procedures(self):
        outcome = self.flow.suggest_transition(
            current_stage="applicant",
            target_stage="activist",
            materials=["入党申请书", "党组织谈话记录"],
        )
        assert outcome.eligible is True
        assert outcome.suggested_target == "activist"
        assert outcome.procedures

    def test_suggestion_ineligible_has_no_target(self):
        outcome = self.flow.suggest_transition(
            current_stage="activist", target_stage="candidate", materials=[]
        )
        assert outcome.eligible is False
        assert outcome.suggested_target is None

    def test_todos_list_missing_materials(self):
        todos = self.flow.generate_todos(current_stage="applicant", materials=[])
        assert any(category == "material" for category, _ in todos)
        assert any("入党申请书" in content for _, content in todos)

    def test_todos_complete_suggest_meeting(self):
        todos = self.flow.generate_todos(
            current_stage="applicant", materials=["入党申请书", "党组织谈话记录"]
        )
        assert todos and todos[0][0] == "meeting"

    def test_flow_exposes_no_stage_write_method(self):
        """决策边界：状态图不提供写入阶段的接口"""
        flow = MemberFlow()
        public = [name for name in dir(flow) if not name.startswith("_")]
        assert not any("set_stage" in name or "update_stage" in name for name in public)
        assert not any("transition_to" in name or "write_stage" in name for name in public)
