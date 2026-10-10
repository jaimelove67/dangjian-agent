"""问答历史服务

负责把每次成功的问答写入 ``qa_sessions`` 表，并提供按「租户 + 用户」分页
查询历史记录的能力。租户与用户标识一律取自登录态，不接受前端传入。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qa_session import QASession

logger = logging.getLogger(__name__)


async def create_session(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
    answer: str,
    citations: Optional[list[dict[str, Any]]] = None,
    data_level: str = "public",
    has_sufficient_evidence: bool = False,
    retrieved_count: int = 0,
    used_count: int = 0,
) -> QASession:
    """落库一条问答历史

    调用方（API 层）负责 commit；本函数只负责创建与 flush（触发 tenant_id 注入）。
    """
    session = QASession(
        tenant_id=tenant_id,
        user_id=user_id,
        question=question,
        answer=answer,
        citations=citations or [],
        data_level=data_level,
        has_sufficient_evidence=has_sufficient_evidence,
        retrieved_count=retrieved_count,
        used_count=used_count,
    )
    db.add(session)
    await db.flush()
    return session


async def list_sessions(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QASession], int]:
    """分页查询当前用户在租户内的问答历史（按时间倒序）"""
    conditions = [
        QASession.tenant_id == tenant_id,
        QASession.user_id == user_id,
        QASession.is_deleted.is_(False),
    ]

    total = (
        await db.execute(select(func.count(QASession.id)).where(*conditions))
    ).scalar_one()

    stmt = (
        select(QASession)
        .where(*conditions)
        .order_by(QASession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    sessions = list((await db.execute(stmt)).scalars().all())
    return sessions, int(total)