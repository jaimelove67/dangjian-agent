"""问答的授权组织范围统计上下文。

只给管理角色提供聚合数字：档案数量、阶段分布、待核验材料、未办结提醒和
近 90 天组织生活记录数量。这里不读取、不拼接其他党员的材料正文，也不返回名单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.models.meeting import MeetingRecord
from app.models.member import MemberMaterial, MemberProfile, MemberReminder
from app.models.user import User, UserRole
from app.services.org_scope import visible_org_units

SCOPE_ROLES = {
    UserRole.SCHOOL_ADMIN,
    UserRole.DEPARTMENT_ADMIN,
    UserRole.BRANCH_SECRETARY,
    UserRole.ORGANIZER,
}
STAGE_LABELS = {
    "applicant": "入党申请人",
    "activist": "入党积极分子",
    "candidate": "发展对象",
    "probationary": "预备党员",
    "member": "正式党员",
    "disqualified": "取消资格",
    "rejected": "退回",
}


@dataclass
class ScopeContext:
    text: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_level: DataLevel = DataLevel.INTERNAL

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip())


async def build_scope_context(
    db: AsyncSession,
    user: User,
) -> ScopeContext:
    """按当前账号授权范围汇总组织数据；普通党员和平台管理员返回空。"""
    if user.role not in SCOPE_ROLES:
        return ScopeContext()
    orgs = await visible_org_units(db, user)
    org_ids = [str(org.id) for org in orgs]
    if not org_ids:
        return ScopeContext()

    tenant_id = str(user.tenant_id)
    profile_conditions = (
        MemberProfile.tenant_id == tenant_id,
        MemberProfile.org_unit_id.in_(org_ids),
        MemberProfile.is_active.is_(True),
        MemberProfile.is_deleted.is_(False),
    )
    total = (await db.scalar(select(func.count(MemberProfile.id)).where(*profile_conditions))) or 0
    stage_rows = (
        await db.execute(
            select(MemberProfile.current_stage, func.count(MemberProfile.id))
            .where(*profile_conditions)
            .group_by(MemberProfile.current_stage)
        )
    ).all()
    stages = "、".join(
        f"{STAGE_LABELS.get(str(stage), str(stage))} {count} 人"
        for stage, count in stage_rows
        if count
    )

    scope_material = func.count(MemberMaterial.id)
    material_conditions = (
        MemberMaterial.tenant_id == tenant_id,
        MemberMaterial.org_unit_id.in_(org_ids),
        MemberMaterial.is_deleted.is_(False),
        MemberMaterial.review_status == "pending",
    )
    pending_materials = (await db.scalar(select(scope_material).where(*material_conditions))) or 0

    reminder_conditions = (
        MemberReminder.tenant_id == tenant_id,
        MemberReminder.org_unit_id.in_(org_ids),
        MemberReminder.is_deleted.is_(False),
        MemberReminder.status == "open",
    )
    open_reminders = (
        await db.scalar(select(func.count(MemberReminder.id)).where(*reminder_conditions))
    ) or 0
    overdue_reminders = (
        await db.scalar(
            select(func.count(MemberReminder.id)).where(
                *reminder_conditions, MemberReminder.due_on < date.today()
            )
        )
    ) or 0

    since = date.today() - timedelta(days=90)
    recent_meetings = (
        await db.scalar(
            select(func.count(MeetingRecord.id)).where(
                MeetingRecord.tenant_id == tenant_id,
                MeetingRecord.org_unit_id.in_(org_ids),
                MeetingRecord.is_deleted.is_(False),
                MeetingRecord.held_on.is_not(None),
                MeetingRecord.held_on >= since,
            )
        )
    ) or 0

    lines = [
        "[当前组织范围统计]",
        f"授权组织：{len(org_ids)} 个",
        f"在册档案：{total} 人" + (f"；阶段分布：{stages}" if stages else ""),
        f"待核验材料：{pending_materials} 份",
        f"未办结提醒：{open_reminders} 条，其中逾期 {overdue_reminders} 条",
        f"近90天组织生活记录：{recent_meetings} 条",
    ]
    return ScopeContext(
        text="\n".join(lines),
        sources=[
            {
                "id": f"{tenant_id}:scope",
                "kind": "organization_scope",
                "title": "当前账号授权范围统计",
            }
        ],
        warnings=["本次回答参考了当前账号授权范围内的组织统计；统计不包含其他党员的个人材料正文。"],
        data_level=DataLevel.INTERNAL,
    )
