"""工作流运行日志（T-SYS-06E）：从审计轨迹回答"这个任务/这轮扫描跑成什么样"。

为什么不新建一张运行日志表：任务队列的每次入队、每次尝试失败、每次完成，以及三个定时
扫描的结果**本来就已经写进审计**（`job_enqueue` / `job_attempt_failed` / `job_completed` /
`member_scheduled_scan` / `assessment_scheduled_scan` / `assessment_reminders_scan`）。
再建一张表就是把同一个事实写两遍，还会多出"两张表不一致时信谁"的问题。这里做的是
**读模型**：按事件类型筛出这些审计行，把 `new_value` 里的第几次、耗时、错误码、处理条数
摊平成一行行可读的运行日志。

任务类型以任务表为准（`DurableJob.kind`）：入队审计的 `new_value` 走仓库统一的摘要口径
（只留 sha256 与字节数），拿不到明文类型，所以按 `resource_id` 批量补一次；查不到任务行
（任务记录已清理）就留空，不编造。

时间口径：库里的 `created_at` 是 UTC 朴素时间（与审计表一致），比较用 UTC、**说明按北京
时间**；失败只记错误类型与状态，不记供应商错误正文（审计本来就不存正文）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_time
from app.models.audit import AuditLog
from app.models.governance import DurableJob

#: 运行日志收录的事件：任务生命周期 + 三个定时扫描。
#: 键是审计动作名，值是给人看的阶段名（界面直接用，不再各处翻译一遍）。
RUN_EVENTS: dict[str, str] = {
    "job_enqueue": "任务入队",
    "job_attempt_failed": "执行失败",
    "job_completed": "执行完成",
    "member_scheduled_scan": "党员提醒扫描",
    "assessment_scheduled_scan": "考核提醒扫描",
    "assessment_reminders_scan": "考核提醒同步",
}

#: 任务类型筛选的允许值（与任务表 `DurableJob.kind` 一致）
RUN_KINDS = ("member_reminders", "assessment_reminders", "embedding")

EVENT_CHOICES = tuple(RUN_EVENTS)


def _payload(row: AuditLog) -> dict[str, Any]:
    """审计行的变更内容；老记录或摘要行可能不是 dict，一律当空处理"""
    value = row.new_value
    return value if isinstance(value, dict) else {}


def _text(payload: dict[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _number(payload: dict[str, Any], key: str) -> Optional[int]:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


@dataclass(frozen=True)
class RunLogFilters:
    """运行日志的筛选条件（租户必填，其余按需）"""

    tenant_id: str
    event: Optional[str] = None
    kind: Optional[str] = None
    result: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None

    def scope_note(self) -> str:
        """把筛选口径写成一句话：界面要能自证这段日志是按什么条件筛出来的"""
        parts = [f"租户 {self.tenant_id}"]
        if self.event:
            parts.append(f"事件 {RUN_EVENTS.get(self.event, self.event)}")
        if self.kind:
            parts.append(f"任务类型 {self.kind}")
        if self.result:
            parts.append(f"结果 {self.result}")
        if self.start_at:
            parts.append("起 " + local_time(self.start_at))
        if self.end_at:
            parts.append("止 " + local_time(self.end_at))
        return "；".join(parts)


@dataclass
class RunLogRow:
    """运行日志的一行：审计事件 + 任务类型（以任务表为准）"""

    id: str
    created_at: datetime
    event: str
    event_text: str
    result: str
    kind: Optional[str] = None
    status: Optional[str] = None
    attempt: Optional[int] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    processed: Optional[int] = None
    reminder_count: Optional[int] = None
    resource_id: Optional[str] = None
    request_id: Optional[str] = None

    @classmethod
    def from_audit(cls, row: AuditLog, kind: Optional[str] = None) -> "RunLogRow":
        payload = _payload(row)
        return cls(
            id=str(row.id),
            created_at=row.created_at,
            event=str(row.action),
            event_text=RUN_EVENTS.get(str(row.action), str(row.action)),
            result=str(row.result),
            kind=kind or _text(payload, "kind"),
            status=_text(payload, "status"),
            attempt=_number(payload, "attempt"),
            duration_ms=_number(payload, "duration_ms"),
            error_code=_text(payload, "error_code"),
            processed=_number(payload, "processed"),
            reminder_count=_number(payload, "reminder_count"),
            resource_id=row.resource_id,
            request_id=row.request_id,
        )


def build_run_log_query(filters: RunLogFilters) -> Select[Any]:
    """构造运行日志查询（仅构造不执行；租户边界由接口层决定）

    任务类型按**任务表**口径筛：定时扫描是调度器行为、不属于某一条任务，按类型筛时
    不出现（用事件筛"党员提醒扫描"可以单独看）。
    """
    stmt = select(AuditLog).where(
        AuditLog.tenant_id == filters.tenant_id,
        AuditLog.is_deleted.is_(False),
        AuditLog.action.in_(EVENT_CHOICES),
    )
    if filters.event:
        stmt = stmt.where(AuditLog.action == filters.event)
    if filters.kind:
        stmt = stmt.where(
            AuditLog.resource_id.in_(select(DurableJob.id).where(DurableJob.kind == filters.kind))
        )
    if filters.result:
        stmt = stmt.where(AuditLog.result == filters.result)
    if filters.start_at:
        stmt = stmt.where(AuditLog.created_at >= filters.start_at)
    if filters.end_at:
        stmt = stmt.where(AuditLog.created_at <= filters.end_at)
    return stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())


async def count_run_logs(db: AsyncSession, filters: RunLogFilters) -> int:
    """按同一筛选口径统计条数"""
    stmt = build_run_log_query(filters)
    total = (await db.execute(stmt.with_only_columns(func.count()).order_by(None))).scalar_one()
    return int(total)


async def job_kinds(db: AsyncSession, rows: list[AuditLog]) -> dict[str, str]:
    """批量补任务类型：一次查询覆盖当前页涉及的作业，不做 N+1"""
    ids = {str(row.resource_id) for row in rows if row.resource_type == "job" and row.resource_id}
    if not ids:
        return {}
    pairs = (
        await db.execute(select(DurableJob.id, DurableJob.kind).where(DurableJob.id.in_(ids)))
    ).all()
    return {str(job_id): str(kind) for job_id, kind in pairs}


async def fetch_run_logs(
    db: AsyncSession, filters: RunLogFilters, *, offset: int = 0, limit: int = 40
) -> list[RunLogRow]:
    """按筛选口径取数（分页），并把任务类型补齐"""
    stmt = build_run_log_query(filters).offset(offset).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    kinds = await job_kinds(db, rows)
    return [RunLogRow.from_audit(row, kinds.get(str(row.resource_id))) for row in rows]
