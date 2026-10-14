"""按登录租户与用户保存、分页查询长期问答记录。事务由接口管理。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qa_session import QASession


async def create_session(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
    data_level: str,
    response: dict[str, Any],
) -> QASession:
    record = QASession(
        tenant_id=tenant_id,
        user_id=user_id,
        question=question,
        data_level=data_level,
        **response,
    )
    db.add(record)
    await db.flush()
    return record


async def list_sessions(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QASession], int]:
    conditions = (
        QASession.tenant_id == tenant_id,
        QASession.user_id == user_id,
        QASession.is_deleted.is_(False),
    )
    total = (await db.execute(select(func.count(QASession.id)).where(*conditions))).scalar_one()
    statement = (
        select(QASession)
        .where(*conditions)
        .order_by(QASession.created_at.desc(), QASession.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(statement)).scalars().all()), int(total)


async def soft_delete_session(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    session_record_id: str,
) -> bool:
    """按租户与用户软删除一条长期问答记录。

    返回是否命中：不命中的原因（不存在、他人记录、跨租户、已删除）一律对调用方
    等价处理，避免通过错误码差异探测其他用户的记录是否存在。
    """
    record = (
        await db.execute(
            select(QASession).where(
                QASession.id == session_record_id,
                QASession.tenant_id == tenant_id,
                QASession.user_id == user_id,
                QASession.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        return False
    record.is_deleted = True
    await db.flush()
    return True
