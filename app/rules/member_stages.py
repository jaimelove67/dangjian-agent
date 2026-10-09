"""党员发展阶段规则（配置化）

对应框架文档 5.9.1 / 5.9.2：发展阶段、允许的流转、所需材料与最短时限。
规则全部可配置（默认从 ``config/business_rules.yaml`` 读取，缺失时回退内置默认）。

**决策边界（框架 5.9.3）**：本模块只描述"规则与建议"，不提供任何写入阶段的函数。
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# PyYAML 可选
yaml: Any = None
try:
    yaml = importlib.import_module("yaml")
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_CONFIG_PATH = "config/business_rules.yaml"


class MemberStage(str, Enum):
    """党员发展阶段"""
    APPLICANT = "applicant"          # 入党申请人
    ACTIVIST = "activist"            # 入党积极分子
    CANDIDATE = "candidate"          # 发展对象
    PROBATIONARY = "probationary"    # 预备党员
    MEMBER = "member"                # 正式党员
    REJECTED = "rejected"            # 退回


STAGE_LABELS: dict[MemberStage, str] = {
    MemberStage.APPLICANT: "入党申请人",
    MemberStage.ACTIVIST: "入党积极分子",
    MemberStage.CANDIDATE: "发展对象",
    MemberStage.PROBATIONARY: "预备党员",
    MemberStage.MEMBER: "正式党员",
    MemberStage.REJECTED: "退回",
}


@dataclass(frozen=True)
class TransitionRule:
    """一次流转的规则"""
    source: MemberStage
    target: MemberStage
    required_materials: tuple[str, ...] = ()
    min_days: int = 0
    procedures: tuple[str, ...] = ()   # 建议履行的程序（供流转建议使用）
    description: str = ""


# 内置默认规则（对应框架文档 5.9.2）
DEFAULT_TRANSITIONS: tuple[TransitionRule, ...] = (
    TransitionRule(
        MemberStage.APPLICANT, MemberStage.ACTIVIST,
        required_materials=("入党申请书", "党组织谈话记录"),
        procedures=("支委会研究确定",),
        description="入党申请人 → 入党积极分子",
    ),
    TransitionRule(
        MemberStage.ACTIVIST, MemberStage.CANDIDATE,
        required_materials=("思想汇报", "培养考察记录", "群众评议材料", "党课培训证明"),
        min_days=365,
        procedures=("培养期满且评议通过", "支委会研究确定"),
        description="入党积极分子 → 发展对象",
    ),
    TransitionRule(
        MemberStage.CANDIDATE, MemberStage.PROBATIONARY,
        required_materials=("政治审查材料", "公示情况报告", "支部大会决议", "上级审批意见"),
        min_days=90,
        procedures=("政治审查", "公示", "支部大会通过", "上级审批"),
        description="发展对象 → 预备党员",
    ),
    TransitionRule(
        MemberStage.PROBATIONARY, MemberStage.MEMBER,
        required_materials=("转正申请书", "预备期考察记录", "支部大会决议"),
        min_days=365,
        procedures=("预备期满", "支部大会通过", "上级审批"),
        description="预备党员 → 正式党员",
    ),
    TransitionRule(
        MemberStage.ACTIVIST, MemberStage.REJECTED,
        description="入党积极分子 → 退回（考察不合格）",
    ),
    TransitionRule(
        MemberStage.CANDIDATE, MemberStage.REJECTED,
        description="发展对象 → 退回（公示有异议）",
    ),
    TransitionRule(
        MemberStage.REJECTED, MemberStage.ACTIVIST,
        description="退回 → 入党积极分子",
    ),
)

# YAML 材料键 → (source, target)
_MATERIAL_KEYS: dict[str, tuple[MemberStage, MemberStage]] = {
    "applicant_to_activist": (MemberStage.APPLICANT, MemberStage.ACTIVIST),
    "activist_to_candidate": (MemberStage.ACTIVIST, MemberStage.CANDIDATE),
    "candidate_to_probationary": (MemberStage.CANDIDATE, MemberStage.PROBATIONARY),
    "probationary_to_member": (MemberStage.PROBATIONARY, MemberStage.MEMBER),
}

# YAML 时限键 → (source, target)
_MIN_DAYS_KEYS: dict[str, tuple[MemberStage, MemberStage]] = {
    "activist_training_min_days": (MemberStage.ACTIVIST, MemberStage.CANDIDATE),
    "candidate_training_days": (MemberStage.CANDIDATE, MemberStage.PROBATIONARY),
    "probationary_period_min_days": (MemberStage.PROBATIONARY, MemberStage.MEMBER),
}


@dataclass
class StageRules:
    """阶段规则集合"""
    transitions: tuple[TransitionRule, ...] = DEFAULT_TRANSITIONS
    reminder_advance_days: int = 30

    def get_rule(self, source: MemberStage, target: MemberStage) -> Optional[TransitionRule]:
        for rule in self.transitions:
            if rule.source == source and rule.target == target:
                return rule
        return None

    def next_targets(self, source: MemberStage) -> list[MemberStage]:
        return [rule.target for rule in self.transitions if rule.source == source]

    @classmethod
    def default(cls) -> "StageRules":
        return cls()


def _load_yaml(path: Path) -> Optional[dict]:
    if yaml is None or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except Exception as exc:  # pragma: no cover - 配置损坏时回退
        logger.warning("加载业务规则配置失败，回退默认：%s", exc)
        return None
    return data if isinstance(data, dict) else {}


def load_stage_rules(config_path: Optional[str] = None) -> StageRules:
    """加载阶段规则；从配置文件读取材料清单与时限，缺失时回退内置默认。"""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    data = _load_yaml(path)
    if not data:
        return StageRules.default()

    materials: dict[tuple[MemberStage, MemberStage], tuple[str, ...]] = {}
    for key, value in (data.get("material_requirements") or {}).items():
        mapping = _MATERIAL_KEYS.get(key)
        if mapping and isinstance(value, list):
            materials[mapping] = tuple(str(item) for item in value)

    min_days: dict[tuple[MemberStage, MemberStage], int] = {}
    development = data.get("member_development") or {}
    for key, mapping in _MIN_DAYS_KEYS.items():
        if key in development and isinstance(development[key], int):
            min_days[mapping] = int(development[key])

    transitions = []
    for rule in DEFAULT_TRANSITIONS:
        key = (rule.source, rule.target)
        transitions.append(
            TransitionRule(
                source=rule.source,
                target=rule.target,
                required_materials=materials.get(key, rule.required_materials),
                min_days=min_days.get(key, rule.min_days),
                procedures=rule.procedures,
                description=rule.description,
            )
        )

    advance = development.get("reminder_advance_days", 30)
    return StageRules(
        transitions=tuple(transitions),
        reminder_advance_days=int(advance) if isinstance(advance, int) else 30,
    )
