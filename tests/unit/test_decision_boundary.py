"""决策边界标注（T-SEC-13）：文案只有一处来源，各出口必须派生自它。

“强制标注”要能被机器检查：这里锁住常量本身的必需语义，并核对各模块导出的
标注确实是同一处来源，避免新增接口时各写一套话术或干脆漏标。
"""

from app.core.decision_boundary import (
    ASSISTED_REFERENCE_NOTE,
    ASSISTED_REFERENCE_PREFIX,
    QA_DISCLAIMER,
    STAGE_TRANSITION_NOTE,
    evidence_note,
    pending_review_message,
)
from app.schemas.member import DECISION_BOUNDARY_NOTE
from app.schemas.qa import DEFAULT_DISCLAIMER
from app.services.member_service import DECISION_BOUNDARY


class TestSharedWording:
    def test_every_export_derives_from_the_same_prefix(self):
        # 成员建议 / 阶段流转补充 / 问答标注都必须以同一句开头，不允许模块自拟口径
        for text in (ASSISTED_REFERENCE_NOTE, QA_DISCLAIMER, STAGE_TRANSITION_NOTE):
            assert text.startswith(ASSISTED_REFERENCE_PREFIX)
        assert STAGE_TRANSITION_NOTE.startswith(ASSISTED_REFERENCE_NOTE)
        assert DECISION_BOUNDARY_NOTE == STAGE_TRANSITION_NOTE
        assert DECISION_BOUNDARY == STAGE_TRANSITION_NOTE
        assert DEFAULT_DISCLAIMER == QA_DISCLAIMER

    def test_label_carries_the_required_phrases(self):
        # SEC-10 / FR-MEM-10 的最小可用标注
        assert "辅助参考" in ASSISTED_REFERENCE_NOTE
        assert "人工终审" in ASSISTED_REFERENCE_NOTE
        assert "组织认定" in ASSISTED_REFERENCE_NOTE
        # FR-QA-11：以正式文件为准
        assert "正式文件" in QA_DISCLAIMER

    def test_stage_transition_supplement_names_the_human_path(self):
        assert "人工接口" in STAGE_TRANSITION_NOTE
        assert "依规操作" in STAGE_TRANSITION_NOTE

    def test_evidence_note_points_at_a_checkable_location(self):
        note = evidence_note("各维度 evidence 字段")
        assert "各维度 evidence 字段" in note
        assert "逐条溯源" in note
        assert "不以模型自动结论替代组织决定" in note

    def test_pending_review_message_is_actionable(self):
        message = pending_review_message("考核归集", "待人工审核", "请在考核工作台完成审核")
        assert "考核归集" in message
        assert "待人工审核" in message
        assert "不得流转" in message
        assert "请在考核工作台完成审核" in message
