"""党员发展状态图框架（LangGraph）

对应框架文档 5.9。状态图由三类节点组成，**不包含任何写入阶段的节点**：

- 资格校验：核对材料齐全性与时限，输出阻断项；
- 待办生成：生成"待补材料""建议安排会议"等行动建议；
- 流转建议：生成"拟转入什么阶段、需履行什么程序"的建议。

核心约束（框架 5.9.3）：状态图**不写入阶段字段**，人员阶段变更只能通过人工接口完成。
本模块的纯逻辑方法可独立单测；LangGraph 编排在 :func:`build_member_graph` 中惰性构建。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from app.rules.member_stages import (
    MemberStage,
    STAGE_LABELS,
    StageRules,
    load_stage_rules,
)
from app.schemas.member import DECISION_BOUNDARY_NOTE


@dataclass
class QualificationOutcome:
    """资格校验结果"""
    eligible: bool
    blockers: list[str] = field(default_factory=list)
    missing_materials: list[str] = field(default_factory=list)
    present_materials: list[str] = field(default_factory=list)
    min_days: int = 0
    days_in_stage: int = 0


@dataclass
class SuggestionOutcome:
    """流转建议（不含阶段写入）"""
    current_stage: str
    suggested_target: Optional[str]
    eligible: bool
    procedures: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


class MemberFlow:
    """党员发展状态图的纯逻辑实现"""

    def __init__(self, rules: Optional[StageRules] = None) -> None:
        self.rules = rules or load_stage_rules()

    @staticmethod
    def _coerce(stage: MemberStage | str) -> MemberStage:
        return stage if isinstance(stage, MemberStage) else MemberStage(stage)

    def check_qualification(
        self,
        *,
        current_stage: MemberStage | str,
        target_stage: MemberStage | str,
        materials: Optional[list[str]] = None,
        days_in_stage: int = 0,
    ) -> QualificationOutcome:
        """资格校验：材料齐全性 + 最短时限"""
        current = self._coerce(current_stage)
        target = self._coerce(target_stage)
        provided = set(materials or [])

        rule = self.rules.get_rule(current, target)
        if rule is None:
            label = f"{STAGE_LABELS.get(current, current)} → {STAGE_LABELS.get(target, target)}"
            return QualificationOutcome(
                eligible=False, blockers=[f"不允许的流转：{label}"], days_in_stage=days_in_stage
            )

        missing = [m for m in rule.required_materials if m not in provided]
        present = [m for m in rule.required_materials if m in provided]

        blockers: list[str] = []
        if missing:
            blockers.append("材料不齐：" + "、".join(missing))
        if days_in_stage < rule.min_days:
            blockers.append(
                f"未满足最短时限：需 {rule.min_days} 天，当前 {days_in_stage} 天"
            )

        return QualificationOutcome(
            eligible=not blockers,
            blockers=blockers,
            missing_materials=missing,
            present_materials=present,
            min_days=rule.min_days,
            days_in_stage=days_in_stage,
        )

    def suggest_transition(
        self,
        *,
        current_stage: MemberStage | str,
        target_stage: MemberStage | str,
        materials: Optional[list[str]] = None,
        days_in_stage: int = 0,
    ) -> SuggestionOutcome:
        """流转建议：给出拟转入阶段与应履行程序（**不写入阶段**）"""
        current = self._coerce(current_stage)
        target = self._coerce(target_stage)
        outcome = self.check_qualification(
            current_stage=current,
            target_stage=target,
            materials=materials,
            days_in_stage=days_in_stage,
        )
        rule = self.rules.get_rule(current, target)
        return SuggestionOutcome(
            current_stage=current.value,
            suggested_target=target.value if outcome.eligible else None,
            eligible=outcome.eligible,
            procedures=list(rule.procedures) if rule else [],
            blockers=outcome.blockers,
        )

    def generate_todos(
        self,
        *,
        current_stage: MemberStage | str,
        materials: Optional[list[str]] = None,
        days_in_stage: int = 0,
    ) -> list[tuple[str, str]]:
        """待办生成：返回 (类别, 内容) 列表；类别 material/meeting/reminder"""
        current = self._coerce(current_stage)
        provided = set(materials or [])
        todos: list[tuple[str, str]] = []

        for rule in self.rules.transitions:
            if rule.source != current or rule.target == MemberStage.REJECTED:
                continue
            for material in rule.required_materials:
                if material not in provided:
                    todos.append(
                        (
                            "material",
                            f"待补材料：{material}（用于 "
                            f"{STAGE_LABELS[current]} → {STAGE_LABELS[rule.target]}）",
                        )
                    )

        if not todos:
            todos.append(("meeting", "材料齐备，建议按程序安排支委会/支部大会研究"))

        return todos


# LangGraph 状态定义
class MemberFlowState(TypedDict, total=False):
    current_stage: str
    target_stage: str
    materials: list[str]
    days_in_stage: int
    eligible: bool
    blockers: list[str]
    missing_materials: list[str]
    present_materials: list[str]
    min_days: int
    todos: list[dict[str, str]]
    suggested_target: Optional[str]
    procedures: list[str]
    note: str


def build_member_graph(flow: Optional[MemberFlow] = None) -> Any:
    """构建 LangGraph 状态图（编译后的图）

    图为"校验 → 待办 → 建议"的只读流水线，节点均不修改人员阶段。
    """
    from langgraph.graph import END, START, StateGraph

    flow = flow or MemberFlow()

    def check_node(state: MemberFlowState) -> dict[str, Any]:
        outcome = flow.check_qualification(
            current_stage=state["current_stage"],
            target_stage=state["target_stage"],
            materials=state.get("materials", []),
            days_in_stage=state.get("days_in_stage", 0),
        )
        return {
            "eligible": outcome.eligible,
            "blockers": outcome.blockers,
            "missing_materials": outcome.missing_materials,
            "present_materials": outcome.present_materials,
            "min_days": outcome.min_days,
        }

    def todo_node(state: MemberFlowState) -> dict[str, Any]:
        todos = flow.generate_todos(
            current_stage=state["current_stage"],
            materials=state.get("materials", []),
            days_in_stage=state.get("days_in_stage", 0),
        )
        return {"todos": [{"category": c, "content": t} for c, t in todos]}

    def suggest_node(state: MemberFlowState) -> dict[str, Any]:
        outcome = flow.suggest_transition(
            current_stage=state["current_stage"],
            target_stage=state["target_stage"],
            materials=state.get("materials", []),
            days_in_stage=state.get("days_in_stage", 0),
        )
        return {
            "suggested_target": outcome.suggested_target,
            "procedures": outcome.procedures,
            "note": DECISION_BOUNDARY_NOTE,
        }

    graph = StateGraph(MemberFlowState)
    graph.add_node("check_qualification", check_node)
    graph.add_node("generate_todos", todo_node)
    graph.add_node("suggest_transition", suggest_node)
    graph.add_edge(START, "check_qualification")
    graph.add_edge("check_qualification", "generate_todos")
    graph.add_edge("generate_todos", "suggest_transition")
    graph.add_edge("suggest_transition", END)
    return graph.compile()
