"""问答的“本人资料”上下文。

只读取当前登录账号自己的档案、基本信息采集表和个人提交材料，作为理解本人
具体情况的补充材料；它不进入制度检索、不占引用编号，也不能被当作政策依据。

隐私边界：
- 只按租户 + 当前用户 + 本人档案读取，不读取其他党员资料；
- 不把身份证号、手机号等个人标识送入模型，正文统一脱敏；
- 敏感级、涉密级个人材料不参与问答，并在回答中说明；
- 只保留来源元数据用于展示和审计，不把正文写入问答历史。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.desensitization import mask_email, mask_text
from app.llm.base import DataLevel
from app.models.education import EducationEnrollment, EducationOffering
from app.models.meeting import MeetingRecord
from app.models.member import (
    MemberCultivation,
    MemberInfoCollection,
    MemberMaterial,
    MemberProcedure,
    MemberProfile,
    MemberReminder,
    MemberStageHistory,
    MemberTraining,
)
from app.models.user import User
from app.rules.member_stages import STAGE_LABELS, MemberStage

MAX_PERSONAL_MATERIALS = 8
MAX_PERSONAL_CHARS = 7000
MAX_MATERIAL_CHARS = 1800
MAX_HISTORY_ROWS = 5
MAX_PROCEDURE_ROWS = 12
MAX_MATERIAL_ROWS = 20

#: 只把不会暴露第三人评价和组织结论原文的程序类型放进问答上下文。
_SAFE_PROCEDURE_LABELS = {
    "contact": "培养联系人",
    "introducer": "入党介绍人",
    "publicity": "公示",
    "application_form": "入党志愿书",
    "higher_record": "再上一级备案",
    "party_group": "编入党支部和党小组",
    "secondary_review": "二级党组织审议",
}
_REMINDER_LABELS = {
    "higher_record": "再上一级党委组织部门备案",
    "party_group": "编入党支部和党小组",
    "oath": "入党宣誓",
    "probationary_expiration": "预备期到期",
    "probationary_expiration_advance": "预备期临近",
    "material_submission": "材料提交",
    "material_submission_advance": "材料提交临近",
    "training_period": "培养期",
    "training_period_advance": "培养期临近",
    "meeting_discussion": "会议讨论",
    "meeting_discussion_advance": "会议讨论临近",
}
_MATERIAL_STATUS_LABELS = {
    "approved": "已核验通过",
    "pending": "待核验",
    "rejected": "已退回",
}
_PROCEDURE_STATUS_LABELS = {
    "assigned": "已登记",
    "confirmed": "已确认",
    "completed": "已完成",
    "submitted": "已提交",
    "reviewed": "已审核",
    "recorded": "已备案",
}
_ACTIVITY_LABELS = {
    "branch_member_meeting": "支部大会",
    "branch_committee_meeting": "支委会",
    "party_group_meeting": "党小组会",
    "party_lecture": "党课",
    "organizational_life_meeting": "组织生活会",
    "other": "其他组织生活",
}
_CULTIVATION_LABELS = {
    "theory_test": "理论学习",
    "volunteer_service": "志愿服务",
    "academic": "学业表现",
    "public_review": "群众评议",
    "party_review": "党员评议",
    "other": "其他培养记录",
}

_INFO_LABELS = {
    "gender": "性别",
    "ethnicity": "民族",
    "education_code": "学历代码",
    "join_party_on": "加入党组织日期",
    "full_member_on": "转为正式党员日期",
    "job_code": "工作岗位代码",
    "party_status": "党籍状态",
    "filing_type": "填报类型",
    "relation_transfer": "是否转接组织关系",
    "transfer_branch": "转入组织关系支部",
    "lost_contact": "是否失联党员",
    "floating": "是否流动党员",
    "floating_province": "外出流向省份",
    "floating_city": "外出流向城市",
    "floating_county": "外出流向县区",
}
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_TRUE_FALSE = {True: "是", False: "否"}
_PARTY_STATUS = {"normal": "正常", "suspended": "停止党籍"}
_FILING_TYPE = {"new": "当年新发展党员", "supplement": "往年党员补录"}


@dataclass(frozen=True)
class PersonalSource:
    id: str
    kind: str
    title: str
    material_type: str = ""
    occurred_on: str = ""
    version: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "material_type": self.material_type,
            "occurred_on": self.occurred_on,
            "version": self.version,
        }


@dataclass
class PersonalContext:
    text: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_level: DataLevel = DataLevel.INTERNAL
    has_profile: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip())


def _value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _TRUE_FALSE[value]
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text


def _stage_label(value: str | None) -> str:
    if not value:
        return "未登记"
    try:
        return STAGE_LABELS.get(MemberStage(value), value)
    except ValueError:
        return value


def _append(lines: list[str], label: str, value: Any) -> None:
    text = _value(value)
    if text:
        lines.append(f"{label}：{text}")


async def build_personal_context(
    db: AsyncSession,
    user: User,
    *,
    max_materials: int = MAX_PERSONAL_MATERIALS,
    max_chars: int = MAX_PERSONAL_CHARS,
) -> PersonalContext:
    """组装当前账号本人的资料块；没有本人档案时返回空上下文。"""
    profile = (
        await db.execute(
            select(MemberProfile)
            .where(
                MemberProfile.tenant_id == str(user.tenant_id),
                MemberProfile.user_id == str(user.id),
                MemberProfile.is_deleted.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if profile is None:
        return PersonalContext(has_profile=False, data_level=DataLevel.PUBLIC)

    lines = ["[本人档案]"]
    _append(lines, "姓名", profile.name)
    _append(lines, "所在组织", profile.org_name)
    _append(lines, "当前阶段", _stage_label(profile.current_stage))
    _append(lines, "进入当前阶段日期", profile.stage_joined_on)
    sources = [
        PersonalSource(
            id=str(profile.id),
            kind="profile",
            title="本人档案",
        ).as_dict()
    ]

    collection = (
        await db.execute(
            select(MemberInfoCollection)
            .where(
                MemberInfoCollection.tenant_id == str(user.tenant_id),
                MemberInfoCollection.profile_id == str(profile.id),
                MemberInfoCollection.is_deleted.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if collection is not None:
        payload = collection.payload or {}
        info_lines: list[str] = []
        for key in (
            "gender",
            "ethnicity",
            "education_code",
            "join_party_on",
            "full_member_on",
            "job_code",
            "party_status",
            "filing_type",
            "relation_transfer",
            "transfer_branch",
            "lost_contact",
            "floating",
            "floating_province",
            "floating_city",
            "floating_county",
        ):
            value = payload.get(key)
            if key == "gender":
                value = {"male": "男", "female": "女"}.get(value, value)
            elif key == "party_status":
                value = _PARTY_STATUS.get(value, value)
            elif key == "filing_type":
                value = _FILING_TYPE.get(value, value)
            _append(info_lines, _INFO_LABELS[key], value)
        if info_lines:
            lines.extend(["", f"[本人基本信息采集表 · 第{collection.version}版]"])
            lines.extend(info_lines)
        sources.append(
            PersonalSource(
                id=str(collection.id),
                kind="info_collection",
                title="本人基本信息采集表",
                version=int(collection.version or 0),
            ).as_dict()
        )

    history = (
        (
            await db.execute(
                select(MemberStageHistory)
                .where(
                    MemberStageHistory.tenant_id == str(user.tenant_id),
                    MemberStageHistory.profile_id == str(profile.id),
                    MemberStageHistory.is_deleted.is_(False),
                )
                .order_by(MemberStageHistory.decision_date.desc(), MemberStageHistory.id.desc())
                .limit(MAX_HISTORY_ROWS)
            )
        )
        .scalars()
        .all()
    )
    if history:
        lines.extend(["", "[本人阶段流转]"])
        for row in history:
            lines.append(
                f"{_value(row.decision_date)}："
                f"{_stage_label(row.from_stage)} → {_stage_label(row.to_stage)}"
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:history",
                kind="stage_history",
                title="本人阶段流转记录",
            ).as_dict()
        )

    procedures = (
        (
            await db.execute(
                select(MemberProcedure)
                .where(
                    MemberProcedure.tenant_id == str(user.tenant_id),
                    MemberProcedure.profile_id == str(profile.id),
                    MemberProcedure.is_deleted.is_(False),
                    MemberProcedure.kind.in_(tuple(_SAFE_PROCEDURE_LABELS)),
                )
                .order_by(MemberProcedure.occurred_on.desc(), MemberProcedure.id.desc())
                .limit(MAX_PROCEDURE_ROWS)
            )
        )
        .scalars()
        .all()
    )
    if procedures:
        lines.extend(["", "[本人发展程序记录]"])
        for row in procedures:
            label = _SAFE_PROCEDURE_LABELS.get(row.kind, "发展程序")
            detail = ""
            if row.kind == "publicity":
                detail = f"；{((row.details or {}).get('working_days') or '未登记')} 个工作日"
            elif row.kind == "secondary_review":
                detail = f"；节点：{((row.details or {}).get('node_label') or '未登记')}"
            status = _PROCEDURE_STATUS_LABELS.get(row.status, row.status or "待核对")
            lines.append(f"{_value(row.occurred_on)}：{label}，状态 {status}{detail}")
        sources.append(
            PersonalSource(
                id=f"{profile.id}:procedures",
                kind="procedure",
                title="本人发展程序记录",
            ).as_dict()
        )

    material_rows = (
        (
            await db.execute(
                select(MemberMaterial)
                .where(
                    MemberMaterial.tenant_id == str(user.tenant_id),
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.is_deleted.is_(False),
                )
                .order_by(
                    MemberMaterial.submit_date.desc(),
                    MemberMaterial.created_at.desc(),
                    MemberMaterial.id.desc(),
                )
                .limit(MAX_MATERIAL_ROWS)
            )
        )
        .scalars()
        .all()
    )
    if material_rows:
        lines.extend(["", "[本人材料清单]"])
        for material in material_rows:
            material_name = material.material_type or material.title or "材料"
            status = _MATERIAL_STATUS_LABELS.get(
                material.review_status, material.review_status or "待核验"
            )
            date_value = _value(material.document_date or material.submit_date)
            lines.append(
                f"{material_name}：{status}" + (f"，日期 {date_value}" if date_value else "")
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:materials",
                kind="material_list",
                title="本人材料清单",
            ).as_dict()
        )

    reminders = (
        (
            await db.execute(
                select(MemberReminder)
                .where(
                    MemberReminder.tenant_id == str(user.tenant_id),
                    MemberReminder.profile_id == str(profile.id),
                    MemberReminder.status == "open",
                    MemberReminder.is_deleted.is_(False),
                )
                .order_by(MemberReminder.due_on, MemberReminder.id)
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    if reminders:
        lines.extend(["", "[本人待办提醒]"])
        for reminder in reminders:
            lines.append(
                f"{_REMINDER_LABELS.get(reminder.kind, reminder.kind)}："
                f"应于 {_value(reminder.due_on)} 前办理"
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:reminders",
                kind="reminders",
                title="本人待办提醒",
            ).as_dict()
        )

    trainings = (
        (
            await db.execute(
                select(MemberTraining)
                .where(
                    MemberTraining.tenant_id == str(user.tenant_id),
                    MemberTraining.profile_id == str(profile.id),
                    MemberTraining.is_deleted.is_(False),
                )
                .order_by(MemberTraining.end_on.desc(), MemberTraining.id.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    if trainings:
        lines.extend(["", "[本人集中培训记录]"])
        for training in trainings:
            lines.append(
                f"{_value(training.start_on)} 至 {_value(training.end_on)}："
                f"{training.days or 0} 天 / {training.hours or 0} 学时"
                f"（{training.issuer or '出具单位未登记'}）"
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:trainings",
                kind="trainings",
                title="本人集中培训记录",
            ).as_dict()
        )

    cultivation_rows = (
        (
            await db.execute(
                select(MemberCultivation)
                .where(
                    MemberCultivation.tenant_id == str(user.tenant_id),
                    MemberCultivation.profile_id == str(profile.id),
                    MemberCultivation.is_deleted.is_(False),
                )
                .order_by(MemberCultivation.created_at.desc(), MemberCultivation.id.desc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    if cultivation_rows:
        lines.extend(["", "[本人培养与表现记录]"])
        for row in cultivation_rows:
            label = _CULTIVATION_LABELS.get(row.category, "培养记录")
            score = f"，成绩 {row.score}" if row.score is not None else ""
            period = f"，期间 {row.period}" if row.period else ""
            lines.append(f"{label}{period}{score}")
        sources.append(
            PersonalSource(
                id=f"{profile.id}:cultivation",
                kind="cultivation",
                title="本人培养与表现记录",
            ).as_dict()
        )

    enrollments = (
        await db.execute(
            select(EducationEnrollment, EducationOffering)
            .join(
                EducationOffering,
                EducationOffering.id == EducationEnrollment.offering_id,
            )
            .where(
                EducationEnrollment.tenant_id == str(user.tenant_id),
                EducationEnrollment.user_id == str(user.id),
                EducationEnrollment.is_deleted.is_(False),
                EducationOffering.is_deleted.is_(False),
            )
            .order_by(EducationEnrollment.updated_at.desc(), EducationEnrollment.id.desc())
            .limit(10)
        )
    ).all()
    if enrollments:
        lines.extend(["", "[本人学习记录]"])
        for enrollment, offering in enrollments:
            lines.append(
                f"{offering.title or '未命名课程'}：{enrollment.status or '已报名'}"
                f"，积分 {enrollment.points or 0}"
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:learning",
                kind="learning",
                title="本人学习记录",
            ).as_dict()
        )

    meetings = (
        (
            await db.execute(
                select(MeetingRecord)
                .where(
                    MeetingRecord.tenant_id == str(user.tenant_id),
                    MeetingRecord.org_unit_id == profile.org_unit_id,
                    MeetingRecord.is_deleted.is_(False),
                )
                .order_by(MeetingRecord.held_on.desc(), MeetingRecord.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    attended_meetings = []
    for meeting in meetings:
        participants = meeting.participants or []
        if any(
            isinstance(person, dict)
            and str(person.get("participant_id")) in {str(profile.id), str(user.id)}
            and person.get("attended", True)
            for person in participants
        ):
            attended_meetings.append(meeting)
    if attended_meetings:
        lines.extend(["", "[本人组织生活记录]"])
        for meeting in attended_meetings[:5]:
            lines.append(
                f"{_value(meeting.held_on or meeting.scheduled_on)}："
                f"{_ACTIVITY_LABELS.get(meeting.activity_type, '组织生活')}"
                f"《{meeting.title or '未命名活动'}》，状态 {meeting.review_status or '待核对'}"
            )
        sources.append(
            PersonalSource(
                id=f"{profile.id}:meetings",
                kind="meetings",
                title="本人组织生活记录",
            ).as_dict()
        )

    materials = (
        (
            await db.execute(
                select(MemberMaterial)
                .options(undefer(MemberMaterial.extracted_text))
                .where(
                    MemberMaterial.tenant_id == str(user.tenant_id),
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.user_id == str(user.id),
                    MemberMaterial.is_deleted.is_(False),
                )
                .order_by(MemberMaterial.created_at.desc(), MemberMaterial.id.desc())
                .limit(max_materials * 4)
            )
        )
        .scalars()
        .all()
    )
    warnings: list[str] = []
    included = 0
    used_chars = sum(len(line) + 1 for line in lines)
    for material in materials:
        if included >= max_materials or used_chars >= max_chars:
            break
        try:
            level = DataLevel(material.data_level or "internal")
        except ValueError:
            level = DataLevel.INTERNAL
        title = material.title or material.material_type or "个人材料"
        if level in {DataLevel.SENSITIVE, DataLevel.CLASSIFIED}:
            warnings.append(f"《{title}》按敏感/涉密材料管理，未参与本次问答。")
            continue
        text = str(mask_text(material.extracted_text or "") or "").strip()
        text = _EMAIL.sub(lambda match: str(mask_email(match.group(0))), text)
        if not text:
            continue
        text = text[:MAX_MATERIAL_CHARS]
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        text = text[:remaining]
        lines.extend(
            [
                "",
                f"[个人材料] {material.material_type or title}",
                f"标题：{title}",
                f"版本：{material.file_version or '未登记'}",
                f"日期：{_value(material.document_date) or '未登记'}",
            ]
        )
        if material.description:
            lines.append(f"说明：{mask_text(str(material.description)[:200])}")
        lines.append(f"正文：{text}")
        used_chars = sum(len(line) + 1 for line in lines)
        sources.append(
            PersonalSource(
                id=str(material.id),
                kind="material",
                title=title,
                material_type=material.material_type or "",
                occurred_on=_value(material.document_date),
                version=0,
            ).as_dict()
        )
        included += 1

    # 组织登记的发展材料：只把内部/公开级、已核验的正文作为本人情况参考。
    # 政治审查材料等敏感/涉密材料不会进入这里，也不会送往云端模型。
    development_materials = (
        (
            await db.execute(
                select(MemberMaterial)
                .options(undefer(MemberMaterial.extracted_text))
                .where(
                    MemberMaterial.tenant_id == str(user.tenant_id),
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.is_deleted.is_(False),
                    MemberMaterial.user_id.is_(None),
                    MemberMaterial.submission_key.is_(None),
                    MemberMaterial.review_status == "approved",
                    MemberMaterial.data_level.in_(["public", "internal"]),
                )
                .order_by(MemberMaterial.created_at.desc(), MemberMaterial.id.desc())
                .limit(max_materials * 2)
            )
        )
        .scalars()
        .all()
    )
    for material in development_materials:
        if included >= max_materials or used_chars >= max_chars:
            break
        title = material.title or material.material_type or "发展材料"
        text = str(mask_text(material.extracted_text or "") or "").strip()
        text = _EMAIL.sub(lambda match: str(mask_email(match.group(0))), text)
        if not text:
            continue
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        text = text[: min(MAX_MATERIAL_CHARS, remaining)]
        lines.extend(
            [
                "",
                f"[组织登记材料] {material.material_type or title}",
                f"标题：{title}",
                f"版本：{material.file_version or '未登记'}",
                f"日期：{_value(material.document_date) or '未登记'}",
                f"正文：{text}",
            ]
        )
        used_chars = sum(len(line) + 1 for line in lines)
        sources.append(
            PersonalSource(
                id=str(material.id),
                kind="development_material",
                title=title,
                material_type=material.material_type or "",
                occurred_on=_value(material.document_date),
                version=0,
            ).as_dict()
        )
        included += 1

    return PersonalContext(
        text="\n".join(lines).strip(),
        sources=sources,
        warnings=list(dict.fromkeys(warnings)),
        data_level=DataLevel.INTERNAL,
        has_profile=True,
    )
