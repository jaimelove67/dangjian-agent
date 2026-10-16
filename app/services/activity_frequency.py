"""三会一课周期频次口径与合规提醒。

频次只在本模块一处维护：配置（``config/business_rules.yaml`` 的
``activity_requirements``）按**周期**表达（每月 / 每季度至少几次），年度要求由周期
派生——同一件事同时写成"每月 1 次"和"每年 12 次"两份，迟早会像修复前那样互相矛盾
（旧配置把支委会写成每季度 1 次、党课写成每年 1-2 次，都低于制度要求，支部书记照做
反而不合规）。

完成认定沿用组织生活既有口径：只认**已召开且人工审核通过**的记录，系统不自动认定
完成；"已召开但纪要没审"与"根本没开"是两件事，提醒必须区分，否则要么把人催到以为
系统坏了，要么把没开的记成开了。

依据：《中国共产党支部工作条例（试行）》——支部党员大会、党课一般每季度至少 1 次；
党支部委员会会议、党小组会一般每月 1 次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "business_rules.yaml"

PERIOD_MONTHS: dict[str, int] = {"year": 12, "quarter": 3, "month": 1, "none": 0}
PERIOD_TEXT: dict[str, str] = {
    "year": "每年至少 1 次",
    "quarter": "每季度至少 1 次",
    "month": "每月至少 1 次",
    "none": "不设固定频次",
}

FREQUENCY_NOTICE = "频次为制度提示，完成认定以人工审核通过的会议记录为准，系统不自动认定完成"
FREQUENCY_RULE = (
    "org-life-frequency-1：按《中国共产党支部工作条例（试行）》的周期口径"
    "（组织生活会每年至少 1 次；支部党员大会、党课每季度至少 1 次；"
    "党支部委员会会议、党小组会每月至少 1 次）；"
    "只统计已召开且人工审核通过的记录，跨周期不互相抵扣，已形成的周期缺口不因后续补开而消除"
)

# 本周期状态：已达标 / 已召开但纪要未过审 / 期内还差次数（本模块只描述事实，
# 是否算违规由人工判断）
MET = "met"
AWAITING_REVIEW = "awaiting_review"
OPEN = "open"


@dataclass(frozen=True)
class Requirement:
    """一类活动的周期频次要求；年度要求由周期派生，不另存一份。"""

    key: str
    label: str
    period: str
    per_period: int
    basis: str

    @property
    def annual_required(self) -> int:
        months = PERIOD_MONTHS.get(self.period, 0)
        return 0 if not months else self.per_period * (12 // months)

    @property
    def period_text(self) -> str:
        text = PERIOD_TEXT.get(self.period, PERIOD_TEXT["none"])
        if self.per_period == 1:
            return text
        return text.replace("1 次", f"{self.per_period} 次")


# 文件缺失或字段非法时逐项回落到这里的默认值；键必须覆盖 ACTIVITY_TYPES 的每一类。
DEFAULT_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "branch_member_meeting",
        "支部大会",
        "quarter",
        1,
        "支部党员大会一般每季度召开 1 次",
    ),
    Requirement(
        "branch_committee_meeting",
        "支委会",
        "month",
        1,
        "党支部委员会会议一般每月召开 1 次",
    ),
    Requirement(
        "party_group_meeting",
        "党小组会",
        "month",
        1,
        "党小组会一般每月召开 1 次（未划分党小组的支部不适用）",
    ),
    Requirement("party_lecture", "党课", "quarter", 1, "党支部一般每季度至少组织 1 次党课"),
    Requirement(
        "organizational_life_meeting",
        "组织生活会",
        "year",
        1,
        "党支部每年至少召开 1 次组织生活会，一般安排在第四季度",
    ),
    Requirement("other", "其他组织生活", "none", 0, "其他组织生活不设固定频次"),
)


@dataclass(frozen=True)
class RecordFact:
    """参与频次统计的一条会议记录的最小事实，便于脱离数据库单测。"""

    org_unit_id: str
    activity_type: str
    scheduled_on: date
    held_on: date | None
    review_status: str


def load_requirements() -> dict[str, Requirement]:
    """读取频次配置；文件缺失或字段非法时逐项回落到内置默认，不因配置损坏丢口径。"""
    try:
        data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    configured = data.get("activity_requirements") or {}
    result: dict[str, Requirement] = {}
    for default in DEFAULT_REQUIREMENTS:
        entry = configured.get(default.key) or {}
        period = str(entry.get("period", default.period))
        if period not in PERIOD_MONTHS:
            period = default.period
        try:
            per_period = int(entry.get("per_period", default.per_period))
        except (TypeError, ValueError):
            per_period = default.per_period
        if per_period < 0:
            per_period = default.per_period
        result[default.key] = Requirement(
            key=default.key,
            label=default.label,
            period=period,
            per_period=per_period,
            basis=str(entry.get("basis") or default.basis),
        )
    return result


def _month_end(month_start: date) -> date:
    """该月最后一天；避免手工维护每月天数。"""
    return (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def period_window(period: str, on: date) -> tuple[date, date] | None:
    """``on`` 所在周期的首末日（含）；不设周期返回 ``None``。"""
    if period == "year":
        return date(on.year, 1, 1), date(on.year, 12, 31)
    if period == "quarter":
        start = date(on.year, (on.month - 1) // 3 * 3 + 1, 1)
        return start, _month_end(date(start.year, start.month + 2, 1))
    if period == "month":
        start = on.replace(day=1)
        return start, _month_end(start)
    return None


def period_label(period: str, start: date) -> str:
    """周期的人读标签，接口与界面共用同一个说法。"""
    if period == "year":
        return f"{start.year} 年度"
    if period == "quarter":
        return f"{start.year} 年第 {(start.month - 1) // 3 + 1} 季度"
    if period == "month":
        return f"{start.year} 年 {start.month} 月"
    return f"{start.year} 年度"


def periods_in_year(period: str, year: int) -> list[tuple[date, date]]:
    """本年度内该周期的全部窗口，按时间正序。"""
    if period == "year":
        starts = [date(year, 1, 1)]
    elif period == "quarter":
        starts = [date(year, month, 1) for month in (1, 4, 7, 10)]
    elif period == "month":
        starts = [date(year, month, 1) for month in range(1, 13)]
    else:
        return []
    windows: list[tuple[date, date]] = []
    for start in starts:
        window = period_window(period, start)
        if window is not None:
            windows.append(window)
    return windows


def _tally(facts: Iterable[RecordFact], window: tuple[date, date]) -> tuple[int, int, int]:
    """窗口内按实际召开日期分类计数；未召开的按计划日期算"已安排"。"""
    approved = awaiting = scheduled = 0
    for fact in facts:
        if fact.held_on is not None:
            if not window[0] <= fact.held_on <= window[1]:
                continue
            if fact.review_status == "approved":
                approved += 1
            else:
                awaiting += 1
        elif window[0] <= fact.scheduled_on <= window[1]:
            scheduled += 1
    return approved, awaiting, scheduled


def _reminder_text(row: dict[str, Any]) -> str:
    """提醒话术只此一处；每条都给出下一步做什么，而不是只说"未达标"。"""
    label, when = row["activity_type_label"], row["period_label"]
    if row["state"] == MET:
        return (
            f"{when}{label}已通过人工审核 {row['performed']} 次，已达要求"
            f"（{row['period_text']}）"
        )
    if row["state"] == AWAITING_REVIEW:
        return (
            f"{when}{label}已召开 {row['awaiting_review']} 次，但纪要尚未通过人工审核；"
            "完成审核后即计入本周期，请先完成纪要审核（退回的需修订后重新提交）"
        )
    extra = f"，已安排待召开 {row['scheduled']} 次" if row["scheduled"] else ""
    return (
        f"{when}{label}还差 {row['missing']} 次，最晚 {row['period_end']} 前召开并完成纪要审核"
        f"（已通过 {row['performed']} 次{extra}）"
    )


def _branch_row(
    org_id: str,
    org_name: str,
    requirement: Requirement,
    facts: list[RecordFact],
    as_of: date,
) -> dict[str, Any]:
    """一个支部一类活动的本周期要求与实际；缺口只按"已过审"计算。"""
    window = period_window(requirement.period, as_of)
    if window is None:
        raise ValueError(f"活动类型 {requirement.key} 未配置周期，不应生成频次行")
    approved, awaiting, scheduled = _tally(facts, window)
    missing = max(0, requirement.per_period - approved)
    if missing == 0:
        state = MET
    elif approved + awaiting >= requirement.per_period:
        state = AWAITING_REVIEW
    else:
        state = OPEN
    row: dict[str, Any] = {
        "org_unit_id": org_id,
        "org_unit_name": org_name,
        "activity_type": requirement.key,
        "activity_type_label": requirement.label,
        "period": requirement.period,
        "period_label": period_label(requirement.period, window[0]),
        "period_start": window[0].isoformat(),
        "period_end": window[1].isoformat(),
        "required": requirement.per_period,
        "performed": approved,
        "awaiting_review": awaiting,
        "scheduled": scheduled,
        "missing": missing,
        "days_left": (window[1] - as_of).days,
        "annual_required": requirement.annual_required,
        "period_text": requirement.period_text,
        "basis": requirement.basis,
        "state": state,
    }
    row["reminder"] = _reminder_text(row)
    return row


def _branch_gap(
    org_id: str,
    org_name: str,
    requirement: Requirement,
    facts: list[RecordFact],
    as_of: date,
) -> dict[str, Any] | None:
    """本年度内**已结束**周期中未达标的汇总；当前周期另有提醒，不重复计入。

    逐周期一行会把"每个支部每个月"都铺成一条，迎检时反而看不出轻重；这里按
    支部 × 类型合成一条，列出具体是哪几个周期，并区分"没开"与"开了没审"。
    """
    missed: list[str] = []
    missing_total = awaiting_total = ended_total = 0
    for window in periods_in_year(requirement.period, as_of.year):
        if window[1] >= as_of:
            break
        ended_total += 1
        approved, awaiting, _ = _tally(facts, window)
        if approved >= requirement.per_period:
            continue
        missing_total += requirement.per_period - approved
        awaiting_total += awaiting
        missed.append(period_label(requirement.period, window[0]))
    if not missed:
        return None
    detail = f"、已召开待审核 {awaiting_total} 次" if awaiting_total else ""
    return {
        "org_unit_id": org_id,
        "org_unit_name": org_name,
        "activity_type": requirement.key,
        "activity_type_label": requirement.label,
        "period": requirement.period,
        "required": requirement.per_period,
        "missed_periods": missed,
        "missing_total": missing_total,
        "awaiting_total": awaiting_total,
        "text": (
            f"{org_name}{requirement.label}：本年度已结束 {ended_total} 个周期中 "
            f"{len(missed)} 个未达标（{'、'.join(missed)}），累计缺口 {missing_total} 次{detail}；"
            "跨周期不抵扣，不因后续补开而消除，请在台账中说明原因"
        ),
    }


def build_frequency(
    requirements: dict[str, Requirement],
    records: Iterable[RecordFact],
    branches: list[tuple[str, str]],
    as_of: date,
) -> dict[str, list[dict[str, Any]]]:
    """按支部逐类型算出本周期要求、完成情况、提醒与本年度缺口；纯计算，不访问数据库。

    ``branches`` 为有序的 ``(组织编号, 组织名称)``；只对配置了周期的活动类型生成行，
    其他组织生活不设固定频次、不产生提醒。
    """
    by_key: dict[tuple[str, str], list[RecordFact]] = {}
    for fact in records:
        by_key.setdefault((fact.org_unit_id, fact.activity_type), []).append(fact)

    rows: list[dict[str, Any]] = []
    reminders: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for org_id, org_name in branches:
        for requirement in requirements.values():
            if requirement.period == "none":
                continue
            facts = by_key.get((org_id, requirement.key), [])
            row = _branch_row(org_id, org_name, requirement, facts, as_of)
            rows.append(row)
            if row["state"] in (OPEN, AWAITING_REVIEW):
                reminders.append(row)
            gap = _branch_gap(org_id, org_name, requirement, facts, as_of)
            if gap is not None:
                gaps.append(gap)
    return {"rows": rows, "reminders": reminders, "gaps": gaps}
