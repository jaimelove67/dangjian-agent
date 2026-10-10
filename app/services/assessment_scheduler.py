"""用现有数据库执行站内提醒扫描；停机后补偿、重复扫描去重，不发送外部消息。"""

import asyncio
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.config import settings
from app.core.security import Permission, has_permission
from app.core.tenant import bypass_tenant_filter, tenant_context
from app.db.session import async_session_maker
from app.models.assessment import AssessmentTask
from app.models.user import User
from app.services.assessment_service import AssessmentService
from app.services.org_scope import knowledge_org_ids

logger = logging.getLogger(__name__)


async def scan_assessment_reminders() -> int:
    """仅系统扫描枚举任务租户，随后每组按责任用户的当前权限执行。"""
    async with async_session_maker() as db:
        with bypass_tenant_filter():
            groups = (
                await db.execute(
                    select(
                        AssessmentTask.tenant_id,
                        AssessmentTask.org_unit_id,
                        AssessmentTask.year,
                        AssessmentTask.owner_id,
                    )
                    .where(AssessmentTask.is_deleted.is_(False))
                    .distinct()
                )
            ).all()
    completed = 0
    for tenant_id, org_id, year, owner_id in groups:
        with tenant_context(tenant_id, user_id=owner_id):
            async with async_session_maker() as db:
                owner = (
                    await db.execute(
                        select(User).where(
                            User.id == owner_id,
                            User.tenant_id == tenant_id,
                            User.is_deleted.is_(False),
                            User.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if owner is None or not has_permission(owner.role, Permission.ASSESSMENT_QUERY):
                    continue
                try:
                    owner.knowledge_org_ids = await knowledge_org_ids(db, owner)
                    service = AssessmentService(db, owner)
                    records = await service.sync_reminders(org_id, year)
                    await write_audit(
                        db,
                        tenant_id=tenant_id,
                        user_id=owner_id,
                        user_name=owner.username,
                        action="assessment_scheduled_scan",
                        resource_type="assessment",
                        request_id=uuid.uuid4().hex,
                        result="success",
                        data_level="sensitive",
                        new_value={
                            "reminder_count": len(records),
                            "year": year,
                            "changes": service.audit_changes,
                        },
                    )
                    await db.commit()
                    completed += 1
                except HTTPException:
                    await db.rollback()
    return completed


async def assessment_reminder_loop() -> None:
    """依赖暂不可用时保留重试；取消由应用关闭流程等待完成。"""
    while True:
        try:
            await scan_assessment_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 不记录数据库URL、参数、人员材料或异常原文。
            logger.warning("assessment_reminder_scan_failed_will_retry")
        await asyncio.sleep(settings.ASSESSMENT_REMINDER_SCAN_SECONDS)
