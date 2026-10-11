"""考核纯计算：稳定来源去重、明确期间、零分母与缺项，禁止模型下结论。"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

ENGINE_VERSION = "assessment-1"


def fingerprint(value: Any) -> str:
    """对排序后的规范 JSON 求摘要，供版本、重算与导出核对。"""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceRecord:
    """上游模块只读契约；id 是业务稳定编号，version 随记录修订变化。"""

    id: str
    tenant_id: str
    org_unit_id: str
    occurred_on: date
    version: str
    status: str = "approved"
    participants: tuple[str, ...] = ()
    expected_participants: tuple[str, ...] = ()
    material_complete: bool | None = None
    value: str | None = None
    facts: tuple[tuple[str, str], ...] = ()

    def reference(self, source: str) -> dict[str, Any]:
        """来源定位不包含人员材料原文、磁盘路径或认证信息。"""
        return {
            "source": source,
            "record_id": self.id,
            "version": self.version,
            "org_unit_id": self.org_unit_id,
            "occurred_on": self.occurred_on.isoformat(),
            "facts": dict(self.facts),
        }


@dataclass(frozen=True)
class SourceBatch:
    """只有 complete=True 的空集合才表示确知为零，未接入不得表示零。"""

    records: tuple[SourceRecord, ...] = ()
    complete: bool = False
    missing: tuple[str, ...] = ()


def scoped_records(
    batch: SourceBatch, *, tenant_id: str, org_ids: set[str], start: date, end: date
) -> tuple[list[SourceRecord], list[str]]:
    """按期间、租户与组织再次限制适配器输出，重复和冲突版本不重复计数。"""
    records: dict[str, SourceRecord] = {}
    conflicted: set[str] = set()
    missing = list(batch.missing)
    for record in batch.records:
        if record.id in conflicted:
            continue
        if record.tenant_id != tenant_id or record.org_unit_id not in org_ids:
            continue
        if not start <= record.occurred_on <= end or record.status == "deleted":
            continue
        previous = records.get(record.id)
        if previous is not None and previous != record:
            missing.append("同一来源编号存在冲突版本，须核对上游记录")
            # 冲突版本均不计数；即使后续再次出现同一记录也保留阻断提示。
            records.pop(record.id, None)
            conflicted.add(record.id)
            continue
        records[record.id] = record
    return sorted(records.values(), key=lambda item: item.id), sorted(set(missing))


def calculate_indicator(
    rule: dict[str, Any],
    batch: SourceBatch,
    evidence: list[dict[str, Any]],
    *,
    tenant_id: str,
    org_ids: set[str],
    as_of: date,
) -> dict[str, Any]:
    """按白名单公式计算预览；是否满足只是规则比较，正式评价须人工审核。"""
    records, missing = scoped_records(
        batch,
        tenant_id=tenant_id,
        org_ids=org_ids,
        start=date.fromisoformat(rule["period_start"]),
        end=min(date.fromisoformat(rule["period_end"]), as_of),
    )
    approved = [record for record in records if record.status == "approved"]
    if date.fromisoformat(rule["period_start"]) > as_of:
        missing.append("统计期间尚未开始")
    if len(approved) != len(records):
        missing.append("来源记录含未审核内容")
    if not batch.complete:
        missing.append("数据源尚未完整接入或统计口径待核验")
    actual: Decimal | None = None
    measure = rule["source_options"]["measure"]
    if measure == "count" and batch.complete:
        actual = Decimal(len(approved))
    elif measure == "sum" and approved:
        if any(record.value is None for record in approved):
            missing.append("人工特色项缺少有依据的数值")
        else:
            actual = sum((Decimal(record.value) for record in approved), Decimal(0))
    elif measure == "material_rate":
        if not approved:
            missing.append("材料完整率分母为零，不能判断达标")
        elif any(record.material_complete is None for record in approved):
            missing.append("材料完整性尚未核验")
        else:
            actual = (
                Decimal(sum(record.material_complete for record in approved))
                / Decimal(len(approved))
                * 100
            )
    elif measure == "attendance_rate":
        denominator = sum(len(set(record.expected_participants)) for record in approved)
        if not denominator:
            missing.append("参会/参学率分母为零或应参加名单缺失")
        elif any(not record.expected_participants for record in approved):
            missing.append("部分活动缺少应参加名单")
        elif any(
            set(record.participants) - set(record.expected_participants) for record in approved
        ):
            missing.append("参加名单超出应参加范围，须核验名单")
        else:
            numerator = sum(len(set(record.participants)) for record in approved)
            actual = Decimal(numerator) / Decimal(denominator) * 100
    if measure == "sum" and not approved:
        missing.append("缺少已审核的人工特色项及录入依据")
    if not rule["confirmed"]:
        missing.append("学校指标口径待确认")
    for key in rule["required_evidence"]:
        matches = [item for item in evidence if item["requirement_key"] == key]
        if not any(item["status"] == "approved" for item in matches):
            statuses = sorted({item["status"] for item in matches})
            missing.append(f"佐证「{key}」：{'、'.join(statuses) if statuses else '缺失'}")
    missing = sorted(set(missing))
    target = Decimal(rule["target"])
    satisfied = None
    if actual is not None and not missing:
        satisfied = {"gte": actual >= target, "lte": actual <= target, "eq": actual == target}[
            rule["comparison"]
        ]
    return {
        "code": rule["code"],
        "name": rule["name"],
        "rule_id": rule["id"],
        "rule_version": rule["version"],
        "requirement": rule["requirement"],
        "formula": rule["formula"],
        "source": rule["source"],
        "target": float(target),
        "actual": float(actual.quantize(Decimal("0.0001"))) if actual is not None else None,
        "satisfied": satisfied,
        "unit": rule["unit"],
        "period_start": rule["period_start"],
        "period_end": rule["period_end"],
        "sources": [record.reference(rule["source"]) for record in approved],
        "evidence": evidence,
        "missing": missing,
    }


def batch_snapshot(batch: SourceBatch) -> dict[str, Any]:
    """快照保留规范化输入；来源顺序不影响重复计算。"""
    records = {fingerprint(asdict(record)): asdict(record) for record in batch.records}
    return {
        "complete": batch.complete,
        "missing": sorted(set(batch.missing)),
        "records": [records[key] for key in sorted(records)],
    }


def task_state(
    task: dict[str, Any], result: dict[str, Any] | None, *, as_of: date, advance_days: int
) -> dict[str, Any]:
    """进度和完成从归集依据产生；声明100%不替代核验。"""
    missing = result["missing"] if result else ["该指标尚未生效或已调整"]
    complete = bool(result and result["satisfied"] is True and not missing)
    if result and result["source"] == "manual":
        complete = (
            complete and task["review_status"] == "approved" and task["declared_progress"] == 100
        )
    due = date.fromisoformat(task["due_date"])
    progress = 0
    if result and result["actual"] is not None and result["target"] > 0:
        progress = min(100, max(0, round(result["actual"] / result["target"] * 100)))
    if result and result["source"] == "manual":
        progress = task["declared_progress"]
    if complete:
        progress = 100
    return {
        **task,
        "progress": progress,
        "complete": complete,
        "missing": missing,
        "overdue": not complete and due < as_of,
        "due_soon": not complete and 0 <= (due - as_of).days <= advance_days,
    }
