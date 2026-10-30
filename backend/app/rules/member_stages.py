"""党员发展阶段规则（配置化）

对应框架文档 5.9.1 / 5.9.2：发展阶段、允许的流转、所需材料与最短时限。
规则全部可配置（默认从 ``config/business_rules.yaml`` 读取，缺失时回退内置默认）。

**决策边界（框架 5.9.3）**：本模块只描述"规则与建议"，不提供任何写入阶段的函数。
"""

from __future__ import annotations

import calendar
import importlib
import logging
from dataclasses import dataclass
from datetime import date, timedelta
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

    APPLICANT = "applicant"  # 入党申请人
    ACTIVIST = "activist"  # 入党积极分子
    CANDIDATE = "candidate"  # 发展对象
    PROBATIONARY = "probationary"  # 预备党员
    MEMBER = "member"  # 正式党员
    REJECTED = "rejected"  # 退回


STAGE_LABELS: dict[MemberStage, str] = {
    MemberStage.APPLICANT: "入党申请人",
    MemberStage.ACTIVIST: "入党积极分子",
    MemberStage.CANDIDATE: "发展对象",
    MemberStage.PROBATIONARY: "预备党员",
    MemberStage.MEMBER: "正式党员",
    MemberStage.REJECTED: "退回",
}


#: 接收预备党员前的硬前置：政审须有明确结论，集中培训不少于 3 天或 24 学时。
#: 这两个阈值只描述"事实是否具备"，不替组织判断政审是否合格、培训是否有效。
MIN_POLITICAL_REVIEW_STATUS = "passed"
MIN_TRAINING_DAYS = 3
MIN_TRAINING_HOURS = 24


def add_months(value: date, months: int) -> date:
    """按自然月计算到期日；月末按目标月份最后一天处理（1月31日 + 1个月 = 2月28/29日）。"""
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def political_review_blocker(status: str | None) -> str | None:
    """政审结论是否满足接收预备党员的前置条件；只返回阻断说明，不替组织下结论。"""
    if status is None:
        return "政治审查结论未登记：请先登记组织形成的政审结论"
    if status == "in_progress":
        return "政治审查尚未形成结论：请待组织完成审查并登记结论"
    if status == "failed":
        return "政治审查结论为不合格：不能办理接收预备党员，请按组织程序处理"
    if status != MIN_POLITICAL_REVIEW_STATUS:
        return "政治审查结论状态无效：请核对档案"
    return None


def training_blocker(days: int | None, hours: int | None) -> str | None:
    """集中培训是否达到 3 天或 24 学时；两个口径满足其一即可。"""
    attended_days = max(0, int(days or 0))
    attended_hours = max(0, int(hours or 0))
    if attended_days >= MIN_TRAINING_DAYS or attended_hours >= MIN_TRAINING_HOURS:
        return None
    if attended_days or attended_hours:
        return (
            f"集中培训未达 {MIN_TRAINING_DAYS} 天或 {MIN_TRAINING_HOURS} 学时："
            f"已登记 {attended_days} 天 / {attended_hours} 学时"
        )
    return f"集中培训未登记：须参加不少于 {MIN_TRAINING_DAYS} 天或 {MIN_TRAINING_HOURS} 学时的集中培训"


@dataclass(frozen=True)
class TransitionRule:
    """一次流转的规则"""

    source: MemberStage
    target: MemberStage
    required_materials: tuple[str, ...] = ()
    min_days: int = 0
    #: 自然月时限；与 min_days 同时存在时取较晚的日期。用于"申请满 6 个月"这类按月计算的规则。
    min_months: int = 0
    procedures: tuple[str, ...] = ()  # 建议履行的程序（供流转建议使用）
    description: str = ""


# 内置默认规则（对应框架文档 5.9.2）
DEFAULT_TRANSITIONS: tuple[TransitionRule, ...] = (
    TransitionRule(
        MemberStage.APPLICANT,
        MemberStage.ACTIVIST,
        required_materials=("入党申请书", "党组织谈话记录"),
        # 细则要求"递交入党申请书满 6 个月"才能确定为入党积极分子；锚点是申请书落款日期，
        # 不是建档日期。服务层会用最早一份已核验申请书的落款日期核算。
        min_months=6,
        procedures=("支委会研究确定",),
        description="入党申请人 → 入党积极分子",
    ),
    TransitionRule(
        MemberStage.ACTIVIST,
        MemberStage.CANDIDATE,
        required_materials=("思想汇报", "培养考察记录", "群众评议材料", "党课培训证明"),
        min_days=365,
        procedures=("培养联系人", "培养期满且评议通过", "支委会研究确定"),
        description="入党积极分子 → 发展对象",
    ),
    TransitionRule(
        MemberStage.CANDIDATE,
        MemberStage.PROBATIONARY,
        # "上级审批意见"是批复回填后的材料，不应作为支部大会前流转的前置，否则会与
        # "上级审批报送要求人员已是预备党员"形成循环。上级审批仍由报送台账单独登记。
        required_materials=("政治审查材料", "公示情况报告", "支部大会决议"),
        # 细则没有"发展对象满 90 天"的固定间隔；原 90 天是配置误读，已移除。
        # 政审结论与集中培训由服务层按事实台账单独校验。
        procedures=(
            "入党介绍人",
            "政治审查",
            "集中培训",
            "支委会审查",
            "上级党委预审",
            "填写入党志愿书",
            "公示",
            "支部大会通过",
            "上级审批",
        ),
        description="发展对象 → 预备党员",
    ),
    TransitionRule(
        MemberStage.PROBATIONARY,
        MemberStage.MEMBER,
        required_materials=("转正申请书", "预备期考察记录", "支部大会决议"),
        min_days=365,
        procedures=("预备期满", "支部大会通过", "上级审批"),
        description="预备党员 → 正式党员",
    ),
    TransitionRule(
        MemberStage.ACTIVIST,
        MemberStage.REJECTED,
        description="入党积极分子 → 退回（考察不合格）",
    ),
    TransitionRule(
        MemberStage.CANDIDATE,
        MemberStage.REJECTED,
        description="发展对象 → 退回（公示有异议）",
    ),
    TransitionRule(
        MemberStage.REJECTED,
        MemberStage.ACTIVIST,
        description="退回 → 入党积极分子",
    ),
)

# 发展阶段链：转入档案清单沿这条链累加既有材料要求（T-MEM-14）。
_DEVELOPMENT_PATH: tuple[MemberStage, ...] = (
    MemberStage.APPLICANT,
    MemberStage.ACTIVIST,
    MemberStage.CANDIDATE,
    MemberStage.PROBATIONARY,
    MemberStage.MEMBER,
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
    "probationary_period_min_days": (MemberStage.PROBATIONARY, MemberStage.MEMBER),
}

# YAML 自然月时限键 → (source, target)
_MIN_MONTHS_KEYS: dict[str, tuple[MemberStage, MemberStage]] = {
    "applicant_to_activist_min_months": (MemberStage.APPLICANT, MemberStage.ACTIVIST),
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

    def development_rank(self, stage: MemberStage) -> int | None:
        """发展阶段链上的序号（入党申请人 0 → 正式党员 4）；非发展阶段返回 None。

        接续发展顺序是判断"能不能办某一环节"的共同依据：档案清单要沿链累加
        （`materials_for_stage`），上级备案 / 审批要在阶段已到（或已过）目标阶段后才受理
        （T-MEM-11），两处都不能各写一套顺序。
        """
        if stage not in _DEVELOPMENT_PATH:
            return None
        return _DEVELOPMENT_PATH.index(stage)

    def materials_for_stage(self, stage: MemberStage) -> tuple[str, ...]:
        """转入档案清单：沿"入党申请人 → 当前阶段"累加既有材料要求。

        组织关系转入时要核对本人档案（T-MEM-14），清单口径与阶段流转**同一来源**——
        不另写一份"转入档案清单"，否则两处清单必然漂移（哪套算数就说不清了）。
        预备党员按到"预备党员"为止累加，不把尚未发生的转正材料算成缺项：转入时还没
        转正，清单要跟着人的实际阶段走。非发展阶段（如"退回"）返回空清单。
        """
        stop = self.development_rank(stage)
        if stop is None:
            return ()
        names: list[str] = []
        for index in range(stop):
            rule = self.get_rule(_DEVELOPMENT_PATH[index], _DEVELOPMENT_PATH[index + 1])
            if rule is None:
                continue
            for name in rule.required_materials:
                if name not in names:
                    names.append(name)
        return tuple(names)

    def earliest_transition_date(self, anchor: date, rule: TransitionRule) -> date:
        """按规则计算最早可办理日期；天数和自然月同时存在时取较晚者。"""
        earliest = anchor + timedelta(days=max(0, rule.min_days))
        if rule.min_months > 0:
            earliest = max(earliest, add_months(anchor, rule.min_months))
        return earliest

    @staticmethod
    def min_period_label(rule: TransitionRule) -> str:
        """给人工提示用的时限文字，不把天数与月数混成一个模糊说法。"""
        parts = []
        if rule.min_months > 0:
            parts.append(f"{rule.min_months} 个月")
        if rule.min_days > 0:
            parts.append(f"{rule.min_days} 天")
        return "、".join(parts) or "无固定间隔"

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
    min_months: dict[tuple[MemberStage, MemberStage], int] = {}
    development = data.get("member_development") or {}
    for key, mapping in _MIN_DAYS_KEYS.items():
        if key in development and isinstance(development[key], int):
            min_days[mapping] = int(development[key])
    for key, mapping in _MIN_MONTHS_KEYS.items():
        if key in development and isinstance(development[key], int):
            min_months[mapping] = int(development[key])

    transitions = []
    for rule in DEFAULT_TRANSITIONS:
        key = (rule.source, rule.target)
        transitions.append(
            TransitionRule(
                source=rule.source,
                target=rule.target,
                required_materials=materials.get(key, rule.required_materials),
                min_days=min_days.get(key, rule.min_days),
                min_months=min_months.get(key, rule.min_months),
                procedures=rule.procedures,
                description=rule.description,
            )
        )

    advance = development.get("reminder_advance_days", 30)
    return StageRules(
        transitions=tuple(transitions),
        reminder_advance_days=int(advance) if isinstance(advance, int) else 30,
    )
