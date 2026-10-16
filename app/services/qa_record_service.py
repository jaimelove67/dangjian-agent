"""问答记录的集中查看（T-SYS-06）。

本人档案口径只回答"我问过什么"；学校治理与合规复核要回答"这段时间谁问了什么、
哪些被拒答、哪些没有依据、用的是哪个数据级别"。这里只做**查询构造与取数**，
租户边界与角色判定留在接口层（跨租户仅平台管理员，复用身份口径）。

软删除的语义：提问人删除的是"我的列表里不再显示"，不是销毁证据。治理视图默认与本人
口径一致，但允许显式`include_deleted=True`查看已删除记录——否则删除就成了审计盲区。

时间口径：库里的 `created_at` 是 UTC 朴素时间（与审计表一致），比较用 UTC，**展示与筛选
说明按北京时间**——中国无夏令时，用固定 +08:00 即可，不引入时区库依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_time
from app.core.versions import PROMPT_LABELS
from app.models.qa_session import QASession
from app.models.user import User

#: 单次导出上限：超过会生成难以打开的大文件，也给不出可核对的行号
MAX_EXPORT_ROWS = 5000
#: 账号已注销或姓名缺失时的提问人显示，避免治理页出现空白单元格
UNKNOWN_ASKER = "已注销账号"

_DELETED_LABELS = {True: "含本人已删除的记录", False: "不含本人已删除的记录"}


@dataclass(frozen=True)
class QaRecordFilters:
    """集中查看的筛选条件（租户必填，其余按需）"""

    tenant_id: str
    user_id: Optional[str] = None
    keyword: Optional[str] = None
    data_level: Optional[str] = None
    refused: Optional[bool] = None
    has_evidence: Optional[bool] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    include_deleted: bool = False

    def scope_note(self) -> str:
        """把筛选口径写成一句话：导出文件必须能自证"按什么条件导出的"。"""
        parts = [_DELETED_LABELS[self.include_deleted]]
        if self.user_id:
            parts.append(f"仅提问人 {self.user_id}")
        if self.keyword:
            parts.append(f"问题或回答含「{self.keyword}」")
        if self.data_level:
            parts.append(f"数据级别 {self.data_level}")
        if self.refused is not None:
            parts.append("仅无依据拒答" if self.refused else "仅正常回答")
        if self.has_evidence is not None:
            parts.append("仅有依据" if self.has_evidence else "仅无依据")
        if self.start_at:
            parts.append("起 " + local_time(self.start_at))
        if self.end_at:
            parts.append("止 " + local_time(self.end_at))
        return "；".join(parts)


@dataclass
class QaRecordRow:
    """集中查看用的一行：问答记录 + 提问人标识"""

    id: str
    user_id: str
    asker: str
    username: str
    question: str
    answer: str
    data_level: str
    refused: bool
    has_sufficient_evidence: bool
    retrieved_count: int
    used_count: int
    citation_count: int
    warning_count: int
    is_deleted: bool
    created_at: datetime
    session_id: Optional[str] = None
    #: 版本指纹（SEC-11）：这条答案由哪个提示词 / 工作流契约版本产出；上线前为空
    versions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any) -> "QaRecordRow":
        record, name, username = row
        return cls(
            id=str(record.id),
            user_id=str(record.user_id),
            asker=str(name or username or UNKNOWN_ASKER),
            username=str(username or ""),
            question=record.question,
            answer=record.answer,
            data_level=str(record.data_level),
            refused=bool(record.refused),
            has_sufficient_evidence=bool(record.has_sufficient_evidence),
            retrieved_count=int(record.retrieved_count or 0),
            used_count=int(record.used_count or 0),
            citation_count=len(record.citations or []),
            warning_count=len(record.warnings or []),
            is_deleted=bool(record.is_deleted),
            created_at=record.created_at,
            session_id=record.session_id,
            versions=dict(record.versions or {}),
        )


def versions_text(versions: dict[str, Any] | None) -> str:
    """把版本指纹压成一行（SEC-11）：导出与列表共用一个说法，不各处拼字符串。

    返回空串表示"这条记录没有版本指纹"（本功能上线前的历史记录），由调用方决定
    显示成什么文案——服务层不自拟界面文案。
    """
    data = versions or {}
    prompt = data.get("prompt") or {}
    workflow = data.get("workflow") or {}
    parts = []
    if prompt:
        parts.append(
            "提示词："
            + " / ".join(
                f"{PROMPT_LABELS.get(kind, kind)} {value}" for kind, value in prompt.items()
            )
        )
    if workflow:
        parts.append("工作流：" + " / ".join(f"{wid} {value}" for wid, value in workflow.items()))
    return "；".join(parts)


def build_qa_record_query(filters: QaRecordFilters) -> Select[Any]:
    """构造问答记录查询（仅构造，不执行；权限与租户由调用方决定）

    提问人用外连接：账号被清理后记录仍要能查，不能因为查不到用户就整条消失。
    """
    stmt = (
        select(QASession, User.name, User.username)
        .outerjoin(User, User.id == QASession.user_id)
        .where(QASession.tenant_id == filters.tenant_id)
    )
    if not filters.include_deleted:
        stmt = stmt.where(QASession.is_deleted.is_(False))
    if filters.user_id is not None:
        stmt = stmt.where(QASession.user_id == filters.user_id)
    if filters.keyword:
        like = f"%{filters.keyword}%"
        stmt = stmt.where(or_(QASession.question.ilike(like), QASession.answer.ilike(like)))
    if filters.data_level is not None:
        stmt = stmt.where(QASession.data_level == filters.data_level)
    if filters.refused is not None:
        stmt = stmt.where(QASession.refused.is_(filters.refused))
    if filters.has_evidence is not None:
        stmt = stmt.where(QASession.has_sufficient_evidence.is_(filters.has_evidence))
    if filters.start_at is not None:
        stmt = stmt.where(QASession.created_at >= filters.start_at.replace(tzinfo=None))
    if filters.end_at is not None:
        stmt = stmt.where(QASession.created_at <= filters.end_at.replace(tzinfo=None))
    return stmt.order_by(QASession.created_at.desc(), QASession.id)


async def count_qa_records(db: AsyncSession, filters: QaRecordFilters) -> int:
    """按同一筛选口径统计条数（导出前用于判定是否超过上限）"""
    stmt = build_qa_record_query(filters)
    total = (
        await db.execute(stmt.with_only_columns(func.count()).select_from(QASession).order_by(None))
    ).scalar_one()
    return int(total)


async def fetch_qa_records(
    db: AsyncSession, filters: QaRecordFilters, *, offset: int = 0, limit: int = 40
) -> list[QaRecordRow]:
    """按筛选口径取数（分页或整份导出共用）"""
    stmt = build_qa_record_query(filters).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [QaRecordRow.from_row(row) for row in rows]
