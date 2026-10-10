"""用现有数据库执行党员发展站内提醒扫描；停机后补偿、重复扫描去重，不发送外部消息。"""

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
from app.models.member import MemberProfile
from app.models.user import User, UserRole
from app.services.member_service import MemberDevelopment

logger = logging.getLogger(__name__)

_OWNER_PRIORITY = [
    UserRole.SYSTEM_ADMIN,
    UserRole.SCHOOL_ADMIN,
    UserRole.DEPARTMENT_ADMIN,
    UserRole.BRANCH_SECRETARY,
    UserRole.ORGANIZER,
]


async def scan_member_reminders() -> int:
    """按租户选择有权限的操作人执行扫描；同一人员同一提醒天然去重。"""
    async with async_session_maker() as db:
        with bypass_tenant_filter():
            tenant_ids = (
                (
                    await db.execute(
                        select(MemberProfile.tenant_id)
                        .where(MemberProfile.is_deleted.is_(False))
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
    completed = 0
    for tenant_id in tenant_ids:
        with tenant_context(tenant_id, user_id="member-scheduler"):
            async with async_session_maker() as db:
                with bypass_tenant_filter():
                    users = (
                        (
                            await db.execute(
                                select(User).where(
                                    User.tenant_id == tenant_id,
                                    User.is_deleted.is_(False),
                                    User.is_active.is_(True),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                owner = next(
                    (user for user in users if has_permission(user.role, Permission.MEMBER_QUERY)),
                    None,
                )
                if owner is None:
                    continue
                try:
                    owner.knowledge_org_ids = []
                    service = MemberDevelopment(db, owner)
                    await service.initialize()
                    created = await service.scan_all_reminders()
                    await write_audit(
                        db,
                        tenant_id=tenant_id,
                        user_id=str(owner.id),
                        user_name=owner.username,
                        action="member_scheduled_scan",
                        resource_type="member_reminder",
                        request_id=uuid.uuid4().hex,
                        result="success",
                        data_level="sensitive",
                        new_value={"reminder_count": created},
                    )
                    await db.commit()
                    completed += 1
                except HTTPException:
                    await db.rollback()
    return completed


async def member_reminder_loop() -> None:
    """调度循环；依赖暂不可用时保留重试，取消由应用关闭流程等待完成。"""
    while True:
        try:
            await scan_member_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("member_reminder_scan_failed_will_retry")
        await asyncio.sleep(settings.MEMBER_REMINDER_SCAN_SECONDS)
