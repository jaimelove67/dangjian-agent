"""中心组学习业务闭环；所有数据库读写均带租户及有效组织范围。"""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import ContentRevision, MeetingRecord
from app.models.study import StudyPlan, StudyPlanItem
from app.models.user import User
from app.schemas.study import (
    ActivityUpdate,
    ItemCreate,
    ItemFields,
    ItemUpdate,
    PlanCreate,
    PlanUpdate,
    ReviewRequest,
    RevisionRequest,
)
from app.services.archive_service import require_archive_policy
from app.services.meeting_service import (
    STUDY_NOTICE,
    apply_review,
    extract_minutes,
    minutes_missing,
    reset_review,
    utc_now,
    validate_minutes,
)
from app.services.org_scope import accessible_org_units
from app.services.study_materials import recommend_sources, selected_sources, visible_sources

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "config" / "study_templates.yaml"


def row_data(record: Any) -> dict[str, Any]:
    """版本快照保留真实字段；不保存 SQLAlchemy 内部状态。"""
    return jsonable_encoder(
        {column.key: getattr(record, column.key) for column in record.__table__.columns}
    )


class StudyService:
    """在请求事务内完成学习业务及只追加版本，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []

    async def initialize(self) -> "StudyService":
        """中心组学习仅登记学校/院系党委范围，不能以任意组织编号扩大授权。"""
        self.orgs = [
            org
            for org in await accessible_org_units(self.db, self.user)
            if org.org_type in ("school", "department")
        ]
        self.org_ids = [str(org.id) for org in self.orgs]
        return self

    def _scope(self, model: Any) -> list[Any]:
        return [
            model.tenant_id == self.tenant_id,
            model.is_deleted.is_(False),
            model.org_unit_id.in_(self.org_ids),
        ]

    async def plan(self, plan_id: str, *, lock: bool = False) -> StudyPlan:
        """不可访问的编号统一返回不存在，避免跨组织探测。"""
        stmt = select(StudyPlan).where(*self._scope(StudyPlan), StudyPlan.id == plan_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise HTTPException(404, "学习计划不存在或无权访问")
        return record

    async def activity(self, activity_id: str, *, lock: bool = False) -> MeetingRecord:
        """在当前授权事务内处理学习业务。"""
        stmt = select(MeetingRecord).where(
            *self._scope(MeetingRecord),
            MeetingRecord.id == activity_id,
            MeetingRecord.activity_type == "center_group",
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise HTTPException(404, "学习活动不存在或无权访问")
        if record.archived_at:
            await require_archive_policy(self.db, self.tenant_id)
        return record

    async def items(self, plan: StudyPlan) -> list[StudyPlanItem]:
        """读取当前租户计划的学习条目。"""
        return list(
            (
                await self.db.execute(
                    select(StudyPlanItem)
                    .where(
                        StudyPlanItem.tenant_id == self.tenant_id,
                        StudyPlanItem.plan_id == plan.id,
                        StudyPlanItem.is_deleted.is_(False),
                    )
                    .order_by(StudyPlanItem.scheduled_on, StudyPlanItem.id)
                )
            )
            .scalars()
            .all()
        )

    async def item(self, plan: StudyPlan, item_id: str) -> StudyPlanItem:
        """读取计划内指定学习安排，拒绝跨计划编号。"""
        item = (
            await self.db.execute(
                select(StudyPlanItem).where(
                    StudyPlanItem.id == item_id,
                    StudyPlanItem.plan_id == plan.id,
                    StudyPlanItem.tenant_id == self.tenant_id,
                    StudyPlanItem.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(404, "学习安排不存在")
        return item

    @staticmethod
    def check_revision(record: Any, expected: int) -> None:
        """拒绝覆盖别人已经修订的内容。"""
        if record.revision != expected:
            raise HTTPException(409, "内容已被修订，请刷新并核对当前版本后重试")

    async def _snapshot(self, record: Any) -> dict[str, Any]:
        snapshot = row_data(record)
        if isinstance(record, StudyPlan):
            snapshot["items"] = [row_data(item) for item in await self.items(record)]
        return snapshot

    async def save_revision(
        self, record: Any, resource_type: str, action: str, reason: str, *, initial: bool = False
    ) -> None:
        """保存只追加的完整版本和真实操作人。"""
        if not initial:
            record.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type=resource_type,
                resource_id=str(record.id),
                revision=record.revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=await self._snapshot(record),
            )
        )
        await self.db.flush()

    async def _new_item(self, plan: StudyPlan, body: ItemFields) -> StudyPlanItem:
        if body.scheduled_on.year != plan.year:
            raise HTTPException(422, "计划安排日期必须在计划年度内")
        doc_ids = list(dict.fromkeys(body.source_doc_ids or plan.source_doc_ids))
        item = StudyPlanItem(
            tenant_id=self.tenant_id,
            plan_id=plan.id,
            topic=body.topic,
            scheduled_on=body.scheduled_on,
            responsible=body.responsible,
            source_doc_ids=doc_ids,
            sources=await selected_sources(
                self.db, self.user, plan.org_unit_id, doc_ids, on=body.scheduled_on
            ),
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def create_plan(self, body: PlanCreate) -> StudyPlan:
        """创建年度学习草案并保留初始依据版本。"""
        if body.org_unit_id not in self.org_ids:
            raise HTTPException(403, "请选择权限范围内有效的学校或院系党委")
        # 组织行锁使并发创建同年度计划串行化，数据库唯一约束作为最后保障。
        from app.models.org import OrgUnit

        await self.db.execute(
            select(OrgUnit)
            .where(OrgUnit.id == body.org_unit_id, OrgUnit.tenant_id == self.tenant_id)
            .with_for_update()
        )
        duplicate = await self.db.scalar(
            select(StudyPlan.id).where(
                StudyPlan.tenant_id == self.tenant_id,
                StudyPlan.org_unit_id == body.org_unit_id,
                StudyPlan.year == body.year,
            )
        )
        if duplicate:
            raise HTTPException(409, "该组织已有本年度计划，请修订既有计划")
        ids = list(dict.fromkeys(body.source_doc_ids))
        plan = StudyPlan(
            tenant_id=self.tenant_id,
            org_unit_id=body.org_unit_id,
            year=body.year,
            title=body.title,
            priorities=body.priorities,
            responsible=body.responsible,
            source_doc_ids=ids,
            sources=await selected_sources(self.db, self.user, body.org_unit_id, ids),
        )
        self.db.add(plan)
        await self.db.flush()
        proposed = body.items or [
            ItemFields(
                topic=topic,
                scheduled_on=date(body.year, max(1, 12 * (index + 1) // len(body.priorities)), 1),
                responsible=body.responsible,
                source_doc_ids=ids,
            )
            for index, topic in enumerate(body.priorities)
        ]
        for entry in proposed:
            await self._new_item(plan, entry)
        await self.save_revision(plan, "study_plan", "create", body.reason, initial=True)
        return plan

    async def update_plan(self, plan_id: str, body: PlanUpdate) -> StudyPlan:
        """修订年度重点，保留旧版本并撤销旧审核。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        sources = await selected_sources(self.db, self.user, plan.org_unit_id, body.source_doc_ids)
        plan.title, plan.priorities, plan.responsible = (
            body.title,
            body.priorities,
            body.responsible,
        )
        plan.source_doc_ids, plan.sources = list(dict.fromkeys(body.source_doc_ids)), sources
        # 未开活动的生成草稿依赖年度重点，修订重点后必须重新生成/核对。
        for entry in await self.items(plan):
            if not entry.meeting_record_id:
                entry.agenda = entry.outline = ""
                entry.template_version = None
        reset_review(plan)
        await self.save_revision(plan, "study_plan", "revise", body.reason)
        return plan

    async def add_item(self, plan_id: str, body: ItemCreate) -> StudyPlan:
        """增加学习安排，重新提交年度计划审核。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        if len(await self.items(plan)) >= 60:
            raise HTTPException(422, "年度学习安排不能超过 60 项")
        await self._new_item(plan, body)
        reset_review(plan)
        await self.save_revision(plan, "study_plan", "add_item", body.reason)
        return plan

    async def update_item(self, plan_id: str, item_id: str, body: ItemUpdate) -> StudyPlan:
        """修订学习安排与人工议程提纲，保留活动关联。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        entry = await self.item(plan, item_id)
        if entry.meeting_record_id and (
            entry.topic != body.topic
            or entry.scheduled_on != body.scheduled_on
            or entry.responsible != body.responsible
        ):
            raise HTTPException(409, "已关联活动的主题、安排日期与负责人不能覆盖，请新增后续安排")
        if body.scheduled_on.year != plan.year:
            raise HTTPException(422, "计划安排日期必须在计划年度内")
        sources = await selected_sources(
            self.db, self.user, plan.org_unit_id, body.source_doc_ids, on=body.scheduled_on
        )
        entry.topic, entry.scheduled_on, entry.responsible = (
            body.topic,
            body.scheduled_on,
            body.responsible,
        )
        entry.source_doc_ids, entry.sources = list(dict.fromkeys(body.source_doc_ids)), sources
        entry.agenda, entry.outline = body.agenda, body.outline
        if body.agenda or body.outline:
            entry.template_version = (entry.template_version or "manual") + (
                "" if (entry.template_version or "").endswith("+manual") else "+manual"
            )
        else:
            entry.template_version = None
        reset_review(plan)
        await self.save_revision(plan, "study_plan", "revise_item", body.reason)
        return plan

    async def recommendations(
        self, plan_id: str, item_id: str, query: str | None = None
    ) -> dict[str, Any]:
        """从授权知识库推荐本期材料，不补写虚构文件。"""
        plan = await self.plan(plan_id)
        entry = await self.item(plan, item_id)
        sources = await recommend_sources(
            self.db,
            self.user,
            plan.org_unit_id,
            [entry.topic, *plan.priorities],
            on=entry.scheduled_on,
            query=query,
        )
        return {
            "topic": entry.topic,
            "sources": sources,
            "missing": [] if sources else ["没有匹配的有效授权资料，政策依据待补"],
            "notice": STUDY_NOTICE,
        }

    async def generate_drafts(self, plan_id: str, item_id: str, body: RevisionRequest) -> StudyPlan:
        """按独立版本模板生成有真实摘录的议程与发言提纲。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        entry = await self.item(plan, item_id)
        if entry.meeting_record_id:
            raise HTTPException(409, "该安排已有活动记录，不能覆盖既有议程依据")
        _, _, restricted = await visible_sources(self.db, self.user, plan.org_unit_id, plan.sources)
        if restricted:
            raise HTTPException(403, "年度依据资料权限已变化，请修订依据后重新生成")
        entry.sources = await selected_sources(
            self.db, self.user, plan.org_unit_id, entry.source_doc_ids, on=entry.scheduled_on
        )
        template = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
        materials = (
            "\n".join(
                f"[{index}] {source['title']}（{source['doc_id']}，"
                f"版本{source['content_revision']}，生效{source['effective_date']}）："
                f"{source['excerpt'] or '原文摘录待补'}"
                for index, source in enumerate(entry.sources, 1)
            )
            or "政策依据待补；资料不足时不生成政策表述。"
        )
        values = {
            "topic": entry.topic,
            "scheduled_on": entry.scheduled_on.isoformat(),
            "responsible": entry.responsible,
            "priorities": "；".join(plan.priorities),
            "materials": materials,
        }
        entry.agenda = template["agenda"].format(**values) + "\n" + STUDY_NOTICE
        entry.outline = template["outline"].format(**values) + "\n" + STUDY_NOTICE
        entry.template_version = str(template["version"])
        reset_review(plan)
        await self.save_revision(plan, "study_plan", "generate_drafts", body.reason)
        return plan

    async def _require_current_sources(
        self, org_id: str, saved: list[dict[str, Any]], *, on: date | None = None
    ) -> None:
        if not saved or any(not source.get("excerpt") for source in saved):
            raise HTTPException(422, "政策依据或原文摘录待补，暂不能提交正式审核")
        current = await selected_sources(
            self.db, self.user, org_id, [source["doc_id"] for source in saved], on=on
        )
        if any(
            a["content_revision"] != b["content_revision"] or a["sha256"] != b["sha256"]
            for a, b in zip(saved, current)
        ):
            raise HTTPException(409, "依据文件已更新，请重新选择资料并修订内容后送审")

    async def submit_plan(self, plan_id: str, body: RevisionRequest) -> StudyPlan:
        """提交当前计划版本，由另一位组织人员审核。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        if plan.review_status not in ("draft", "rejected"):
            raise HTTPException(409, "请先修订草案再提交审核")
        await self._validate_plan(plan)
        plan.review_status, plan.submitted_by = "pending", str(self.user.id)
        await self.save_revision(plan, "study_plan", "submit", body.reason)
        return plan

    async def _validate_plan(self, plan: StudyPlan) -> None:
        await self._require_current_sources(plan.org_unit_id, plan.sources)
        entries = await self.items(plan)
        if not entries:
            raise HTTPException(422, "学习安排待补")
        for entry in entries:
            await self._require_current_sources(
                plan.org_unit_id, entry.sources, on=entry.scheduled_on
            )

    async def review_plan(self, plan_id: str, body: ReviewRequest) -> StudyPlan:
        """人工通过或退回已提交的计划版本。"""
        plan = await self.plan(plan_id, lock=True)
        self.check_revision(plan, body.expected_revision)
        if body.decision == "approved":
            await self._validate_plan(plan)
        apply_review(plan, str(self.user.id), body.decision, body.reason)
        await self.save_revision(plan, "study_plan", "review", body.reason)
        return plan

    async def start_activity(
        self, plan_id: str, item_id: str, body: RevisionRequest
    ) -> MeetingRecord:
        """为已审核安排登记稳定且可复用的共用活动记录。"""
        plan = await self.plan(plan_id, lock=True)
        entry = await self.item(plan, item_id)
        # 重试返回稳定活动编号，即使第一次调用已推进计划版本也不会新增流水。
        if entry.meeting_record_id:
            return await self.activity(entry.meeting_record_id)
        self.check_revision(plan, body.expected_revision)
        if plan.review_status != "approved":
            raise HTTPException(409, "年度学习安排须经人工审核通过后登记活动")
        await self._require_current_sources(plan.org_unit_id, plan.sources)
        await self._require_current_sources(plan.org_unit_id, entry.sources, on=entry.scheduled_on)
        combined_sources = {source["doc_id"]: source for source in [*plan.sources, *entry.sources]}
        record = MeetingRecord(
            tenant_id=self.tenant_id,
            org_unit_id=plan.org_unit_id,
            activity_type="center_group",
            title=entry.topic,
            scheduled_on=entry.scheduled_on,
            source_doc_ids=list(combined_sources),
            sources=list(combined_sources.values()),
            context={
                "plan_id": str(plan.id),
                "plan_revision": plan.revision,
                "item_id": str(entry.id),
                "plan_year": plan.year,
                "agenda": entry.agenda,
                "outline": entry.outline,
                "template_version": entry.template_version,
            },
        )
        self.db.add(record)
        await self.db.flush()
        entry.meeting_record_id = record.id
        await self.save_revision(record, "meeting", "create", body.reason, initial=True)
        # 仅执行进度发生变化，不改变已经审核的学习内容与计划修订版本。
        return record

    async def update_activity(self, activity_id: str, body: ActivityUpdate) -> MeetingRecord:
        """登记原始文本与参学情况，修改后重新审核纪要。"""
        record = await self.activity(activity_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档活动不能覆盖，请保留正式版本")
        if body.held_on and body.held_on.year < record.context["plan_year"]:
            raise HTTPException(422, "实际学习日期不能早于年度计划开始日期")
        minutes = body.minutes.model_dump() if body.minutes is not None else {}
        validate_minutes(body.transcript, minutes)
        record.held_on, record.host = body.held_on, body.host
        record.participants = [person.model_dump() for person in body.participants]
        record.transcript, record.minutes = body.transcript, minutes
        if body.source_doc_ids is not None:
            plan = await self.plan(record.context["plan_id"])
            await self._require_current_sources(plan.org_unit_id, plan.sources)
            chosen = await selected_sources(
                self.db,
                self.user,
                record.org_unit_id,
                body.source_doc_ids,
                on=body.held_on or record.scheduled_on,
            )
            combined = {source["doc_id"]: source for source in [*plan.sources, *chosen]}
            record.sources, record.source_doc_ids = list(combined.values()), list(combined)
            entry = await self.item(plan, record.context["item_id"])
            record.context = {
                **record.context,
                "plan_revision": plan.revision,
                "agenda": entry.agenda,
                "outline": entry.outline,
                "template_version": entry.template_version,
            }
        reset_review(record)
        await self.save_revision(record, "meeting", "revise", body.reason)
        return record

    async def generate_minutes(self, activity_id: str, body: RevisionRequest) -> MeetingRecord:
        """仅提取原文中明确标注的学习要点、共识和要求。"""
        record = await self.activity(activity_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档纪要不能覆盖")
        if not record.transcript:
            raise HTTPException(422, "原始学习文本待补")
        record.minutes = extract_minutes(record.transcript)
        reset_review(record)
        await self.save_revision(record, "meeting", "generate_minutes", body.reason)
        return record

    async def _validate_activity(self, record: MeetingRecord) -> None:
        missing = minutes_missing(record)
        if missing:
            raise HTTPException(422, "；".join(missing))
        validate_minutes(record.transcript, record.minutes)
        plan = await self.plan(record.context["plan_id"])
        if plan.review_status != "approved":
            raise HTTPException(409, "关联年度计划修订后尚未重新审核")
        await self._require_current_sources(plan.org_unit_id, plan.sources)
        await self._require_current_sources(record.org_unit_id, record.sources, on=record.held_on)

    async def submit_activity(self, activity_id: str, body: RevisionRequest) -> MeetingRecord:
        """核查原文定位、参学、日期及依据后提交纪要。"""
        record = await self.activity(activity_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at or record.review_status not in ("draft", "rejected"):
            raise HTTPException(409, "当前纪要不能再次提交，请先修订")
        await self._validate_activity(record)
        record.review_status, record.submitted_by = "pending", str(self.user.id)
        await self.save_revision(record, "meeting", "submit", body.reason)
        return record

    async def review_activity(self, activity_id: str, body: ReviewRequest) -> MeetingRecord:
        """人工审核当前纪要版本，不允许自审。"""
        record = await self.activity(activity_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档纪要不能重复审核")
        if body.decision == "approved":
            await self._validate_activity(record)
        apply_review(record, str(self.user.id), body.decision, body.reason)
        await self.save_revision(record, "meeting", "review", body.reason)
        return record

    async def archive_activity(self, activity_id: str, body: RevisionRequest) -> MeetingRecord:
        """学校确认电子效力后归档人工审核通过的记录。"""
        record = await self.activity(activity_id, lock=True)
        policy = await require_archive_policy(self.db, self.tenant_id)
        if record.archived_at:
            return record
        self.check_revision(record, body.expected_revision)
        if record.review_status != "approved" or not record.reviewed_by:
            raise HTTPException(409, "纪要须先经人工审核通过")
        missing = minutes_missing(record)
        if missing:
            raise HTTPException(422, "；".join(missing))
        _, _, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, record.sources
        )
        if restricted:
            raise HTTPException(403, "关联学习资料当前不可访问，不能归档")
        record.archived_at, record.archive_policy_version = utc_now(), policy["revision"]
        await self.save_revision(record, "meeting", "archive", body.reason)
        return record

    async def plan_data(self, plan: StudyPlan) -> dict[str, Any]:
        """生成经当前资料权限复核的计划响应。"""
        data = row_data(plan)
        data["sources"], warnings, restricted = await visible_sources(
            self.db, self.user, plan.org_unit_id, plan.sources
        )
        entries = []
        for entry in await self.items(plan):
            item = row_data(entry)
            item["sources"], item_warnings, item_restricted = await visible_sources(
                self.db, self.user, plan.org_unit_id, entry.sources
            )
            item["missing"] = item_warnings
            item["execution_status"] = "planned"
            if entry.meeting_record_id:
                record = (
                    await self.db.execute(
                        select(MeetingRecord).where(
                            MeetingRecord.id == entry.meeting_record_id, *self._scope(MeetingRecord)
                        )
                    )
                ).scalar_one_or_none()
                if record:
                    item["execution_status"] = (
                        "archived"
                        if record.archived_at
                        else (
                            "completed"
                            if record.review_status == "approved"
                            else (
                                "pending"
                                if record.review_status == "pending"
                                else ("held" if record.held_on else "planned")
                            )
                        )
                    )
            if item_restricted:
                item.update(
                    topic="关联资料权限变更，内容待复核",
                    agenda="",
                    outline="",
                    source_doc_ids=[],
                    sources=[],
                )
            restricted |= item_restricted
            entries.append(item)
        data.update(items=entries, notice=STUDY_NOTICE, missing=warnings, restricted=restricted)
        if restricted:
            data.update(
                title="关联资料权限变更，内容待复核",
                priorities=[],
                source_doc_ids=[],
                sources=[],
                review_comment="",
            )
            for item in data["items"]:
                item.update(
                    topic="关联资料权限变更，内容待复核",
                    agenda="",
                    outline="",
                    source_doc_ids=[],
                    sources=[],
                )
        return data

    async def activity_data(self, record: MeetingRecord) -> dict[str, Any]:
        """生成当前授权的活动响应，缺项明确待补。"""
        data = row_data(record)
        data["sources"], warnings, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, record.sources
        )
        data.update(
            notice=STUDY_NOTICE,
            missing=minutes_missing(record) + warnings,
            restricted=restricted,
            execution_status=(
                "archived"
                if record.archived_at
                else ("completed" if record.review_status == "approved" else record.review_status)
            ),
        )
        if restricted:
            data.update(
                title="关联资料权限变更，内容待复核",
                transcript="",
                minutes={},
                sources=[],
                source_doc_ids=[],
                participants=[],
                review_comment="",
                context={
                    key: record.context.get(key)
                    for key in ("plan_id", "item_id", "plan_revision", "plan_year")
                },
            )
        return data

    async def list_plans(
        self,
        *,
        year: int | None,
        org_unit_id: str | None,
        start: date | None,
        end: date | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """按授权党委和时间条件分页读取年度计划。"""
        if start and end and start > end:
            raise HTTPException(422, "查询开始日期不能晚于结束日期")
        conditions = self._scope(StudyPlan)
        if year:
            conditions.append(StudyPlan.year == year)
        if org_unit_id:
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "无权查询该组织")
            conditions.append(StudyPlan.org_unit_id == org_unit_id)
        if start or end:
            item_stmt = select(StudyPlanItem.plan_id).where(
                StudyPlanItem.tenant_id == self.tenant_id, StudyPlanItem.is_deleted.is_(False)
            )
            if start:
                item_stmt = item_stmt.where(StudyPlanItem.scheduled_on >= start)
            if end:
                item_stmt = item_stmt.where(StudyPlanItem.scheduled_on <= end)
            conditions.append(StudyPlan.id.in_(item_stmt))
        total = await self.db.scalar(select(func.count(StudyPlan.id)).where(*conditions))
        plans = (
            (
                await self.db.execute(
                    select(StudyPlan)
                    .where(*conditions)
                    .order_by(StudyPlan.year.desc(), StudyPlan.created_at.desc(), StudyPlan.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [await self.plan_data(plan) for plan in plans],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def revisions(self, record: Any, resource_type: str) -> list[dict[str, Any]]:
        """逐版检查资料权限后读取历史修订证据。"""
        revisions = (
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == resource_type,
                        ContentRevision.resource_id == record.id,
                        ContentRevision.is_deleted.is_(False),
                    )
                    .order_by(ContentRevision.revision.desc())
                )
            )
            .scalars()
            .all()
        )
        result = []
        for revision in revisions:
            snapshot = revision.snapshot
            all_sources = [
                *snapshot.get("sources", []),
                *(
                    source
                    for item in snapshot.get("items", [])
                    for source in item.get("sources", [])
                ),
            ]
            _, _, restricted = await visible_sources(
                self.db, self.user, record.org_unit_id, all_sources
            )
            result.append(
                {
                    "revision": revision.revision,
                    "action": revision.action,
                    "actor_id": revision.actor_id,
                    "created_at": jsonable_encoder(revision.created_at),
                    "reason": "内容因资料权限变化暂不可查看" if restricted else revision.reason,
                    "snapshot": None if restricted else snapshot,
                    "restricted": restricted,
                }
            )
        return result

    async def history(
        self,
        *,
        year: int | None,
        org_unit_id: str | None,
        topic: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """经合规门禁按年度、主题和党委查询历史归档。"""
        await require_archive_policy(self.db, self.tenant_id)
        conditions = [
            *self._scope(MeetingRecord),
            MeetingRecord.activity_type == "center_group",
            MeetingRecord.archived_at.is_not(None),
            MeetingRecord.review_status == "approved",
        ]
        if year:
            conditions.extend(
                [
                    MeetingRecord.scheduled_on >= date(year, 1, 1),
                    MeetingRecord.scheduled_on < date(year + 1, 1, 1),
                ]
            )
        if org_unit_id:
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "无权查询该组织")
            conditions.append(MeetingRecord.org_unit_id == org_unit_id)
        if topic:
            conditions.append(MeetingRecord.title.contains(topic, autoescape=True))
        total = await self.db.scalar(select(func.count(MeetingRecord.id)).where(*conditions))
        records = (
            (
                await self.db.execute(
                    select(MeetingRecord)
                    .where(*conditions)
                    .order_by(MeetingRecord.scheduled_on.desc(), MeetingRecord.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [await self.activity_data(record) for record in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def export_activity(self, activity_id: str) -> dict[str, Any]:
        """按当前权限导出归档、材料摘录、计划与确认证据。"""
        await require_archive_policy(self.db, self.tenant_id)
        record = await self.activity(activity_id)
        if not record.archived_at or record.review_status != "approved":
            raise HTTPException(409, "仅能导出已审核归档记录")
        data = await self.activity_data(record)
        if data["restricted"]:
            raise HTTPException(403, "资料权限已变化，不能导出包含旧资料内容的归档")
        plan = await self.plan(record.context["plan_id"])
        pinned = (
            await self.db.execute(
                select(ContentRevision).where(
                    ContentRevision.tenant_id == self.tenant_id,
                    ContentRevision.resource_type == "study_plan",
                    ContentRevision.resource_id == plan.id,
                    ContentRevision.revision == record.context["plan_revision"],
                )
            )
        ).scalar_one_or_none()
        if pinned is None:
            raise HTTPException(409, "关联计划版本待核验")
        pinned_sources = [
            *pinned.snapshot.get("sources", []),
            *(
                source
                for item in pinned.snapshot.get("items", [])
                for source in item.get("sources", [])
            ),
        ]
        _, _, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, pinned_sources
        )
        revisions = await self.revisions(record, "meeting")
        if restricted or any(revision["restricted"] for revision in revisions):
            raise HTTPException(403, "历史版本包含当前不可访问资料，不能导出")
        confirmation = (
            await self.db.execute(
                select(ContentRevision).where(
                    ContentRevision.tenant_id == self.tenant_id,
                    ContentRevision.resource_type == "archive_policy",
                    ContentRevision.resource_id == self.tenant_id,
                    ContentRevision.revision == record.archive_policy_version,
                )
            )
        ).scalar_one_or_none()
        if confirmation is None:
            raise HTTPException(409, "电子归档确认证据待核验")
        return {
            "format_version": "study-1",
            "notice": STUDY_NOTICE,
            "exported_at": jsonable_encoder(utc_now()),
            "record": data,
            "plan_version": pinned.snapshot,
            "revisions": revisions,
            "archive_confirmation": confirmation.snapshot,
        }

    async def metrics(self, year: int, org_unit_id: str | None) -> dict[str, Any]:
        """只读归集；计划按安排年度，次数/参学按实际召开年度，未审核不作正式完成。"""
        if org_unit_id and org_unit_id not in self.org_ids:
            raise HTTPException(403, "无权统计该组织")
        plan_conditions = [*self._scope(StudyPlan), StudyPlan.year == year]
        activity_conditions = [
            *self._scope(MeetingRecord),
            MeetingRecord.activity_type == "center_group",
            MeetingRecord.held_on >= date(year, 1, 1),
            MeetingRecord.held_on < date(year + 1, 1, 1),
        ]
        if org_unit_id:
            plan_conditions.append(StudyPlan.org_unit_id == org_unit_id)
            activity_conditions.append(MeetingRecord.org_unit_id == org_unit_id)
        plans = (await self.db.execute(select(StudyPlan).where(*plan_conditions))).scalars().all()
        records = (
            (
                await self.db.execute(
                    select(MeetingRecord).where(*activity_conditions).order_by(MeetingRecord.id)
                )
            )
            .scalars()
            .all()
        )
        formal, evidence, missing = [], [], []
        for record in records:
            if record.archived_at:
                await require_archive_policy(self.db, self.tenant_id)
            data = await self.activity_data(record)
            if record.review_status != "approved" or data["restricted"]:
                missing.append("有未审核或资料待核验活动，未计入正式次数与参学率")
                continue
            formal.append(record)
            evidence.append(
                {
                    "activity_id": str(record.id),
                    "revision": record.revision,
                    "held_on": record.held_on.isoformat(),
                    "reviewed_by": record.reviewed_by,
                    "participants": [
                        {"source_id": f"{record.id}:{person['participant_id']}", **person}
                        for person in record.participants
                    ],
                    "minutes_sections": [
                        key
                        for key in ("learning_points", "consensus", "requirements")
                        if record.minutes.get(key)
                    ],
                    "sources": data["sources"],
                }
            )
        planned, completed, plan_evidence = 0, 0, []
        for plan in plans:
            plan_data = await self.plan_data(plan)
            if plan.review_status != "approved" or plan_data["restricted"]:
                missing.append("年度计划尚未审核或资料待核验")
                continue
            for entry in await self.items(plan):
                planned += 1
                linked = None
                if entry.meeting_record_id:
                    linked = (
                        await self.db.execute(
                            select(MeetingRecord).where(
                                *self._scope(MeetingRecord),
                                MeetingRecord.id == entry.meeting_record_id,
                            )
                        )
                    ).scalar_one_or_none()
                done = False
                if linked:
                    if linked.archived_at:
                        await require_archive_policy(self.db, self.tenant_id)
                    linked_data = await self.activity_data(linked)
                    done = (
                        linked.review_status == "approved"
                        and linked.held_on is not None
                        and not linked_data["restricted"]
                    )
                completed += int(done)
                plan_evidence.append(
                    {
                        "plan_id": str(plan.id),
                        "plan_revision": plan.revision,
                        "item_id": str(entry.id),
                        "activity_id": entry.meeting_record_id,
                        "completed": done,
                    }
                )
        expected = sum(len(record.participants) for record in formal)
        attended = sum(
            sum(person["attended"] for person in record.participants) for record in formal
        )
        complete_minutes = sum(not minutes_missing(record) for record in formal)
        if not planned:
            missing.append("经审核年度计划安排待补")
        if not formal:
            missing.append("经审核学习记录、参学及纪要统计待补")

        def ratio(numerator: int, denominator: int) -> dict[str, Any]:
            """在当前授权事务内处理学习业务。"""
            return {
                "value": round(numerator / denominator, 4) if denominator else None,
                "numerator": numerator,
                "denominator": denominator,
                "status": "known" if denominator else "pending",
            }

        return {
            "year": year,
            "org_unit_id": org_unit_id,
            "plan_completion_rate": ratio(completed, planned),
            "learning_count": {
                "value": len(formal) if formal else None,
                "status": "known" if formal else "pending",
            },
            "attendance_rate": ratio(attended, expected),
            "minutes_completeness": ratio(complete_minutes, len(formal)),
            "evidence": evidence,
            "plan_evidence": plan_evidence,
            "missing": list(dict.fromkeys(missing)),
            "notice": STUDY_NOTICE,
            "calculation_rule": "study-1：计划按安排年度；次数、参学、纪要按实际学习年度；仅人工审核通过的记录进入正式统计",
        }
