"""党员基本信息采集表的校验、范围与流转规则。

采集表是业务记录，不是档案身份变更：姓名、身份证号、出生日期、组织和人员类别
始终从 ``member_profiles`` 读取，采集表只保存脱敏快照。本人提交时只校验本人
填写的字段；支部初核前再校验全部必填项，避免把支部补录责任推给党员本人。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.desensitization import mask_id_card
from app.models.member import MemberInfoCollection, MemberProfile, MemberStageHistory
from app.models.user import User, UserRole
from app.schemas.member_info import (
    InfoCollectionOut,
    InfoCollectionSummary,
    InfoPayload,
    SelfInfoPayload,
)
from app.services.org_scope import visible_org_units

SELF_KEYS = {
    "gender",
    "ethnicity",
    "education_code",
    "mobile",
    "phone_area",
    "phone_number",
    "address",
    "lost_contact",
    "lost_contact_on",
    "floating",
    "floating_province",
    "floating_city",
    "floating_county",
}
BRANCH_KEYS = {
    "join_party_on",
    "full_member_on",
    "job_code",
    "party_status",
    "filing_type",
    "supplement_reason",
    "relation_transfer",
    "transfer_branch",
}
ALL_KEYS = SELF_KEYS | BRANCH_KEYS
STATUS_LABELS = {
    "draft": "草稿",
    "submitted": "待支部初核",
    "branch_approved": "待院系复核",
    "department_approved": "待学校备案",
    "archived": "已备案",
    "returned": "已退回",
}
STAGE_LABELS = {
    "applicant": "入党申请人",
    "activist": "入党积极分子",
    "candidate": "发展对象",
    "probationary": "预备党员",
    "member": "正式党员",
    "rejected": "退回",
}


def now_local() -> datetime:
    """数据库使用无时区时间；统一按 UTC 存储，前端按本地时区展示。"""

    return datetime.now(UTC).replace(tzinfo=None)


def stage_label(stage: str | None) -> str:
    return STAGE_LABELS.get(str(stage or ""), "未登记")


def person_category(stage: str | None) -> str:
    if stage == "probationary":
        return "预备党员"
    if stage == "member":
        return "正式党员"
    return "尚未成为预备党员"


def can_self_fill(profile: MemberProfile) -> bool:
    return profile.current_stage in {"probationary", "member"}


def can_edit_self(collection: MemberInfoCollection | None) -> bool:
    return collection is None or collection.status in {"draft", "returned"}


def can_edit_branch(user: User, collection: MemberInfoCollection) -> bool:
    return (
        user.role in {UserRole.ORGANIZER, UserRole.BRANCH_SECRETARY}
        and collection.status == "submitted"
    )


def can_review(user: User, collection: MemberInfoCollection) -> bool:
    return (
        (user.role == UserRole.BRANCH_SECRETARY and collection.status == "submitted")
        or (
            user.role == UserRole.DEPARTMENT_ADMIN
            and collection.status == "branch_approved"
        )
        or (
            user.role == UserRole.SCHOOL_ADMIN
            and collection.status == "department_approved"
        )
    )


def _date_error(value: date | None, label: str) -> str | None:
    if value is None:
        return f"请填写{label}"
    if value > date.today():
        return f"{label}不能晚于今天"
    return None


def validate_self(payload: SelfInfoPayload | InfoPayload) -> dict[str, str]:
    """校验本人字段；返回字段名到中文提示的映射。"""

    errors: dict[str, str] = {}
    if payload.gender not in {"male", "female"}:
        errors["gender"] = "请选择性别"
    for key, label, minimum, maximum in (
        ("ethnicity", "民族", 1, 30),
        ("education_code", "学历代码", 1, 10),
        ("address", "家庭住址", 2, 200),
    ):
        value = str(getattr(payload, key) or "").strip()
        if not value:
            errors[key] = f"请填写{label}"
        elif len(value) < minimum:
            errors[key] = f"{label}至少填写{minimum}个字"
        elif len(value) > maximum:
            errors[key] = f"{label}不能超过{maximum}个字"

    if payload.education_code and not payload.education_code.isalnum():
        errors["education_code"] = "学历代码只能填写数字或字母"

    mobile = str(payload.mobile or "").strip()
    area = str(payload.phone_area or "").strip()
    number = str(payload.phone_number or "").strip()
    if mobile and not (len(mobile) == 11 and mobile.isdigit() and mobile[0] == "1"):
        errors["mobile"] = "请填写有效的 11 位手机号"
    if area or number:
        if not (3 <= len(area) <= 4 and area.isdigit()):
            errors["phone_area"] = "区号应为 3 至 4 位数字"
        if not (7 <= len(number) <= 8 and number.isdigit()):
            errors["phone_number"] = "固定电话号码应为 7 至 8 位数字"
    if not mobile and not (area and number):
        errors["mobile"] = "手机号或固定电话至少填写一项"

    if payload.lost_contact is None:
        errors["lost_contact"] = "请选择是否失联"
    elif payload.lost_contact:
        message = _date_error(payload.lost_contact_on, "失去联系日期")
        if message:
            errors["lost_contact_on"] = message

    if payload.floating is None:
        errors["floating"] = "请选择是否流动"
    elif payload.floating:
        for key, label in (
            ("floating_province", "外出流向省份"),
            ("floating_city", "外出流向城市"),
            ("floating_county", "外出流向县区"),
        ):
            value = str(getattr(payload, key) or "").strip()
            if not value:
                errors[key] = f"请填写{label}"
            elif len(value) > 50:
                errors[key] = f"{label}不能超过50个字"
    return errors


def validate_complete(
    payload: InfoPayload, profile: MemberProfile
) -> dict[str, str]:
    """支部初核前校验全部字段。"""

    errors = validate_self(payload)
    join_message = _date_error(payload.join_party_on, "加入党组织日期")
    if join_message:
        errors["join_party_on"] = join_message
    if profile.current_stage == "member":
        full_message = _date_error(payload.full_member_on, "转为正式党员日期")
        if full_message:
            errors["full_member_on"] = full_message
    elif payload.full_member_on:
        errors["full_member_on"] = "预备党员不填写转为正式党员日期"

    if (
        payload.join_party_on
        and payload.full_member_on
        and payload.full_member_on < payload.join_party_on
    ):
        errors["full_member_on"] = "转正日期不能早于加入党组织日期"
    if (
        profile.birth_date
        and payload.join_party_on
        and payload.join_party_on < profile.birth_date
    ):
        errors["join_party_on"] = "加入党组织日期不能早于出生日期"

    job = str(payload.job_code or "").strip()
    if not job:
        errors["job_code"] = "请填写工作岗位代码"
    elif not job.isalnum():
        errors["job_code"] = "工作岗位代码只能填写数字或字母"

    if payload.party_status not in {"normal", "suspended"}:
        errors["party_status"] = "请选择党籍状态"
    if payload.filing_type not in {"new", "supplement"}:
        errors["filing_type"] = "请选择填报类型"
    if payload.filing_type == "supplement":
        reason = str(payload.supplement_reason or "").strip()
        if len(reason) < 2:
            errors["supplement_reason"] = "请填写补录原因"
        elif len(reason) > 500:
            errors["supplement_reason"] = "补录原因不能超过500个字"

    if payload.relation_transfer is None:
        errors["relation_transfer"] = "请选择是否转接组织关系"
    elif payload.relation_transfer:
        branch = str(payload.transfer_branch or "").strip()
        if len(branch) < 2:
            errors["transfer_branch"] = "请填写转入组织关系支部全称"
        elif len(branch) > 200:
            errors["transfer_branch"] = "转入支部全称不能超过200个字"
    return errors


def error_message(errors: dict[str, str]) -> str:
    return next(iter(errors.values()), "请检查填写内容")


def merge_payload(
    existing: InfoPayload,
    incoming: InfoPayload | SelfInfoPayload,
    keys: set[str] | None = None,
) -> InfoPayload:
    """只合并调用方有权修改的字段，保留支部已补录内容。"""

    data = existing.model_dump()
    updates = incoming.model_dump()
    for key in keys or ALL_KEYS:
        if key in updates:
            data[key] = updates[key]
    return InfoPayload.model_validate(data)


def history_event(
    action: str,
    user: User,
    status: str,
    at: datetime,
    opinion: str = "",
    version: int | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "actor": user.name or user.username,
        "role": str(user.role.value if hasattr(user.role, "value") else user.role),
        "status": status,
        "opinion": opinion.strip(),
        "at": at.isoformat(),
        **({} if version is None else {"version": version}),
    }


def payload_json(payload: InfoPayload) -> dict[str, Any]:
    return payload.model_dump(mode="json")


def serialize_collection(collection: MemberInfoCollection) -> InfoCollectionOut:
    return InfoCollectionOut(
        id=collection.id,
        profile_id=collection.profile_id,
        member_name=collection.member_name,
        member_stage=collection.member_stage,
        member_stage_label=collection.member_stage_label,
        org_unit_id=collection.org_unit_id,
        org_name=collection.org_name,
        department=collection.department,
        id_card_masked=collection.id_card_masked,
        birth_date=collection.birth_date,
        stage_joined_on=collection.stage_joined_on,
        status=collection.status,
        version=collection.version,
        payload=InfoPayload.model_validate(collection.payload or {}),
        history=list(collection.history or []),
        collector_name=collection.collector_name,
        member_confirmed_at=collection.member_confirmed_at,
        submitted_at=collection.submitted_at,
        branch_reviewed_at=collection.branch_reviewed_at,
        branch_reviewed_by_name=collection.branch_reviewed_by_name,
        branch_opinion=collection.branch_opinion,
        department_reviewed_at=collection.department_reviewed_at,
        department_reviewed_by_name=collection.department_reviewed_by_name,
        department_opinion=collection.department_opinion,
        archived_at=collection.archived_at,
        archived_by_name=collection.archived_by_name,
        returned_at=collection.returned_at,
        returned_by_name=collection.returned_by_name,
        return_reason=collection.return_reason,
        return_stage=collection.return_stage,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def serialize_summary(collection: MemberInfoCollection) -> InfoCollectionSummary:
    return InfoCollectionSummary(
        id=collection.id,
        profile_id=collection.profile_id,
        member_name=collection.member_name,
        member_stage=collection.member_stage,
        member_stage_label=collection.member_stage_label,
        org_unit_id=collection.org_unit_id,
        org_name=collection.org_name,
        department=collection.department,
        status=collection.status,
        version=collection.version,
        submitted_at=collection.submitted_at,
        updated_at=collection.updated_at,
        return_reason=collection.return_reason,
    )


async def own_profile(db: AsyncSession, user: User) -> MemberProfile:
    profile = (
        await db.execute(
            select(MemberProfile).where(
                MemberProfile.tenant_id == str(user.tenant_id),
                MemberProfile.user_id == str(user.id),
                MemberProfile.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(409, "当前账号尚未关联本人档案，请联系组织管理员。")
    return profile


async def own_collection(
    db: AsyncSession, user: User, profile: MemberProfile
) -> MemberInfoCollection | None:
    return (
        await db.execute(
            select(MemberInfoCollection).where(
                MemberInfoCollection.tenant_id == str(user.tenant_id),
                MemberInfoCollection.profile_id == str(profile.id),
                MemberInfoCollection.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


async def load_collection(
    db: AsyncSession, user: User, collection_id: str
) -> MemberInfoCollection:
    collection = (
        await db.execute(
            select(MemberInfoCollection).where(
                MemberInfoCollection.id == collection_id,
                MemberInfoCollection.tenant_id == str(user.tenant_id),
                MemberInfoCollection.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if collection is None:
        raise HTTPException(404, "采集表不存在或不在当前租户范围内。")
    await ensure_scope(db, user, collection)
    return collection


async def visible_org_ids(db: AsyncSession, user: User) -> set[str]:
    orgs = await visible_org_units(db, user)
    return {str(org.id) for org in orgs}


async def ensure_scope(
    db: AsyncSession, user: User, collection: MemberInfoCollection
) -> None:
    if user.role == UserRole.SYSTEM_ADMIN:
        raise HTTPException(403, "平台管理员不办理学校党员业务。")
    ids = await visible_org_ids(db, user)
    if collection.org_unit_id and str(collection.org_unit_id) not in ids:
        raise HTTPException(403, "这份采集表不在当前账号的授权范围内。")
    if not collection.org_unit_id and user.role != UserRole.SCHOOL_ADMIN:
        raise HTTPException(403, "这份采集表缺少组织归属，需由学校管理员核对。")


async def suggested_dates(
    db: AsyncSession, profile: MemberProfile
) -> tuple[date | None, date | None]:
    """从人工阶段流转历史取建议值，不由身份证号推算。"""

    async def latest(to_stage: str) -> date | None:
        value = (
            await db.execute(
                select(MemberStageHistory.decision_date)
                .where(
                    MemberStageHistory.tenant_id == str(profile.tenant_id),
                    MemberStageHistory.profile_id == str(profile.id),
                    MemberStageHistory.to_stage == to_stage,
                )
                .order_by(MemberStageHistory.decision_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return value

    return await latest("probationary"), await latest("member")


def new_collection(
    profile: MemberProfile, user: User, at: datetime | None = None
) -> MemberInfoCollection:
    at = at or now_local()
    return MemberInfoCollection(
        tenant_id=str(user.tenant_id),
        profile_id=str(profile.id),
        user_id=str(profile.user_id) if profile.user_id else None,
        member_name=profile.name,
        member_stage=profile.current_stage,
        member_stage_label=stage_label(profile.current_stage),
        org_unit_id=str(profile.org_unit_id) if profile.org_unit_id else None,
        org_name=profile.org_name,
        department="",
        id_card_masked=mask_id_card(profile.id_card_no) if profile.id_card_no else "",
        birth_date=profile.birth_date,
        stage_joined_on=profile.stage_joined_on,
        status="draft",
        version=0,
        payload=payload_json(InfoPayload()),
        history=[],
        collector_name="",
        member_confirmed_at=None,
        submitted_at=None,
        branch_reviewed_at=None,
        branch_reviewed_by_name="",
        branch_opinion="",
        department_reviewed_at=None,
        department_reviewed_by_name="",
        department_opinion="",
        archived_at=None,
        archived_by_name="",
        returned_at=None,
        returned_by_name="",
        return_reason="",
        return_stage="",
        created_at=at,
        updated_at=at,
    )


def refresh_profile_snapshot(
    collection: MemberInfoCollection, profile: MemberProfile
) -> None:
    collection.member_name = profile.name
    collection.member_stage = profile.current_stage
    collection.member_stage_label = stage_label(profile.current_stage)
    collection.org_name = profile.org_name
    collection.org_unit_id = str(profile.org_unit_id) if profile.org_unit_id else None
    collection.id_card_masked = (
        mask_id_card(profile.id_card_no) if profile.id_card_no else ""
    )
    collection.birth_date = profile.birth_date
    collection.stage_joined_on = profile.stage_joined_on
