"""知识文档状态变更审计（可选功能，用于记录状态变更历史）"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDoc

logger = logging.getLogger(__name__)


async def record_status_change(
    db: AsyncSession,
    *,
    document: KnowledgeDoc,
    old_status: str,
    new_status: str,
    changed_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """记录文档状态变更（可扩展：写入审计表）

    Args:
        db: 数据库会话
        document: 文档对象
        old_status: 旧状态
        new_status: 新状态
        changed_by: 变更操作人
        reason: 变更原因
    """
    logger.info(
        "knowledge_document_status_change_audited",
        extra={
            "doc_id": document.doc_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": changed_by,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    # TODO: 将来可扩展为写入 DocumentStatusHistory 表
    # history = DocumentStatusHistory(
    #     doc_id=document.id,
    #     old_status=old_status,
    #     new_status=new_status,
    #     changed_by=changed_by,
    #     reason=reason,
    # )
    # db.add(history)
    # await db.flush()
