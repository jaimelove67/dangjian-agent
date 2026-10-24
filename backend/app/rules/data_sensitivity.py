"""字段级敏感分级与第三人信息脱敏（T-MEM-12）

对应 SEC-01（人员档案 / 政治表现 / 投票 / 评议分类分级）与 SEC-04（敏感内容不出网）。
本模块是"党员材料 / 民主评议 / 选优投票 / 选优结论与团组织推优"密级的**唯一来源**，供下列出口消费：

- 读取出口：密级高于查看者等级时，第三人字段不返回正文（``redact_third_party``）；
- 批量导出：第三人字段一律不写出（``strip_third_party_fields``）；
- 模型与知识库边界：``cloud_allowed`` / ``embedding_allowed`` 供上层判断，依据与
  ``app/rag/privacy.py``、``app/rules/document_metadata.py`` 保持一致口径。

**不假装做到的事**：系统读不懂自由文本里有没有提到别人，分级只依据材料类型 /
记录类型与登记口径，不做内容识别。要收紧只能把对应类型的密级调高（例如学校认定
政治审查材料属涉密时，把 ``member_material_levels`` 里它改成 ``classified``，
第三人字段正文就对**全部角色**都不再返回，只留元数据）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

try:  # PyYAML 可选：缺失时回退内置默认
    import importlib

    yaml: Any = importlib.import_module("yaml")
except Exception:  # pragma: no cover - 环境未装 PyYAML
    yaml = None

from app.core.constants import DataLevel
from app.core.security import resolve_data_level

DEFAULT_CONFIG_PATH = "config/business_rules.yaml"

LEVEL_ORDER: tuple[DataLevel, ...] = (
    DataLevel.PUBLIC,
    DataLevel.INTERNAL,
    DataLevel.SENSITIVE,
    DataLevel.CLASSIFIED,
)

LEVEL_LABELS: dict[DataLevel, str] = {
    DataLevel.PUBLIC: "公开",
    DataLevel.INTERNAL: "内部",
    DataLevel.SENSITIVE: "敏感",
    DataLevel.CLASSIFIED: "涉密",
}

DEFAULT_MATERIAL_LEVEL = DataLevel.INTERNAL
DEFAULT_REVIEW_LEVEL = DataLevel.SENSITIVE
DEFAULT_VOTE_LEVEL = DataLevel.SENSITIVE
# 选优结论与团组织推优台账：含"组织对某人的评价、推优说明"，按敏感级处理。
DEFAULT_SELECTION_LEVEL = DataLevel.SENSITIVE

# 含第三人信息（他人对某人的评价、给某人的备注与说明）的字段名。
# 读取出口按密级收敛，批量导出与模型调用一律不含。
THIRD_PARTY_FIELDS: frozenset[str] = frozenset({"note", "description", "comment", "peer_review"})

# 第三人**身份**字段：这类字段不该被采集（采集了就等于把别人写进台账）。
# 入口不采集是约定，这里列出名字供测试守住，防止"顺手加一个联系人电话"。
# 只列有明确边界出处的名字：投票人身份（选优投票汇总）、上级组织 / 接收单位联系人与电话
# （`T-MEM-11` / `T-MEM-14` 都明确不采集）。
IDENTITY_FIELDS: frozenset[str] = frozenset({"voter_id", "contact_name", "contact_phone"})

REDACTED_NOTE = "（含第三人信息，已按数据等级脱敏；正文请查有权范围内的原件）"
CLASSIFIED_NOTE = "（涉密材料正文不在界面展示，请查党组织线下原件）"
REDACTION_PLACEHOLDERS: frozenset[str] = frozenset({REDACTED_NOTE, CLASSIFIED_NOTE})

_DEFAULTS: dict[str, str] = {
    # 配置缺失时的兜底：与 config/business_rules.yaml 的出厂默认一致（不是放宽）。
    "政治审查材料": DataLevel.CLASSIFIED.value,
    "群众评议材料": DataLevel.SENSITIVE.value,
}

_DEFAULT_ALIASES: dict[str, str] = {
    "政审材料": "政治审查材料",
    "政治审查": "政治审查材料",
    "群众评议": "群众评议材料",
}


@dataclass(frozen=True)
class SensitivityRules:
    """材料 / 评议 / 投票的默认密级与简称归一。"""

    material_levels: Mapping[str, DataLevel] = field(default_factory=dict)
    aliases: Mapping[str, str] = field(default_factory=dict)
    default_material_level: DataLevel = DEFAULT_MATERIAL_LEVEL
    review_level: DataLevel = DEFAULT_REVIEW_LEVEL
    vote_level: DataLevel = DEFAULT_VOTE_LEVEL
    selection_level: DataLevel = DEFAULT_SELECTION_LEVEL

    def material_level(self, material_type: Any) -> DataLevel:
        """按材料类型给出密级；未登记的类型按内部处理（不猜内容）。"""
        name = normalize_material_name(material_type)
        if not name:
            return self.default_material_level
        return self.material_levels.get(name, self.default_material_level)


def normalize_material_name(material_type: Any) -> str:
    """材料类型归一化：去首尾空白。简称归一需要规则表，见 ``SensitivityRules.aliases``。"""
    if material_type is None:
        return ""
    return str(material_type).strip()


def _as_level(value: Any, fallback: DataLevel) -> DataLevel:
    if isinstance(value, DataLevel):
        return value
    try:
        return DataLevel(str(value).strip().lower())
    except ValueError:
        return fallback


def load_rules(config_path: Optional[str] = None) -> SensitivityRules:
    """从业务规则配置读取密级；缺失或损坏时回退内置默认。"""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    entry: Mapping[str, Any] = {}
    if yaml is not None and path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # pragma: no cover - 配置损坏时回退默认
            data = {}
        section = data.get("data_sensitivity") if isinstance(data, dict) else None
        if isinstance(section, Mapping):
            entry = section

    default_level = _as_level(
        entry.get("default_material_level", DEFAULT_MATERIAL_LEVEL.value), DEFAULT_MATERIAL_LEVEL
    )
    levels: dict[str, DataLevel] = {}
    raw_levels = entry.get("member_material_levels")
    if isinstance(raw_levels, Mapping):
        for name, value in raw_levels.items():
            levels[normalize_material_name(name)] = _as_level(value, default_level)
    if not levels:
        levels = {
            normalize_material_name(name): _as_level(value, default_level)
            for name, value in _DEFAULTS.items()
        }

    aliases: dict[str, str] = {}
    raw_aliases = entry.get("material_aliases")
    if isinstance(raw_aliases, Mapping):
        for short, full in raw_aliases.items():
            aliases[normalize_material_name(short)] = normalize_material_name(full)
    if not aliases:
        aliases = dict(_DEFAULT_ALIASES)

    return SensitivityRules(
        material_levels=levels,
        aliases=aliases,
        default_material_level=default_level,
        review_level=_as_level(
            entry.get("member_review_level", DEFAULT_REVIEW_LEVEL.value), DEFAULT_REVIEW_LEVEL
        ),
        vote_level=_as_level(
            entry.get("member_vote_level", DEFAULT_VOTE_LEVEL.value), DEFAULT_VOTE_LEVEL
        ),
        selection_level=_as_level(
            entry.get("member_selection_level", DEFAULT_SELECTION_LEVEL.value),
            DEFAULT_SELECTION_LEVEL,
        ),
    )


def material_level(material_type: Any, *, rules: Optional[SensitivityRules] = None) -> DataLevel:
    """材料类型 → 密级（先按简称归一，避免用简称绕过等级）。"""
    cfg = rules or load_rules()
    name = normalize_material_name(material_type)
    name = cfg.aliases.get(name, name)
    return cfg.material_levels.get(name, cfg.default_material_level)


def review_level(*, rules: Optional[SensitivityRules] = None) -> DataLevel:
    return (rules or load_rules()).review_level


def vote_level(*, rules: Optional[SensitivityRules] = None) -> DataLevel:
    return (rules or load_rules()).vote_level


def selection_level(*, rules: Optional[SensitivityRules] = None) -> DataLevel:
    """选优结论与团组织推优台账的密级（同一套"组织评价"口径）。"""
    return (rules or load_rules()).selection_level


def level_rank(level: DataLevel | str | None) -> int:
    """密级高低比较用序号；未知取值按下限（公开）处理，不抬高也不放过。"""
    return LEVEL_ORDER.index(_as_level(level, DataLevel.PUBLIC))


def level_at_least(viewer: DataLevel | str | None, required: DataLevel | str | None) -> bool:
    return level_rank(viewer) >= level_rank(required)


def level_label(level: DataLevel | str | None) -> str:
    return LEVEL_LABELS.get(_as_level(level, DataLevel.PUBLIC), "")


def cloud_allowed(level: DataLevel | str | None) -> bool:
    """是否允许交给校外（云端）模型：敏感与涉密都不出网。"""
    return level_rank(level) < level_rank(DataLevel.SENSITIVE)


def embedding_allowed(level: DataLevel | str | None) -> bool:
    """是否允许向量化：涉密材料不入向量库（与 ``document_metadata`` 同口径）。"""
    return _as_level(level, DataLevel.PUBLIC) is not DataLevel.CLASSIFIED


def annotate_level(level: DataLevel | str | None) -> dict[str, Any]:
    """把一条记录 / 一份内容的密级写进响应，供界面与下游出口判断。"""
    resolved = _as_level(level, DataLevel.INTERNAL)
    return {
        "data_level": resolved.value,
        "data_level_label": level_label(resolved),
        "cloud_allowed": cloud_allowed(resolved),
        "embedding_allowed": embedding_allowed(resolved),
    }


def viewer_level(user: Any) -> DataLevel:
    """查看者等级：由登录角色推导，不接受客户端传入。"""
    role = getattr(user, "role", None)
    if role is None:
        return DataLevel.PUBLIC
    return resolve_data_level(role)


def _placeholder(level: DataLevel) -> str:
    return CLASSIFIED_NOTE if level is DataLevel.CLASSIFIED else REDACTED_NOTE


def redact_third_party(
    payload: Mapping[str, Any], *, level: DataLevel | str | None, viewer: DataLevel | str | None
) -> tuple[dict[str, Any], list[str]]:
    """按等级脱敏第三人字段。

    ``level`` 为内容密级、``viewer`` 为查看者等级；密级不高于查看者时原样返回。
    第三人字段在**任何一层**都算第三人字段：民主评议的党员互评在 ``procedure`` 里、
    材料留痕在 ``review_history`` 的每条快照里，都不会漏。
    """
    content = _as_level(level, DataLevel.INTERNAL)
    if level_rank(content) <= level_rank(viewer):
        return dict(payload), []
    note = _placeholder(content)
    redacted: list[str] = []

    def _walk(data: Mapping[str, Any], prefix: str) -> dict[str, Any]:
        out = dict(data)
        for key in sorted(THIRD_PARTY_FIELDS):
            if key in out and str(out.get(key) or "").strip():
                out[key] = note
                redacted.append(f"{prefix}{key}")
        for key, value in list(out.items()):
            if isinstance(value, Mapping):
                out[key] = _walk(value, f"{prefix}{key}.")
            elif isinstance(value, list):
                out[key] = [
                    _walk(item, f"{prefix}{key}.") if isinstance(item, Mapping) else item
                    for item in value
                ]
        return out

    return _walk(payload, ""), redacted


def strip_third_party_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """批量导出口径：第三人字段一律不写出（不是脱敏，是根本不落进表格）。

    与 ``redact_third_party`` 同一口径：第三人字段在**任何一层**都不写出，导出件里
    既没有正文也没有占位（占位本身也在告诉读者"这里本来有内容"）。台账要素不受影响
    （例如上级批复说明 ``decide_note`` 不在禁列内）。
    """

    def _walk(data: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key in THIRD_PARTY_FIELDS:
                continue
            if isinstance(value, Mapping):
                out[key] = _walk(value)
            elif isinstance(value, list):
                out[key] = [_walk(item) if isinstance(item, Mapping) else item for item in value]
            else:
                out[key] = value
        return out

    return _walk(payload)


def is_redaction_placeholder(value: Any) -> bool:
    """是否为读取出口写出的脱敏占位文本。

    占位文本不是内容：客户端把详情面板里看到的占位原样提交回来时，不能把它当正文
    写回库（否则一次"我只是打开又保存"就会把党员互评等正文覆盖成占位）。
    """
    return str(value or "").strip() in REDACTION_PLACEHOLDERS
