"""版本留痕（T-SEC-11）：提示词 / 工作流 / 知识库三个版本的可查记录。

三个版本各自的**权威出处**不同，这里不另立一套登记表——同一事实两处登记必然对不上：

- **提示词**：租户配置历史表 ``config_revisions``。谁、何时、为什么改，以及改成了什么版本，
  本表都有；配置审计的 ``new_value`` 走统一摘要口径（正文哈希），版本号靠本表回答，不从审计猜。
- **知识库**：条目入库（``create``）与内容更新（``update_content``）的审计。审计白名单保留
  ``revision`` 整数，因此"改到第几版"可读；只改元数据 / 状态的动作不留修订号，不属于
  版本变更，这里不收录。入库即第 1 版（由 ``update_content`` 的 ``old_value.revision``
  可反推同一口径）。
- **工作流**：契约版本是代码常量（``app/core/versions.py``），只给现行值。它的变更历史在
  代码与发布记录里，数据库里没有——不编造。

时间口径与运行日志一致：库里是 UTC 朴素时间，比较用 UTC，**展示说明按北京时间**。
租户边界与权限判定留在接口层。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.versions import PROMPT_DEFAULTS, PROMPT_LABELS
from app.models.audit import AuditLog
from app.models.governance import ConfigRevision
from app.models.knowledge import KnowledgeDoc
from app.models.user import User

#: 知识库版本事件：入库 + 内容更新（动作名已在审计里分开，不靠猜 new_value 的形状）
KNOWLEDGE_EVENTS: dict[str, str] = {"create": "入库", "update_content": "内容更新"}

#: 提示词变更历史的回溯上限：配置版本不多，给足即可，避免一次拉全表
PROMPT_HISTORY_LIMIT = 200
#: 账号已注销或姓名缺失时的显示
UNKNOWN_ACTOR = "已注销账号"


@dataclass(frozen=True)
class VersionChange:
    """一次版本变化（同一次配置提交里可能有多种提示词同时变）"""

    kind: str
    before: str | None
    after: str


@dataclass
class PromptVersionEntry:
    """一次改动过提示词版本的配置提交"""

    config_version: int
    changed_at: datetime
    actor: str
    username: str
    reason: str
    prompt_versions: dict[str, str]
    changes: list[VersionChange]


@dataclass
class KnowledgeRevisionRow:
    """知识库版本留痕的一行"""

    created_at: datetime
    event: str
    event_text: str
    doc_id: str | None
    title: str | None
    revision: int | None
    previous_revision: int | None
    actor: str
    username: str
    resource_id: str | None

    @classmethod
    def from_row(cls, row: Any) -> "KnowledgeRevisionRow":
        audit, doc_id, title, name, username = row
        new_value = audit.new_value if isinstance(audit.new_value, dict) else {}
        old_value = audit.old_value if isinstance(audit.old_value, dict) else {}
        revision = new_value.get("revision")
        # 入库没有 revision 字段（内容更新才有），但"入库即第 1 版"是定义，不是推测；
        # 其余情况拿不到数字就留空，界面显示"—"，不编造。
        revision = (
            int(revision)
            if isinstance(revision, int)
            else (1 if audit.action == "create" else None)
        )
        previous = old_value.get("revision")
        return cls(
            created_at=audit.created_at,
            event=str(audit.action),
            event_text=KNOWLEDGE_EVENTS.get(str(audit.action), str(audit.action)),
            doc_id=str(doc_id) if doc_id else None,
            title=str(title) if title else None,
            revision=revision,
            previous_revision=int(previous) if isinstance(previous, int) else None,
            actor=str(name or username or UNKNOWN_ACTOR),
            username=str(username or ""),
            resource_id=str(audit.resource_id) if audit.resource_id else None,
        )


def effective_prompt_versions(values: dict[str, Any] | None) -> dict[str, str]:
    """按一次配置提交的取值算出**当时生效**的提示词版本

    与 ``app/core/versions.py::prompt_versions`` 同一个默认值来源：配置缺省项回落
    出厂默认（v1）。配置里清空某项等于回到默认，这在历史里也要看得见。
    """
    configured = (values or {}).get("prompt_versions") or {}
    return {kind: str(configured.get(kind) or default) for kind, default in PROMPT_DEFAULTS.items()}


async def _actor_names(db: AsyncSession, ids: Sequence[str]) -> dict[str, tuple[str, str]]:
    """批量取操作人显示名（一次性查询，避免逐行回表）"""
    unique = {str(item) for item in ids if item}
    if not unique:
        return {}
    rows = (
        await db.execute(select(User.id, User.name, User.username).where(User.id.in_(unique)))
    ).all()
    return {str(row.id): (row.name or "", row.username or "") for row in rows}


def prompt_changes(
    rows: Sequence[ConfigRevision], names: dict[str, tuple[str, str]]
) -> list[PromptVersionEntry]:
    """把配置历史折算成"提示词版本变更"清单（纯函数，便于单测）

    ``rows`` 必须按配置版本**升序**给出：只有按顺序比较前后两个版本，才能说清
    "从什么改成了什么"。没有任何提示词变化的提交不进清单——配置多半是为别的
    字段改的，全列出来只会把真正的版本变更淹掉。
    """
    entries: list[PromptVersionEntry] = []
    previous: dict[str, str] | None = None
    for row in rows:
        current = effective_prompt_versions(row.values)
        if previous is None:
            # 首次登记：每个提示词都从"无"变成当时的取值，这本身就是版本留痕。
            changes = [VersionChange(kind, None, value) for kind, value in current.items()]
        else:
            changes = [
                VersionChange(kind, previous.get(kind), value)
                for kind, value in current.items()
                if previous.get(kind) != value
            ]
        if changes:
            name, username = names.get(str(row.actor_id), ("", ""))
            entries.append(
                PromptVersionEntry(
                    config_version=int(row.version),
                    changed_at=row.created_at,
                    actor=name or username or UNKNOWN_ACTOR,
                    username=username,
                    reason=str(row.reason or ""),
                    prompt_versions=current,
                    changes=changes,
                )
            )
        previous = current
    return entries


async def prompt_version_history(
    db: AsyncSession, tenant_id: str, *, limit: int = PROMPT_HISTORY_LIMIT
) -> list[PromptVersionEntry]:
    """提示词版本变更历史（最新在前）"""
    # 先取最新的 N 个配置版本，再按升序折算：降序 + limit 才能保证截断的是老版本，
    # 而不是把最近的改动漏掉。
    rows = (
        (
            await db.execute(
                select(ConfigRevision)
                .where(ConfigRevision.tenant_id == tenant_id)
                .order_by(ConfigRevision.version.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    ordered = list(reversed(rows))
    names = await _actor_names(db, [row.actor_id for row in ordered])
    return list(reversed(prompt_changes(ordered, names)))


def build_knowledge_revision_query(tenant_id: str) -> Select[Any]:
    """知识库版本留痕查询（只构造，权限与租户由调用方决定）

    条目可能已被软删除，因此外连接知识条目：删掉的条目仍要能查到"谁在什么时候
    把它改到第几版"。账号同理，查不到用户时用外连接留空而不是整条消失。
    """
    return (
        select(AuditLog, KnowledgeDoc.doc_id, KnowledgeDoc.title, User.name, User.username)
        .outerjoin(KnowledgeDoc, KnowledgeDoc.id == AuditLog.resource_id)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.resource_type == "knowledge_doc",
            AuditLog.result == "success",
            AuditLog.action.in_(tuple(KNOWLEDGE_EVENTS)),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
    )


async def count_knowledge_revisions(db: AsyncSession, tenant_id: str) -> int:
    """按同一口径统计条数（分页用）"""
    stmt = build_knowledge_revision_query(tenant_id)
    total = (
        await db.execute(stmt.with_only_columns(func.count()).select_from(AuditLog).order_by(None))
    ).scalar_one()
    return int(total)


async def fetch_knowledge_revisions(
    db: AsyncSession, tenant_id: str, *, offset: int = 0, limit: int = 20
) -> list[KnowledgeRevisionRow]:
    """取知识库版本留痕（分页）"""
    stmt = build_knowledge_revision_query(tenant_id).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [KnowledgeRevisionRow.from_row(row) for row in rows]


def prompt_scope_note(tenant_id: str, history_count: int) -> str:
    """提示词区块的口径说明（界面与报告都要能自证）"""
    defaults = "、".join(
        f"{PROMPT_LABELS.get(kind, kind)} {value}" for kind, value in PROMPT_DEFAULTS.items()
    )
    return (
        f"租户 {tenant_id}；提示词版本来自租户配置（缺省回落到出厂默认 {defaults}），"
        f"变更历史取自配置版本表（最多回溯最近 {PROMPT_HISTORY_LIMIT} 个版本，"
        f"当前命中 {history_count} 次版本变更）"
    )


def knowledge_scope_note(tenant_id: str) -> str:
    """知识库区块的口径说明：只说审计里真的有的东西"""
    return (
        f"租户 {tenant_id}；来源为知识条目的入库与内容更新审计，只记修订号与操作人，"
        "不含被改动的正文（正文在审计里按摘要口径脱敏）；只改元数据 / 状态的动作不计入版本变更"
    )
