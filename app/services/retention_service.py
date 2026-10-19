"""保留期现状报告（T-SEC-07）：把治理页填写的保留天数变成可核对的数字。

口径（为什么这样算，而不是"文件超过 N 天就报到期"）：

- ``file_days`` 只用于**已软删除记录的原件**：在用条目的原件不参与保留期核对。
  制度文件的寿命与文件年龄无关，按文件年龄报"到期"会诱导管理员删掉仍在执行的
  制度文件——那比不报更糟。
- ``audit_days`` 是审计条目的**下限**（不少于一年），超过不表示违规：审计只追加
  不修改，系统不清理审计，超过保留期的条目由组织决定归档 / 清理。
- **不提供自动物理清理**：本模块只给清单与口径。清理范围与审批属学校批准的删除
  流程（治理页 ``physical_purge`` / ``evidence`` 记的就是这份审批），系统不做
  "一键删除"：删错了没有回退，而软删除已经保留了证据与留痕。

时间口径：库里的时间列是 UTC 朴素时间，展示走 ``local_time``（北京时间）；文件
时间戳先换算成 UTC 朴素再比较，避免边界差 8 小时。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import as_utc_naive, local_time
from app.models.audit import AuditLog
from app.models.knowledge import KnowledgeDoc
from app.models.member import MemberMaterial, MemberProfile
from app.models.org import OrgUnit
from app.models.qa_session import QASession
from app.models.user import User

#: 单次扫描的文件上限；超过则报 ``truncated``，不假装"已经数完"
FILE_SCAN_LIMIT = 20000

#: 软删除记录按表核对；标签用于界面，不把表名直接摆给管理员
DELETED_TABLES: tuple[tuple[str, str, Any], ...] = (
    ("knowledge_docs", "知识条目", KnowledgeDoc),
    ("member_profiles", "党员档案", MemberProfile),
    ("member_materials", "党员材料", MemberMaterial),
    ("qa_sessions", "长期问答记录", QASession),
    ("users", "账号", User),
    ("org_units", "组织单元", OrgUnit),
)

#: 文件用途标签；用途解析不出来的不猜，统一按"其他 / 未识别"计数
FILE_KINDS: dict[str, str] = {
    "originals": "制度文件原件",
    "archives": "归档快照",
}

_ORIGINAL_NAME = re.compile(r"(.+)__v([1-9][0-9]*)(?:__h([a-f0-9]{64}))?\.bin")
_ARCHIVE_ID = re.compile(r"archive-[a-f0-9]{32}")
_TENANT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _stamp(value: Optional[datetime]) -> str:
    """UTC 朴素时间 → 北京时间文本；带时区的输入先换算（文件时间戳用得到）"""
    return local_time(as_utc_naive(value))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _naive(value: datetime) -> datetime:
    """比较用 UTC 朴素时间；非空输入一定拿得到值（``as_utc_naive`` 只对 None 返回 None）"""
    converted = as_utc_naive(value)
    return converted if converted is not None else value


def scan_storage(
    root: Optional[Path],
    tenant_id: str,
    *,
    deleted_doc_ids: set[str],
    file_days: int,
    now: datetime,
    limit: int = FILE_SCAN_LIMIT,
) -> dict[str, Any]:
    """扫描本租户的加密存储：按用途分类，并单独核对"已删除知识条目的原件"。

    只统计调用方租户目录，不跨租户；符号链接一律不算（与文件轮换工具同一口径）。
    无法解析用途的文件不参与任何核对，只在"其他 / 未识别"里计数——宁可少报，不猜。
    归档快照按业务编号哈希命名，判不出归属记录，只计入总数、不纳入已删除记录核对。
    """
    counts: dict[str, int] = {"originals": 0, "archives": 0, "other": 0}
    result: dict[str, Any] = {
        "storage": "本地认证加密文件存储（FILE_STORAGE_DIR）",
        "scanned": 0,
        "truncated": False,
        "total": 0,
        "by_kind": [],
        "deleted_docs_total": 0,
        "deleted_docs_expired": 0,
        "unreadable": 0,
        "oldest": "",
        "newest": "",
    }
    oldest: Optional[datetime] = None
    newest: Optional[datetime] = None
    cutoff = _naive(now) - timedelta(days=file_days)
    tenant_root = (root / tenant_id) if root is not None else None
    if tenant_root is not None and _TENANT_ID.fullmatch(tenant_id) and tenant_root.is_dir():
        for path in sorted(tenant_root.rglob("*")):
            if result["scanned"] >= limit:
                result["truncated"] = True
                break
            if path.is_symlink() or not path.is_file():
                continue
            result["scanned"] += 1
            try:
                modified = as_utc_naive(
                    datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                )
            except OSError:
                result["unreadable"] += 1
                continue
            if modified is not None:
                oldest = modified if oldest is None or modified < oldest else oldest
                newest = modified if newest is None or modified > newest else newest
            match = _ORIGINAL_NAME.fullmatch(path.name)
            relative = path.relative_to(tenant_root)
            if match is None or len(relative.parts) != 2 or relative.parts[0] != "originals":
                counts["other"] += 1
                continue
            doc_id = match.group(1)
            if _ARCHIVE_ID.fullmatch(doc_id):
                counts["archives"] += 1
                continue
            counts["originals"] += 1
            if doc_id in deleted_doc_ids:
                result["deleted_docs_total"] += 1
                if modified is not None and modified < cutoff:
                    result["deleted_docs_expired"] += 1
    result["total"] = counts["originals"] + counts["archives"] + counts["other"]
    result["by_kind"] = [
        {"kind": kind, "label": FILE_KINDS.get(kind, "其他 / 未识别"), "total": counts[kind]}
        for kind in ("originals", "archives", "other")
    ]
    result["oldest"] = _stamp(oldest)
    result["newest"] = _stamp(newest)
    return result


async def deleted_records(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """按表统计已软删除的记录：这是"到期核对"的输入，不是"该删了"的判决。"""
    rows: list[dict[str, Any]] = []
    total = 0
    oldest: Optional[datetime] = None
    for table, label, model in DELETED_TABLES:
        count, first = (
            await db.execute(
                select(func.count(model.id), func.min(model.updated_at)).where(
                    model.tenant_id == tenant_id, model.is_deleted.is_(True)
                )
            )
        ).one()
        rows.append(
            {
                "table": table,
                "label": label,
                "count": int(count),
                "oldest_deleted_at": _stamp(first),
            }
        )
        total += int(count)
        if first is not None and (oldest is None or first < oldest):
            oldest = first
    return {"total": total, "oldest_deleted_at": _stamp(oldest), "tables": rows}


async def deleted_doc_ids(db: AsyncSession, tenant_id: str) -> set[str]:
    """已软删除的知识条目 id：用文件名里的 doc_id 把它们与原件对上"""
    return set(
        (
            await db.execute(
                select(KnowledgeDoc.id).where(
                    KnowledgeDoc.tenant_id == tenant_id,
                    KnowledgeDoc.is_deleted.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


async def audit_retention(
    db: AsyncSession, tenant_id: str, *, audit_days: int, now: datetime
) -> dict[str, Any]:
    """审计条目的保留期现状：总数与"超过保留期"的条数（下限口径，不表示违规）"""
    total, oldest, newest = (
        await db.execute(
            select(
                func.count(AuditLog.id),
                func.min(AuditLog.created_at),
                func.max(AuditLog.created_at),
            ).where(AuditLog.tenant_id == tenant_id)
        )
    ).one()
    cutoff = _naive(now) - timedelta(days=audit_days)
    expired = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.tenant_id == tenant_id, AuditLog.created_at < cutoff
            )
        )
    ).scalar_one()
    return {
        "total": int(total),
        "expired": int(expired),
        "oldest": _stamp(oldest),
        "newest": _stamp(newest),
    }


async def retention_report(
    db: AsyncSession,
    *,
    tenant_id: str,
    policy: dict[str, Any],
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    limit: int = FILE_SCAN_LIMIT,
) -> dict[str, Any]:
    """保留期现状：软删除记录 + 审计条目 + 文件存储，与治理页填写的天数同一口径。"""
    file_days = int(policy.get("file_days") or 365)
    audit_days = int(policy.get("audit_days") or 365)
    moment = now or _utc_now()
    files = scan_storage(
        root,
        tenant_id,
        deleted_doc_ids=await deleted_doc_ids(db, tenant_id),
        file_days=file_days,
        now=moment,
        limit=limit,
    )
    return {
        "as_of": _stamp(moment),
        "policy": {
            "file_days": file_days,
            "audit_days": audit_days,
            "physical_purge": str(policy.get("physical_purge") or "disabled"),
            "purge_evidence_present": bool(str(policy.get("evidence") or "").strip()),
        },
        "deleted": await deleted_records(db, tenant_id),
        "files": files,
        "audit": await audit_retention(db, tenant_id, audit_days=audit_days, now=moment),
        "boundary": {
            "auto_purge": False,
            "note": (
                "系统不自动清理任何业务数据或审计，也不提供一键物理清理：软删除已保留证据与"
                "留痕，清理范围与审批按学校批准的删除流程执行。"
            ),
        },
        "notes": [
            "文件保留天数只用于已软删除知识条目的原件；在用条目（含长期有效的制度文件）不参与保留期核对。",
            "归档快照按业务编号哈希命名，判不出归属记录，只计入总数、不纳入已删除记录核对。",
            "审计缓冲由审计重放消费，不属于保留期清理范围。",
            "审计保留天数是下限（不少于一年），超过不表示违规；审计只追加不修改，系统不清理审计。",
            "软删除记录的最早删除时间取记录最后更新时间（删除即一次更新）。",
        ],
    }
