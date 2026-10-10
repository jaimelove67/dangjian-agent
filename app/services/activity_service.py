"""组织生活（三会一课）活动闭环：计划登记、材料议程、纪要审核、任务台账与考核复用。

与中心组学习共用 ``meeting_records`` 活动记录与只追加 ``content_revisions`` 审核证据；
本模块只处理组织生活类型（支部大会/支委会/党小组会/党课/其他），所有读写均带
租户及有效组织范围，审核与归档按共用合规规则执行。
"""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import ContentRevision, MeetingRecord, MeetingTask
from app.models.user import User
from app.schemas.meeting import (
    ActivityCreate,
    ActivityUpdate,
    ReviewRequest,
    RevisionRequest,
    TaskCreate,
    TaskHandle,
    TaskUpdate,
)
from app.services.archive_service import require_archive_policy
from app.services.meeting_service import (
    apply_review,
    extract_minutes,
    minutes_missing,
    reset_review,
    utc_now,
    validate_minutes,
)
from app.services.org_scope import accessible_org_units
from app.services.study_materials import recommend_sources, selected_sources, visible_sources

ORGANIZATION_LIFE_NOTICE = "供支部委员会研究确定，不作为正式纪要"
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "business_rules.yaml"

ACTIVITY_TYPES: dict[str, str] = {
    "branch_member_meeting": "支部大会",
    "branch_committee_meeting": "支委会",
    "party_group_meeting": "党小组会",
    "party_lecture": "党课",
    "other": "其他组织生活",
}


def row_data(record: Any) -> dict[str, Any]:
    """版本快照保留真实字段；不保存 SQLAlchemy 内部状态。"""
    return jsonable_encoder(
        {column.key: getattr(record, column.key) for column in record.__table__.columns}
    )


def load_activity_requirements() -> dict[str, dict[str, Any]]:
    """年度规定频次仅作提示，不由模型认定完成；配置缺失时按内置默认。"""
    default = {
        "branch_member_meeting": {"annual_required": 4, "reminders": []},
        "branch_committee_meeting": {"annual_required": 4, "reminders": []},
        "party_group_meeting": {"annual_required": 6, "reminders": []},
        "party_lecture": {"annual_required": 2, "reminders": []},
        "other": {"annual_required": 0, "reminders": ["其他组织生活不设固定年度频次"]},
    }
    try:
        data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return default
    configured = data.get("activity_requirements") or {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in default.items():
        entry = configured.get(key) or {}
        result[key] = {
            "annual_required": int(entry.get("annual_required", value["annual_required"])),
            "reminders": list(entry.get("reminders") or value["reminders"]),
        }
    return result


def _execution_status(record: MeetingRecord) -> str:
    if record.archived_at:
        return "archived"
    if record.review_status == "approved":
        return "completed"
    if record.review_status == "pending":
        return "pending"
    if record.review_status == "rejected":
        return "rejected"
    return "held" if record.held_on else "planned"


class ActivityService:
    """在请求事务内完成组织生活业务及只追加版本，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []

    async def initialize(self) -> "ActivityService":
        """组织生活活动以登录人的有效组织范围为准。"""
        self.orgs = await accessible_org_units(self.db, self.user)
        self.org_ids = [str(org.id) for org in self.orgs]
        return self

    def _scope(self, model: Any) -> list[Any]:
        return [
            model.tenant_id == self.tenant_id,
            model.is_deleted.is_(False),
            model.org_unit_id.in_(self.org_ids),
        ]

    async def record(self, record_id: str, *, lock: bool = False) -> MeetingRecord:
        """不可访问的编号统一返回不存在，避免跨组织探测。"""
        stmt = select(MeetingRecord).where(
            *self._scope(MeetingRecord),
            MeetingRecord.id == record_id,
            MeetingRecord.activity_type.in_(list(ACTIVITY_TYPES)),
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise HTTPException(404, "组织生活记录不存在或无权访问")
        if record.archived_at:
            await require_archive_policy(self.db, self.tenant_id)
        return record

    async def task(self, task_id: str, *, lock: bool = False) -> MeetingTask:
        stmt = select(MeetingTask).where(*self._scope(MeetingTask), MeetingTask.id == task_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        task = (await self.db.execute(stmt)).scalar_one_or_none()
        if task is None:
            raise HTTPException(404, "会议任务不存在或无权访问")
        record = await self.record(task.record_id)
        await self.require_visible_content(record)
        return task

    async def require_visible_content(self, record: MeetingRecord) -> None:
        """任务摘录沿用母记录关联资料的当前权限。"""
        _, _, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, await self.content_sources(record)
        )
        if restricted:
            raise HTTPException(403, "关联资料权限已变化，内容暂不可访问")

    async def content_sources(self, record: MeetingRecord) -> list[dict[str, Any]]:
        """删改当前材料选择不能解除旧正文及任务的来源权限。"""
        context = record.context or {}
        sources = list(record.sources or []) + list(context.get("content_sources", []))
        # 旧记录从不可覆盖的历史版本补全来源，避免此前清空关联资料绕过检查。
        if "content_sources" not in context:
            snapshots = (
                (
                    await self.db.execute(
                        select(ContentRevision.snapshot).where(
                            ContentRevision.tenant_id == self.tenant_id,
                            ContentRevision.resource_type == "meeting",
                            ContentRevision.resource_id == str(record.id),
                            ContentRevision.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for snapshot in snapshots:
                sources.extend(snapshot.get("sources", []))
                sources.extend((snapshot.get("context") or {}).get("content_sources", []))
        distinct = {}
        for source in sources:
            distinct[(source.get("doc_id"), source.get("content_revision"))] = source
        return list(distinct.values())

    async def tasks_of(self, record: MeetingRecord) -> list[MeetingTask]:
        return list(
            (
                await self.db.execute(
                    select(MeetingTask)
                    .where(
                        MeetingTask.tenant_id == self.tenant_id,
                        MeetingTask.record_id == str(record.id),
                        MeetingTask.is_deleted.is_(False),
                    )
                    .order_by(MeetingTask.created_at, MeetingTask.id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def check_revision(record: Any, expected: int) -> None:
        """拒绝覆盖别人已经修订的内容。"""
        if record.revision != expected:
            raise HTTPException(409, "内容已被修订，请刷新并核对当前版本后重试")

    async def _snapshot(self, record: Any) -> dict[str, Any]:
        snapshot = row_data(record)
        if isinstance(record, MeetingRecord):
            snapshot["tasks"] = [row_data(task) for task in await self.tasks_of(record)]
        return snapshot

    async def save_revision(
        self,
        record: Any,
        resource_type: str,
        action: str,
        reason: str,
        *,
        initial: bool = False,
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

    # ==================== 活动计划 ====================

    async def create(self, body: ActivityCreate) -> MeetingRecord:
        """登记一次组织生活计划，保留初始依据版本。"""
        if body.org_unit_id not in self.org_ids:
            raise HTTPException(403, "请选择权限范围内有效的组织")
        sources = await selected_sources(
            self.db, self.user, body.org_unit_id, body.source_doc_ids, on=body.scheduled_on
        )
        record = MeetingRecord(
            tenant_id=self.tenant_id,
            org_unit_id=body.org_unit_id,
            activity_type=body.activity_type,
            title=body.title,
            scheduled_on=body.scheduled_on,
            host=body.host,
            participants=[person.model_dump() for person in body.participants],
            source_doc_ids=list(dict.fromkeys(body.source_doc_ids)),
            sources=sources,
            context={"agenda": body.agenda, "notice": body.notice, "content_sources": sources},
        )
        self.db.add(record)
        await self.db.flush()
        await self.save_revision(record, "meeting", "create", body.reason, initial=True)
        return record

    async def update(self, record_id: str, body: ActivityUpdate) -> MeetingRecord:
        """修订活动计划与会议文本；修改内容后必须重新送审。"""
        record = await self.record(record_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档活动不能覆盖，请保留正式版本")
        derived_sources = await self.content_sources(record)
        if body.scheduled_on is not None:
            record.scheduled_on = body.scheduled_on
        if body.held_on is not None:
            record.held_on = body.held_on
        if body.host is not None:
            record.host = body.host
        if body.topic is not None:
            record.title = body.topic
        if body.participants is not None:
            record.participants = [person.model_dump() for person in body.participants]
        content_changed = body.transcript is not None or body.minutes is not None
        if content_changed:
            transcript = body.transcript if body.transcript is not None else record.transcript
            minutes = body.minutes.model_dump() if body.minutes is not None else {}
            validate_minutes(transcript, minutes)
            record.transcript, record.minutes = transcript, minutes
        if body.source_doc_ids is not None:
            chosen = await selected_sources(
                self.db,
                self.user,
                record.org_unit_id,
                body.source_doc_ids,
                on=body.held_on or record.scheduled_on or date.today(),
            )
            record.sources, record.source_doc_ids = chosen, list(dict.fromkeys(body.source_doc_ids))
        context = dict(record.context or {})
        context["content_sources"] = derived_sources + list(record.sources or [])
        if body.agenda is not None:
            context["agenda"] = body.agenda
        if body.notice is not None:
            context["notice"] = body.notice
        record.context = context
        reset_review(record)
        await self.save_revision(record, "meeting", "revise", body.reason)
        return record

    async def recommendations(self, record_id: str, query: str | None = None) -> dict[str, Any]:
        """从授权知识库推荐议题材料，不补写虚构文件。"""
        record = await self.record(record_id)
        await self.require_visible_content(record)
        sources = await recommend_sources(
            self.db,
            self.user,
            record.org_unit_id,
            [record.title],
            on=record.scheduled_on or date.today(),
            query=query,
        )
        return {
            "topic": record.title,
            "sources": sources,
            "missing": [] if sources else ["没有匹配的有效授权资料，政策依据待补"],
            "notice": ORGANIZATION_LIFE_NOTICE,
        }

    async def generate_agenda(self, record_id: str, body: RevisionRequest) -> MeetingRecord:
        """生成通知与议程草稿；依据全部来自已选真实材料摘录。"""
        record = await self.record(record_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档活动不能覆盖")
        sources = await selected_sources(
            self.db,
            self.user,
            record.org_unit_id,
            record.source_doc_ids,
            on=record.held_on or record.scheduled_on or date.today(),
        )
        materials = (
            "\n".join(
                f"[{index}] {source['title']}（{source['doc_id']}，"
                f"版本{source['content_revision']}，生效{source['effective_date']}）："
                f"{source['excerpt'] or '原文摘录待补'}"
                for index, source in enumerate(sources, 1)
            )
            or "政策依据待补；资料不足时不生成政策表述。"
        )
        people = "、".join(person["name"] for person in record.participants) or "参会人员待补"
        agenda = (
            f"会议议程（草稿）：\n一、{record.title}\n二、政策依据材料：\n{materials}\n"
            f"三、讨论安排：请围绕上述依据酝酿意见\n四、参会范围：{people}\n{ORGANIZATION_LIFE_NOTICE}"
        )
        notice = (
            f"会议通知（草稿）：\n会议名称：{record.title}\n"
            f"计划时间：{record.scheduled_on.isoformat()}\n主持人：{record.host or '待补'}\n"
            f"参会范围：{people}\n{ORGANIZATION_LIFE_NOTICE}"
        )
        context = dict(record.context or {})
        context.update(
            agenda=agenda,
            notice=notice,
            agenda_template_version="org-life-1",
        )
        record.context = context
        reset_review(record)
        await self.save_revision(record, "meeting", "generate_agenda", body.reason)
        return record

    # ==================== 纪要 ====================

    async def generate_minutes(self, record_id: str, body: RevisionRequest) -> MeetingRecord:
        """仅提取原文中明确标注的学习要点、共识与工作要求。"""
        record = await self.record(record_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档纪要不能覆盖")
        if not record.transcript:
            raise HTTPException(422, "原始会议文本待补")
        await self.require_visible_content(record)
        record.minutes = extract_minutes(record.transcript)
        reset_review(record)
        await self.save_revision(record, "meeting", "generate_minutes", body.reason)
        return record

    async def _validate_activity(self, record: MeetingRecord) -> None:
        missing = minutes_missing(record)
        if missing:
            raise HTTPException(422, "；".join(missing))
        validate_minutes(record.transcript, record.minutes)
        _, _, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, await self.content_sources(record)
        )
        if restricted:
            raise HTTPException(409, "关联材料权限已变化，请重新选择材料后送审")

    async def submit(self, record_id: str, body: RevisionRequest) -> MeetingRecord:
        """核查原文定位、参会、日期及依据后提交纪要。"""
        record = await self.record(record_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at or record.review_status not in ("draft", "rejected"):
            raise HTTPException(409, "当前纪要不能再次提交，请先修订")
        await self._validate_activity(record)
        record.review_status, record.submitted_by = "pending", str(self.user.id)
        await self.save_revision(record, "meeting", "submit", body.reason)
        return record

    async def review(self, record_id: str, body: ReviewRequest) -> MeetingRecord:
        """人工审核当前纪要版本，不允许自审。"""
        record = await self.record(record_id, lock=True)
        self.check_revision(record, body.expected_revision)
        if record.archived_at:
            raise HTTPException(409, "已归档纪要不能重复审核")
        if body.decision == "approved":
            await self._validate_activity(record)
        apply_review(record, str(self.user.id), body.decision, body.reason)
        await self.save_revision(record, "meeting", "review", body.reason)
        return record

    # ==================== 任务台账 ====================

    async def create_task(self, record_id: str, body: TaskCreate) -> MeetingTask:
        """原文摘录必须与会议文本逐字一致；责任人或期限缺省待人工补齐。"""
        record = await self.record(record_id, lock=True)
        await self.require_visible_content(record)
        if (
            body.source_end > len(record.transcript)
            or record.transcript[body.source_start : body.source_end] != body.task_text
        ):
            raise HTTPException(422, "任务摘录与原文位置不一致，请重新定位")
        task = MeetingTask(
            tenant_id=self.tenant_id,
            record_id=str(record.id),
            org_unit_id=record.org_unit_id,
            task_text=body.task_text,
            source_start=body.source_start,
            source_end=body.source_end,
            owner_name=body.owner_name,
            due_on=body.due_on,
            status="pending",
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def confirm_task(self, task_id: str, body: TaskUpdate) -> MeetingTask:
        """人工补齐责任人与期限后确认任务进入台账。"""
        task = await self.task(task_id, lock=True)
        if task.status != "pending":
            raise HTTPException(409, "该任务已确认或已处理，不能重复确认")
        if not (body.owner_name or task.owner_name):
            raise HTTPException(422, "原文未明确责任人，请先人工补齐后再确认")
        if body.owner_name:
            task.owner_name = body.owner_name
        if body.due_on is not None:
            task.due_on = body.due_on
        task.status = "active"
        task.confirmed_by = str(self.user.id)
        task.confirmed_at = utc_now()
        return task

    async def handle_task(self, task_id: str, body: TaskHandle) -> MeetingTask:
        """任务完成或取消，处理记录留痕。"""
        task = await self.task(task_id, lock=True)
        if task.status not in ("pending", "active"):
            raise HTTPException(409, "该任务已结束，不能重复处理")
        if task.status == "pending":
            raise HTTPException(422, "任务须先人工确认责任人后再处理")
        task.status = body.status
        task.handled_at = utc_now()
        task.handle_note = body.handle_note
        return task

    async def list_tasks(
        self,
        *,
        org_unit_id: str | None,
        year: int | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """按组织、年度与状态分页查询任务台账。"""
        conditions = self._scope(MeetingTask)
        if org_unit_id:
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "无权查询该组织")
            conditions.append(MeetingTask.org_unit_id == org_unit_id)
        if year:
            record_ids = select(MeetingRecord.id).where(
                MeetingRecord.tenant_id == self.tenant_id,
                MeetingRecord.is_deleted.is_(False),
                MeetingRecord.scheduled_on >= date(year, 1, 1),
                MeetingRecord.scheduled_on < date(year + 1, 1, 1),
            )
            conditions.append(MeetingTask.record_id.in_(record_ids))
        if status:
            conditions.append(MeetingTask.status == status)
        total = await self.db.scalar(select(func.count(MeetingTask.id)).where(*conditions))
        tasks = (
            (
                await self.db.execute(
                    select(MeetingTask)
                    .where(*conditions)
                    .order_by(MeetingTask.created_at.desc(), MeetingTask.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        items = []
        for task in tasks:
            try:
                record = await self.record(task.record_id)
                await self.require_visible_content(record)
            except HTTPException as exc:
                if exc.status_code not in (403, 404):
                    raise
                items.append({"id": str(task.id), "restricted": True})
            else:
                items.append({**row_data(task), "restricted": False})
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ==================== 归档与复用 ====================

    async def archive(self, record_id: str, body: RevisionRequest) -> MeetingRecord:
        """学校确认电子效力后归档人工审核通过的记录。"""
        record = await self.record(record_id, lock=True)
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
            self.db, self.user, record.org_unit_id, await self.content_sources(record)
        )
        if restricted:
            raise HTTPException(403, "关联材料当前不可访问，不能归档")
        record.archived_at, record.archive_policy_version = utc_now(), policy["revision"]
        await self.save_revision(record, "meeting", "archive", body.reason)
        return record

    async def record_data(self, record: MeetingRecord) -> dict[str, Any]:
        """生成当前授权的活动响应，缺项明确待补。"""
        data = row_data(record)
        data["sources"], warnings, restricted = await visible_sources(
            self.db, self.user, record.org_unit_id, await self.content_sources(record)
        )
        data["tasks"] = [row_data(task) for task in await self.tasks_of(record)]
        data.update(
            activity_type_label=ACTIVITY_TYPES.get(record.activity_type, record.activity_type),
            notice=ORGANIZATION_LIFE_NOTICE,
            missing=minutes_missing(record) + warnings,
            restricted=restricted,
            execution_status=_execution_status(record),
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
                context={},
                tasks=[],
            )
        else:
            data["context"] = {
                key: value
                for key, value in (record.context or {}).items()
                if key != "content_sources"
            }
        return data

    async def list_records(
        self,
        *,
        year: int | None,
        org_unit_id: str | None,
        activity_type: str | None,
        execution_status: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """按年度、组织、活动类型与执行状态分页查询。"""
        conditions = [
            *self._scope(MeetingRecord),
            MeetingRecord.activity_type.in_(list(ACTIVITY_TYPES)),
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
        if activity_type:
            if activity_type not in ACTIVITY_TYPES:
                raise HTTPException(422, "未知活动类型")
            conditions.append(MeetingRecord.activity_type == activity_type)
        if execution_status:
            if execution_status == "archived":
                conditions.append(MeetingRecord.archived_at.is_not(None))
            elif execution_status == "completed":
                conditions.extend(
                    [
                        MeetingRecord.review_status == "approved",
                        MeetingRecord.archived_at.is_(None),
                        MeetingRecord.held_on.is_not(None),
                    ]
                )
            elif execution_status == "pending":
                conditions.append(MeetingRecord.review_status == "pending")
            elif execution_status == "rejected":
                conditions.append(MeetingRecord.review_status == "rejected")
            elif execution_status == "held":
                conditions.extend(
                    [
                        MeetingRecord.held_on.is_not(None),
                        MeetingRecord.review_status == "draft",
                        MeetingRecord.archived_at.is_(None),
                    ]
                )
            elif execution_status == "planned":
                conditions.extend(
                    [
                        MeetingRecord.held_on.is_(None),
                        MeetingRecord.review_status == "draft",
                        MeetingRecord.archived_at.is_(None),
                    ]
                )
            else:
                raise HTTPException(422, "未知执行状态")
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
            "items": [await self.record_data(record) for record in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def revisions(self, record: MeetingRecord) -> list[dict[str, Any]]:
        """逐版检查资料权限后读取历史修订证据。"""
        revisions = (
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == "meeting",
                        ContentRevision.resource_id == str(record.id),
                        ContentRevision.is_deleted.is_(False),
                    )
                    .order_by(ContentRevision.revision.desc())
                )
            )
            .scalars()
            .all()
        )
        result = []
        current_sources = await self.content_sources(record)
        for revision in revisions:
            snapshot = revision.snapshot
            all_sources = snapshot.get("sources", []) if isinstance(snapshot, dict) else []
            _, _, restricted = await visible_sources(
                self.db, self.user, record.org_unit_id, all_sources + current_sources
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
        activity_type: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """经合规门禁按年度、组织与类型查询历史归档。"""
        await require_archive_policy(self.db, self.tenant_id)
        conditions = [
            *self._scope(MeetingRecord),
            MeetingRecord.activity_type.in_(list(ACTIVITY_TYPES)),
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
        if activity_type:
            if activity_type not in ACTIVITY_TYPES:
                raise HTTPException(422, "未知活动类型")
            conditions.append(MeetingRecord.activity_type == activity_type)
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
            "items": [await self.record_data(record) for record in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def export(self, record_id: str) -> dict[str, Any]:
        """按当前权限导出已审核归档记录、修订证据与确认依据。"""
        await require_archive_policy(self.db, self.tenant_id)
        record = await self.record(record_id)
        if not record.archived_at or record.review_status != "approved":
            raise HTTPException(409, "仅能导出已审核归档记录")
        data = await self.record_data(record)
        if data["restricted"]:
            raise HTTPException(403, "资料权限已变化，不能导出包含旧资料内容的归档")
        revisions = await self.revisions(record)
        if any(revision["restricted"] for revision in revisions):
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
            "format_version": "org-life-1",
            "notice": ORGANIZATION_LIFE_NOTICE,
            "exported_at": jsonable_encoder(utc_now()),
            "record": data,
            "revisions": revisions,
            "archive_confirmation": confirmation.snapshot,
        }

    async def stats(self, year: int, org_unit_id: str | None) -> dict[str, Any]:
        """只读归集；仅人工审核通过的记录进入正式统计，缺项与未审核明确待补。"""
        if org_unit_id and org_unit_id not in self.org_ids:
            raise HTTPException(403, "无权统计该组织")
        conditions = [
            *self._scope(MeetingRecord),
            MeetingRecord.activity_type.in_(list(ACTIVITY_TYPES)),
            MeetingRecord.held_on >= date(year, 1, 1),
            MeetingRecord.held_on < date(year + 1, 1, 1),
        ]
        if org_unit_id:
            conditions.append(MeetingRecord.org_unit_id == org_unit_id)
        records = (
            (
                await self.db.execute(
                    select(MeetingRecord).where(*conditions).order_by(MeetingRecord.id)
                )
            )
            .scalars()
            .all()
        )
        formal, evidence, missing = [], [], []
        for record in records:
            if record.archived_at:
                await require_archive_policy(self.db, self.tenant_id)
            data = await self.record_data(record)
            if record.review_status != "approved" or data["restricted"]:
                missing.append("存在未审核或资料待核验活动，未计入正式次数与参学统计")
                continue
            formal.append(record)
            evidence.append(
                {
                    "activity_id": str(record.id),
                    "activity_type": record.activity_type,
                    "activity_type_label": ACTIVITY_TYPES[record.activity_type],
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
        expected = sum(len(record.participants) for record in formal)
        attended = sum(
            sum(person["attended"] for person in record.participants) for record in formal
        )
        complete_minutes = sum(not minutes_missing(record) for record in formal)

        def ratio(numerator: int, denominator: int) -> dict[str, Any]:
            return {
                "value": round(numerator / denominator, 4) if denominator else None,
                "numerator": numerator,
                "denominator": denominator,
                "status": "known" if denominator else "pending",
            }

        counts: dict[str, int] = {}
        for record in records:
            counts[_execution_status(record)] = counts.get(_execution_status(record), 0) + 1
        by_type: dict[str, dict[str, Any]] = {}
        for key in ACTIVITY_TYPES:
            held_reviewed = [
                record
                for record in formal
                if record.activity_type == key and record.review_status == "approved"
            ]
            by_type[key] = {
                "label": ACTIVITY_TYPES[key],
                "required": load_activity_requirements()[key]["annual_required"],
                "performed": len(held_reviewed),
                "total_registered": sum(1 for record in records if record.activity_type == key),
            }
        if not formal:
            missing.append("经审核组织生活记录、参学及纪要统计待补")
        return {
            "year": year,
            "org_unit_id": org_unit_id,
            "counts": {"total": len(records), **counts},
            "by_type": by_type,
            "attendance_rate": ratio(attended, expected),
            "minutes_completeness": ratio(complete_minutes, len(formal)),
            "evidence": evidence,
            "missing": list(dict.fromkeys(missing)),
            "notice": ORGANIZATION_LIFE_NOTICE,
            "calculation_rule": (
                "org-life-1：年度按实际召开日期；次数、参学与纪要仅统计人工审核通过记录；"
                "年度规定频次仅作提示，不由模型或系统自动认定完成"
            ),
        }
