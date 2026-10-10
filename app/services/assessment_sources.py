"""授权只读数据源映射；复用活动台账，缺少可核验来源时明确返回缺项。"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.assessment import AssessmentTask
from app.models.knowledge import KnowledgeDoc
from app.models.meeting import MeetingRecord
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.user import User
from app.rag.retrieval.access import (
    apply_knowledge_access,
    execute_knowledge_query,
    knowledge_filters,
)
from app.rules.assessment import SourceBatch, SourceRecord, fingerprint
from app.services.archive_service import require_archive_policy
from app.services.meeting_service import minutes_missing
from app.services.study_materials import visible_sources
from app.services.study_service import StudyService

SourceProvider = Callable[[AsyncSession, User, dict[str, Any], set[str]], Awaitable[SourceBatch]]
_providers: dict[str, SourceProvider] = {}


def register_assessment_source(source: str, provider: SourceProvider) -> None:
    """上游业务在启动时注册读适配器；不暴露客户端来源注入接口。"""
    if source not in {"meetings", "studies"}:
        raise ValueError("仅会议/学习扩展源可注册适配器")
    _providers[source] = provider


def document_version(document: KnowledgeDoc) -> str:
    """内容版本及影响可见性/时效的元数据均进入佐证版本摘要。"""
    return fingerprint(
        {
            "id": document.doc_id,
            "revision": (document.doc_metadata or {}).get("content_revision", 1),
            "updated_at": document.updated_at,
            "metadata": document.doc_metadata,
            "visibility": document.visibility,
            "security_level": document.security_level,
            "effective_date": document.effective_date,
            "expiration_date": document.expiration_date,
            "status": document.status,
            "is_deleted": document.is_deleted,
        }
    )


async def authorized_documents(
    db: AsyncSession,
    user: User,
    doc_ids: list[str] | None = None,
    *,
    org_unit_id: str | None = None,
) -> list[KnowledgeDoc]:
    """复用知识库权限，读取失效文档以显示状态但仍禁止涉密/越权文档。"""
    filters = knowledge_filters(user, include_expired=True)
    filters["include_future"] = True
    statement = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False)
    if org_unit_id:
        ancestors, current = [], org_unit_id
        while current and current not in ancestors:
            org = (
                await db.execute(
                    select(OrgUnit).where(
                        OrgUnit.id == current,
                        OrgUnit.tenant_id == str(user.tenant_id),
                        OrgUnit.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                break
            ancestors.append(str(org.id))
            current = org.parent_id
        statement = statement.where(
            or_(
                KnowledgeDoc.visibility.in_(["public", "school"]),
                KnowledgeDoc.doc_metadata["org_unit_id"].as_string().in_(ancestors),
            )
        )
    if doc_ids is not None:
        statement = statement.where(KnowledgeDoc.doc_id.in_(doc_ids))
    return list(
        (await execute_knowledge_query(db, statement.order_by(KnowledgeDoc.doc_id))).scalars().all()
    )


async def load_source(
    db: AsyncSession, user: User, rule: dict[str, Any], org_ids: set[str]
) -> SourceBatch:
    """原生源直接复用台账；上游适配器输出仍由计算层强制隔离与去重。"""
    source = rule["source"]
    options = rule["source_options"]
    start, end = date.fromisoformat(rule["period_start"]), date.fromisoformat(rule["period_end"])
    if source in _providers:
        return await _providers[source](db, user, rule, org_ids)
    if source in {"meetings", "studies"}:
        return await activity_source(db, user, rule, org_ids)
    if source == "organizations":
        rows = list(
            (
                await db.execute(
                    select(OrgUnit).where(
                        OrgUnit.tenant_id == str(user.tenant_id),
                        OrgUnit.id.in_(org_ids),
                        OrgUnit.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        if options["org_types"]:
            rows = [row for row in rows if row.org_type in options["org_types"]]
        records = tuple(
            SourceRecord(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                org_unit_id=str(row.id),
                occurred_on=min(date.today(), end),
                version=fingerprint(
                    {
                        "id": row.id,
                        "type": row.org_type,
                        "parent": row.parent_id,
                        "updated": row.updated_at,
                    }
                ),
                facts=(("org_type", row.org_type), ("period_basis", "当前组织快照")),
            )
            for row in rows
        )
        historical = end < date.today()
        return SourceBatch(
            records,
            bool(records) and not historical,
            ("组织历史尚未接入，不能重建历史年度组织归属",) if historical else (),
        )
    if source in {"members", "member_materials"}:
        statement = select(MemberProfile).where(
            MemberProfile.tenant_id == str(user.tenant_id),
            MemberProfile.org_unit_id.in_(org_ids),
            MemberProfile.is_deleted.is_(False),
            MemberProfile.is_active.is_(True),
            MemberProfile.stage_joined_on >= start,
            MemberProfile.stage_joined_on <= min(end, date.today()),
        )
        if options["stages"]:
            # 前端沿用 formal；现有人员阶段枚举在数据库中保存为 member。
            stages = ["member" if stage == "formal" else stage for stage in options["stages"]]
            statement = statement.where(MemberProfile.current_stage.in_(stages))
        rows = list((await db.execute(statement.order_by(MemberProfile.id))).scalars().all())
        records = tuple(
            SourceRecord(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                org_unit_id=str(row.org_unit_id),
                occurred_on=row.stage_joined_on,
                version=fingerprint(
                    {
                        "id": row.id,
                        "org": row.org_unit_id,
                        "stage": row.current_stage,
                        "date": row.stage_joined_on,
                        "materials": sorted(set(row.materials or [])),
                        "updated": row.updated_at,
                    }
                ),
                material_complete=None,
                facts=(
                    ("stage", row.current_stage),
                    ("period_basis", "当前阶段进入日期；非完整发展历史"),
                ),
            )
            for row in rows
        )
        missing = []
        if not rows:
            missing.append("暂无人员记录，尚不能确认真实零值")
        if end < date.today():
            missing.append("人员组织转接/阶段历史尚未接入，历史年度口径待核验")
        if source == "member_materials":
            missing.append("现有材料仅登记名称，文件及审核证据待接入")
        return SourceBatch(records, bool(rows) and not missing, tuple(missing))
    if source == "documents":
        rows = await authorized_documents(db, user, options["document_ids"] or None)
        rows = [
            row
            for row in rows
            if start <= row.effective_date <= min(end, date.today())
            and row.status == "effective"
            and (row.expiration_date is None or row.expiration_date >= date.today())
        ]
        # 校内制度归集只统计选择的组织及其祖先范围；公共政策可作佐证但不是校内制度。
        rows = [
            row
            for row in rows
            if str(row.tenant_id) == str(user.tenant_id)
            and (
                row.visibility in {"school", "public"}
                or (row.doc_metadata or {}).get("org_unit_id") in org_ids
            )
        ]
        records = tuple(
            SourceRecord(
                id=row.doc_id,
                tenant_id=str(user.tenant_id),
                org_unit_id=rule["org_unit_id"],
                occurred_on=row.effective_date,
                version=document_version(row),
                facts=(
                    ("title", row.title),
                    ("content_revision", str((row.doc_metadata or {}).get("content_revision", 1))),
                ),
            )
            for row in rows
        )
        return SourceBatch(
            records, bool(rows), () if rows else ("暂无可授权归集的有效制度文件，不能确认真实零值",)
        )
    return SourceBatch(missing=("人工特色项尚未提交",))


async def authorized_historical_sources(
    db: AsyncSession, user: User, references: list[dict[str, Any]], org_ids: set[str]
) -> set[tuple[str, str]]:
    """按原来源独立核对当前访问权，不用新指标口径代替历史资料授权。"""
    permitted: set[tuple[str, str]] = set()
    models = {
        "organizations": OrgUnit,
        "members": MemberProfile,
        "member_materials": MemberProfile,
        "manual": AssessmentTask,
        "meetings": MeetingRecord,
        "studies": MeetingRecord,
    }
    for source in sorted({item["source"] for item in references}):
        selected = [
            item
            for item in references
            if item["source"] == source and item["org_unit_id"] in org_ids
        ]
        ids = {item["record_id"] for item in selected}
        if not ids:
            continue
        if source == "documents":
            docs = await authorized_documents(db, user, sorted(ids))
            permitted.update(
                (source, doc.doc_id)
                for doc in docs
                if str(doc.tenant_id) == str(user.tenant_id)
                and (
                    doc.visibility in {"school", "public"}
                    or (doc.doc_metadata or {}).get("org_unit_id") in org_ids
                )
            )
            continue
        model = models.get(source)
        if model is None:
            continue
        statement = select(model).where(
            model.id.in_(ids),
            model.tenant_id == str(user.tenant_id),
            model.is_deleted.is_(False),
            model.id.in_(org_ids) if source == "organizations" else model.org_unit_id.in_(org_ids),
        )
        rows = list((await db.execute(statement)).scalars().all())
        study_service = None
        if source == "studies":
            if not has_permission(user.role, Permission.STUDY_QUERY):
                continue
            study_service = await StudyService(db, user).initialize()
        for row in rows:
            if source in {"meetings", "studies"}:
                if (row.activity_type == "center_group") != (source == "studies"):
                    continue
                if study_service:
                    if row.org_unit_id not in study_service.org_ids:
                        continue
                    restricted = (await study_service.activity_data(row))["restricted"]
                else:
                    _, _, restricted = await visible_sources(
                        db, user, row.org_unit_id, row.sources or []
                    )
                if restricted:
                    continue
                if row.archived_at:
                    try:
                        await require_archive_policy(db, str(user.tenant_id))
                    except HTTPException:
                        continue
            permitted.add((source, str(row.id)))
    return permitted


async def activity_source(
    db: AsyncSession, user: User, rule: dict[str, Any], org_ids: set[str]
) -> SourceBatch:
    """复用上游授权活动读取，先限定实际日期，再检查来源及材料状态。"""
    records, missing = [], []
    study_service = None
    if rule["source"] == "studies":
        if not has_permission(user.role, Permission.STUDY_QUERY):
            return SourceBatch(missing=("当前账号无中心组学习数据权限",))
        study_service = await StudyService(db, user).initialize()
        org_ids = org_ids.intersection(study_service.org_ids)
    rows = list(
        (
            await db.execute(
                select(MeetingRecord)
                .where(
                    MeetingRecord.tenant_id == str(user.tenant_id),
                    MeetingRecord.org_unit_id.in_(org_ids),
                    MeetingRecord.is_deleted.is_(False),
                    (
                        MeetingRecord.activity_type == "center_group"
                        if study_service
                        else MeetingRecord.activity_type != "center_group"
                    ),
                    MeetingRecord.held_on >= date.fromisoformat(rule["period_start"]),
                    MeetingRecord.held_on
                    <= min(date.fromisoformat(rule["period_end"]), date.today()),
                )
                .order_by(MeetingRecord.id)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if study_service:
            activity = await study_service.activity_data(row)
            sources, warnings, restricted = (
                activity["sources"],
                activity["missing"],
                activity["restricted"],
            )
        else:
            sources, warnings, restricted = await visible_sources(
                db, user, row.org_unit_id, row.sources or []
            )
        if row.archived_at:
            try:
                await require_archive_policy(db, str(user.tenant_id))
            except HTTPException:
                missing.append("活动电子归档确认已撤销或待补")
                continue
        if restricted:
            missing.append("活动佐证无权限或已删除，未计入统计")
            continue
        missing.extend(warnings)
        people = row.participants or []
        if any(
            not isinstance(person, dict) or not person.get("participant_id") for person in people
        ):
            missing.append("活动参加记录缺少稳定人员编号，须核验")
            continue
        records.append(
            SourceRecord(
                id=str(row.id),
                tenant_id=str(row.tenant_id),
                org_unit_id=str(row.org_unit_id),
                occurred_on=row.held_on,
                status=row.review_status,
                version=fingerprint(
                    {
                        "revision": row.revision,
                        "updated": row.updated_at,
                        "participants": people,
                        "sources": sources,
                    }
                ),
                participants=tuple(
                    sorted(
                        person["participant_id"]
                        for person in people
                        if person.get("attended") is True
                    )
                ),
                expected_participants=tuple(sorted(person["participant_id"] for person in people)),
                material_complete=not minutes_missing(row),
                facts=(("activity_type", row.activity_type), ("revision", str(row.revision))),
            )
        )
    if not records:
        missing.append("暂无可核验的已登记活动，不能将缺少数据当作零次完成")
    return SourceBatch(tuple(records), bool(records), tuple(sorted(set(missing))))
