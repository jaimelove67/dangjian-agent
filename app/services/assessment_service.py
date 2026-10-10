"""考核业务闭环：权限、版本、可复核统计、人工审核、提醒及授权材料目录。"""

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.assessment import (
    AssessmentArchive,
    AssessmentEvidence,
    AssessmentIndicator,
    AssessmentPlan,
    AssessmentPolicy,
    AssessmentReminder,
    AssessmentRun,
    AssessmentTask,
)
from app.models.meeting import ContentRevision
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.rules.assessment import (
    ENGINE_VERSION,
    SourceBatch,
    SourceRecord,
    batch_snapshot,
    calculate_indicator,
    fingerprint,
    task_state,
)
from app.schemas.assessment import (
    EvidenceCreate,
    IndicatorCreate,
    PlanCreate,
    PolicyUpdate,
    ReviewRequest,
    TaskCreate,
    TaskUpdate,
)
from app.schemas.study import ArchivePolicyUpdate
from app.services.archive_service import archive_policy, require_archive_policy, save_archive_policy
from app.services.assessment_sources import (
    authorized_documents,
    authorized_historical_sources,
    document_version,
    load_source,
)
from app.services.org_scope import accessible_org_units, can_access_org_unit


def utc_now() -> datetime:
    """沿用数据库的无时区UTC时间，避免生效时间比较混用时区。"""
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def row_view(row: Any) -> dict[str, Any]:
    """仅返回业务字段，不返回数据库租户字段。"""
    return _json(
        {key: value for key, value in row.dict().items() if key not in {"tenant_id", "is_deleted"}}
    )


def run_view(run: AssessmentRun) -> dict[str, Any]:
    return {key: value for key, value in row_view(run).items() if key not in {"inputs", "results"}}


class AssessmentService:
    """一个请求内复用组织范围；所有对象查询均显式校验当前租户和组织。"""

    def __init__(self, db: AsyncSession, user: User):
        self.db, self.user = db, user
        self.tenant_id = str(user.tenant_id)
        self._orgs: list[OrgUnit] | None = None
        self.audit_changes: list[dict[str, Any]] = []

    async def _save_revision(
        self, kind: str, record: Any, action: str, *, old: dict[str, Any] | None = None
    ) -> None:
        """复用只追加业务快照，审计只存对象、版本和快照编号而不存正文。"""
        await self.db.flush()
        await self.db.refresh(record)
        resource_type = "assessment_" + kind
        prior = (
            await self.db.execute(
                select(ContentRevision)
                .where(
                    ContentRevision.tenant_id == self.tenant_id,
                    ContentRevision.resource_type == resource_type,
                    ContentRevision.resource_id == str(record.id),
                )
                .order_by(ContentRevision.revision.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if old is not None and prior is None:
            prior = ContentRevision(
                tenant_id=self.tenant_id,
                resource_type=resource_type,
                resource_id=str(record.id),
                revision=old.get("revision", old.get("version", 1)),
                action="baseline",
                actor_id=old.get("reviewed_by") or old.get("created_by") or str(self.user.id),
                reason="补存首次修订前的已有状态",
                snapshot=old,
            )
            self.db.add(prior)
            await self.db.flush()
        snapshot = row_view(record)
        revision = snapshot.get("revision", snapshot.get("version"))
        if revision is None:
            revision = prior.revision + 1 if prior else 1
        current = ContentRevision(
            tenant_id=self.tenant_id,
            resource_type=resource_type,
            resource_id=str(record.id),
            revision=revision,
            action=action,
            actor_id=str(self.user.id),
            reason=snapshot.get("review_opinion") or snapshot.get("handling_note") or action,
            snapshot=snapshot,
        )
        self.db.add(current)
        await self.db.flush()
        self.audit_changes.append(
            {
                "resource_type": resource_type,
                "resource_id": str(record.id),
                "old_value": (
                    {"revision": prior.revision, "snapshot_id": str(prior.id)} if prior else None
                ),
                "new_value": {"revision": revision, "snapshot_id": str(current.id)},
            }
        )

    async def organizations(self) -> list[OrgUnit]:
        """读取当前有效业务范围，不接受客户端权限列表。"""
        if self._orgs is None:
            self._orgs = await accessible_org_units(self.db, self.user)
        return self._orgs

    async def scope(self, org_id: str) -> tuple[OrgUnit, OrgUnit, set[str]]:
        """选中组织及有效后代，学校沿同租户祖先链确定，异常组织树拒绝。"""
        orgs = await self.organizations()
        selected = next((org for org in orgs if str(org.id) == org_id), None)
        if selected is None:
            raise HTTPException(403, "请选择权限范围内的有效组织")
        ids = {org_id}
        while True:
            children = {str(org.id) for org in orgs if org.parent_id in ids}
            if children <= ids:
                break
            ids |= children
        school, seen = selected, set()
        while school.org_type != "school":
            if not school.parent_id or school.id in seen:
                raise HTTPException(409, "组织未关联有效学校，请先配置组织树")
            seen.add(school.id)
            school = (
                await self.db.execute(
                    select(OrgUnit).where(
                        OrgUnit.id == school.parent_id,
                        OrgUnit.tenant_id == self.tenant_id,
                        OrgUnit.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if school is None:
                raise HTTPException(409, "组织祖先无效，请先配置组织树")
        return selected, school, ids

    async def _lock_org(self, org_id: str) -> None:
        await self.db.execute(
            select(OrgUnit)
            .where(
                OrgUnit.id == org_id,
                OrgUnit.tenant_id == self.tenant_id,
            )
            .with_for_update()
        )

    async def _get(self, model: type, record_id: str, *, lock: bool = False) -> Any:
        statement = select(model).where(
            model.id == record_id,
            model.tenant_id == self.tenant_id,
            model.is_deleted.is_(False),
        )
        record = (
            await self.db.execute(statement.with_for_update() if lock else statement)
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(404, "记录不存在或无权访问")
        await self.scope(record.org_unit_id)
        return record

    async def _rules(self, school_id: str, year: int) -> list[AssessmentIndicator]:
        return list(
            (
                await self.db.execute(
                    select(AssessmentIndicator)
                    .where(
                        AssessmentIndicator.tenant_id == self.tenant_id,
                        AssessmentIndicator.school_org_id == school_id,
                        AssessmentIndicator.year == year,
                        AssessmentIndicator.is_deleted.is_(False),
                    )
                    .order_by(AssessmentIndicator.code, AssessmentIndicator.version.desc())
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _active_rules(rules: list[AssessmentIndicator]) -> list[AssessmentIndicator]:
        active: dict[str, AssessmentIndicator] = {}
        now = utc_now()
        for rule in rules:
            if rule.effective_from <= now and (
                rule.code not in active or rule.version > active[rule.code].version
            ):
                active[rule.code] = rule
        return [active[code] for code in sorted(active)]

    async def create_indicator(self, body: IndicatorCreate) -> AssessmentIndicator:
        """学校人员追加规则版本；锁学校行处理同编码并发修订。"""
        selected, school, _ = await self.scope(body.org_unit_id)
        if selected.id != school.id or self.user.role not in {
            UserRole.SYSTEM_ADMIN,
            UserRole.SCHOOL_ADMIN,
        }:
            raise HTTPException(403, "学校指标须由学校级管理员在学校范围维护")
        await self._lock_org(str(school.id))
        versions = [
            rule.version
            for rule in await self._rules(str(school.id), body.year)
            if rule.code == body.code
        ]
        latest = max(versions, default=0)
        if latest != body.expected_version:
            raise HTTPException(409, "指标版本已变化，请刷新后重新提交")
        effective = body.effective_from or utc_now()
        if effective.tzinfo is not None:
            effective = effective.astimezone(UTC).replace(tzinfo=None)
        record = AssessmentIndicator(
            tenant_id=self.tenant_id,
            school_org_id=str(school.id),
            version=latest + 1,
            effective_from=effective,
            created_by=str(self.user.id),
            target=str(body.target),
            **body.model_dump(
                exclude={"org_unit_id", "expected_version", "effective_from", "target"}
            ),
        )
        self.db.add(record)
        await self.db.flush()
        await self._save_revision("indicators", record, "create")
        return record

    async def policy(self, school_id: str) -> AssessmentPolicy | None:
        return (
            await self.db.execute(
                select(AssessmentPolicy).where(
                    AssessmentPolicy.tenant_id == self.tenant_id,
                    AssessmentPolicy.school_org_id == school_id,
                    AssessmentPolicy.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def update_policy(self, body: PolicyUpdate) -> AssessmentPolicy:
        """学校电子记录确认与提前提醒量，不提供默认启用或自动确认。"""
        selected, school, _ = await self.scope(body.org_unit_id)
        if selected.id != school.id or self.user.role not in {
            UserRole.SYSTEM_ADMIN,
            UserRole.SCHOOL_ADMIN,
        }:
            raise HTTPException(403, "归档合规确认须由学校级管理员维护")
        await self._lock_org(str(school.id))
        policy = await self.policy(str(school.id))
        if (policy.version if policy else 0) != body.expected_version:
            raise HTTPException(409, "配置版本已变化，请刷新后重试")
        old = row_view(policy) if policy else None
        if policy is None:
            policy = AssessmentPolicy(
                tenant_id=self.tenant_id, school_org_id=str(school.id), version=0
            )
            self.db.add(policy)
        policy.archive_enabled = body.archive_enabled
        policy.reminder_advance_days = body.reminder_advance_days
        policy.confirmation_note = body.confirmation_note
        policy.confirmed_by, policy.confirmed_at = str(self.user.id), utc_now()
        policy.version += 1
        await save_archive_policy(
            self.db,
            self.user,
            ArchivePolicyUpdate(
                enabled=body.archive_enabled,
                expected_revision=body.expected_archive_version,
                evidence=body.confirmation_note or "调整考核提醒并保持电子归档关闭",
            ),
        )
        await self.db.flush()
        await self.db.refresh(policy)
        await self._save_revision("policies", policy, "update", old=old)
        return policy

    async def _owners(self, org_id: str) -> list[User]:
        """责任人必须仍有业务权限，且其当前组织范围覆盖任务组织。"""
        candidates = list(
            (
                await self.db.execute(
                    select(User)
                    .where(
                        User.tenant_id == self.tenant_id,
                        User.is_deleted.is_(False),
                        User.is_active.is_(True),
                    )
                    .order_by(User.id)
                )
            )
            .scalars()
            .all()
        )
        organizations = {
            str(org.id): org
            for org in (
                await self.db.execute(
                    select(OrgUnit).where(
                        OrgUnit.tenant_id == self.tenant_id, OrgUnit.is_deleted.is_(False)
                    )
                )
            )
            .scalars()
            .all()
        }
        return [
            owner
            for owner in candidates
            if has_permission(owner.role, Permission.ASSESSMENT_QUERY)
            and can_access_org_unit(owner, org_id, organizations)
        ]

    async def save_task(self, body: TaskCreate, task_id: str | None = None) -> AssessmentTask:
        """任务编辑不会自动完成指标；人工值须有依据并重新审核。"""
        _, school, _ = await self.scope(body.org_unit_id)
        rules = self._active_rules(await self._rules(str(school.id), body.year))
        rule = next((item for item in rules if item.code == body.indicator_code), None)
        if rule is None:
            raise HTTPException(422, "请选择当前已生效的年度指标")
        if body.owner_id not in {str(owner.id) for owner in await self._owners(body.org_unit_id)}:
            raise HTTPException(403, "责任人须为能够管理该组织的有效业务用户")
        if rule.source != "manual" and body.manual_value is not None:
            raise HTTPException(422, "自动归集指标不接受人工替换数值")
        values = body.model_dump(exclude={"expected_revision", "manual_value"})
        values["manual_value"] = str(body.manual_value) if body.manual_value is not None else None
        old = None
        if task_id:
            record = await self._get(AssessmentTask, task_id, lock=True)
            if not isinstance(body, TaskUpdate) or record.revision != body.expected_revision:
                raise HTTPException(409, "任务已被修改，请刷新后重试")
            if (
                record.org_unit_id != body.org_unit_id
                or record.year != body.year
                or record.indicator_code != body.indicator_code
            ):
                raise HTTPException(422, "修订任务不得更换组织、年度或指标")
            old = row_view(record)
            for key, value in values.items():
                setattr(record, key, value)
            record.revision += 1
            record.review_status, record.review_opinion = "pending", ""
            record.reviewed_by, record.reviewed_at = None, None
            # 修订人也必须经另一位组织人员核验。
            record.created_by = str(self.user.id)
        else:
            record = AssessmentTask(
                tenant_id=self.tenant_id,
                school_org_id=str(school.id),
                created_by=str(self.user.id),
                **values,
            )
            self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        await self._save_revision("tasks", record, "update" if task_id else "create", old=old)
        return record

    async def _evidence_views(self, evidence: list[AssessmentEvidence]) -> list[dict[str, Any]]:
        docs = {}
        for org_id in sorted({item.org_unit_id for item in evidence}):
            for doc in await authorized_documents(
                self.db,
                self.user,
                [row.doc_id for row in evidence if row.org_unit_id == org_id],
                org_unit_id=org_id,
            ):
                docs[(org_id, doc.doc_id)] = doc
        views = []
        for item in evidence:
            doc = docs.get((item.org_unit_id, item.doc_id))
            view = {
                "id": str(item.id),
                "org_unit_id": item.org_unit_id,
                "indicator_code": item.indicator_code,
                "requirement_key": item.requirement_key,
                "revision": item.revision,
                "review_status": item.review_status,
                "reviewed_by": item.reviewed_by,
                "reviewed_at": str(item.reviewed_at) if item.reviewed_at else None,
                "review_opinion": item.review_opinion if doc else "",
            }
            if doc is None:
                view.update(status="无权限或原材料已删除")
            else:
                status = item.review_status
                if doc.status != "effective" or (
                    doc.expiration_date and doc.expiration_date < date.today()
                ):
                    status = "已废止或失效"
                elif doc.effective_date > date.today():
                    status = "尚未生效"
                elif document_version(doc) != item.source_version:
                    status = "源文件已修订，须重新绑定及审核"
                view.update(
                    status=status,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    source_version=item.source_version,
                    created_by=item.created_by,
                    current_version=document_version(doc),
                    content_revision=(doc.doc_metadata or {}).get("content_revision", 1),
                )
            views.append(view)
        return views

    async def add_evidence(self, body: EvidenceCreate) -> AssessmentEvidence:
        """只绑定可访问真实文件；重新绑定新版本清除旧审核。"""
        _, school, _ = await self.scope(body.org_unit_id)
        rule = next(
            (
                rule
                for rule in self._active_rules(await self._rules(str(school.id), body.year))
                if rule.code == body.indicator_code
            ),
            None,
        )
        if rule is None or body.requirement_key not in rule.required_evidence:
            raise HTTPException(422, "佐证类别须属于当前指标的佐证清单")
        docs = await authorized_documents(
            self.db, self.user, [body.doc_id], org_unit_id=body.org_unit_id
        )
        if not docs:
            raise HTTPException(404, "材料不存在或无权访问")
        await self._lock_org(body.org_unit_id)
        record = (
            await self.db.execute(
                select(AssessmentEvidence)
                .where(
                    AssessmentEvidence.tenant_id == self.tenant_id,
                    AssessmentEvidence.org_unit_id == body.org_unit_id,
                    AssessmentEvidence.year == body.year,
                    AssessmentEvidence.indicator_code == body.indicator_code,
                    AssessmentEvidence.requirement_key == body.requirement_key,
                    AssessmentEvidence.doc_id == body.doc_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        version = document_version(docs[0])
        if record and record.source_version == version and not record.is_deleted:
            return record
        old = row_view(record) if record else None
        if record:
            record.source_version, record.is_deleted = version, False
            record.revision += 1
            record.created_by = str(self.user.id)
            record.review_status, record.review_opinion = "pending", ""
            record.reviewed_by, record.reviewed_at = None, None
        else:
            record = AssessmentEvidence(
                tenant_id=self.tenant_id,
                created_by=str(self.user.id),
                source_version=version,
                **body.model_dump(),
            )
            self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        await self._save_revision("evidence", record, "rebind" if old else "create", old=old)
        return record

    async def _calculate(
        self,
        rules: list[AssessmentIndicator],
        org_id: str,
        ids: set[str],
        tasks: list[AssessmentTask],
        evidence: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        results, snapshots = [], []
        for rule in rules:
            rule_data = {**row_view(rule), "org_unit_id": org_id}
            links = [
                item
                for item in evidence
                if item["indicator_code"] == rule.code and item["org_unit_id"] in ids
            ]
            if rule.source == "manual":
                manual = [
                    task
                    for task in tasks
                    if task.indicator_code == rule.code and task.org_unit_id in ids
                ]
                batch = SourceBatch(
                    tuple(
                        SourceRecord(
                            id=str(task.id),
                            tenant_id=self.tenant_id,
                            org_unit_id=task.org_unit_id,
                            occurred_on=task.completed_on or task.due_date,
                            version=str(task.revision),
                            status=task.review_status if task.completed_on else "pending",
                            value=task.manual_value if task.basis else None,
                            facts=(("basis_record", str(task.id)),),
                        )
                        for task in manual
                    ),
                    bool(manual),
                )
            else:
                batch = await load_source(self.db, self.user, rule_data, ids)
            results.append(
                calculate_indicator(
                    rule_data,
                    batch,
                    links,
                    tenant_id=self.tenant_id,
                    org_ids=ids,
                    as_of=date.today(),
                )
            )
            snapshots.append(
                {"rule": rule_data, "batch": _json(batch_snapshot(batch)), "evidence": links}
            )
        return results, snapshots

    async def collect(self, org_id: str, year: int) -> dict[str, Any]:
        """工作台总览与子组织任务分别计算，防止父级达标误完成子支部任务。"""
        selected, school, ids = await self.scope(org_id)
        all_rules = await self._rules(str(school.id), year)
        rules = self._active_rules(all_rules)
        tasks = list(
            (
                await self.db.execute(
                    select(AssessmentTask)
                    .where(
                        AssessmentTask.tenant_id == self.tenant_id,
                        AssessmentTask.org_unit_id.in_(ids),
                        AssessmentTask.year == year,
                        AssessmentTask.is_deleted.is_(False),
                    )
                    .order_by(AssessmentTask.due_date, AssessmentTask.id)
                )
            )
            .scalars()
            .all()
        )
        evidence = list(
            (
                await self.db.execute(
                    select(AssessmentEvidence)
                    .where(
                        AssessmentEvidence.tenant_id == self.tenant_id,
                        AssessmentEvidence.org_unit_id.in_(ids),
                        AssessmentEvidence.year == year,
                        AssessmentEvidence.is_deleted.is_(False),
                    )
                    .order_by(AssessmentEvidence.id)
                )
            )
            .scalars()
            .all()
        )
        evidence_views = await self._evidence_views(evidence)
        results, snapshots = await self._calculate(rules, org_id, ids, tasks, evidence_views)
        task_results = {org_id: results}
        for child in sorted({task.org_unit_id for task in tasks} - {org_id}):
            _, _, child_ids = await self.scope(child)
            task_results[child], child_snapshots = await self._calculate(
                rules, child, child_ids, tasks, evidence_views
            )
            snapshots.extend(child_snapshots)
        policy = await self.policy(str(school.id))
        advance = policy.reminder_advance_days if policy else 14
        task_views = [
            task_state(
                row_view(task),
                next(
                    (
                        result
                        for result in task_results[task.org_unit_id]
                        if result["code"] == task.indicator_code
                    ),
                    None,
                ),
                as_of=date.today(),
                advance_days=advance,
            )
            for task in tasks
        ]
        inputs = {
            "engine_version": ENGINE_VERSION,
            "as_of": date.today().isoformat(),
            "year": year,
            "org_unit_id": org_id,
            "org_ids": sorted(ids),
            "sources": snapshots,
            "tasks": [row_view(task) for task in tasks],
        }
        return {
            "selected": selected,
            "school": school,
            "inputs": inputs,
            "fingerprint": fingerprint(inputs),
            "rules": rules,
            "all_rules": all_rules,
            "results": results,
            "tasks": task_views,
            "evidence": evidence_views,
            "policy": policy,
        }

    async def _runs(self, org_id: str, year: int) -> list[AssessmentRun]:
        return list(
            (
                await self.db.execute(
                    select(AssessmentRun)
                    .where(
                        AssessmentRun.tenant_id == self.tenant_id,
                        AssessmentRun.org_unit_id == org_id,
                        AssessmentRun.year == year,
                        AssessmentRun.is_deleted.is_(False),
                    )
                    .order_by(AssessmentRun.created_at.desc(), AssessmentRun.id)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )

    async def _latest_plan(self, org_id: str, year: int) -> AssessmentPlan | None:
        return (
            await self.db.execute(
                select(AssessmentPlan)
                .where(
                    AssessmentPlan.tenant_id == self.tenant_id,
                    AssessmentPlan.org_unit_id == org_id,
                    AssessmentPlan.year == year,
                    AssessmentPlan.is_deleted.is_(False),
                )
                .order_by(AssessmentPlan.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def workspace(self, org_id: str, year: int) -> dict[str, Any]:
        """实时检查输入变动，旧快照/计划不通过当前权限返回旧材料内容。"""
        data = await self.collect(org_id, year)
        runs = await self._runs(org_id, year)
        current = next((run for run in runs if run.fingerprint == data["fingerprint"]), None)
        if current is None:
            current = (
                await self.db.execute(
                    select(AssessmentRun).where(
                        AssessmentRun.tenant_id == self.tenant_id,
                        AssessmentRun.org_unit_id == org_id,
                        AssessmentRun.year == year,
                        AssessmentRun.fingerprint == data["fingerprint"],
                        AssessmentRun.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if current is not None:
                runs.insert(0, current)
        plan = await self._latest_plan(org_id, year)
        plan_data = row_view(plan) if plan else None
        if plan:
            run = await self._get(AssessmentRun, plan.run_id)
            plan_data["stale"] = run.fingerprint != data["fingerprint"]
            if plan_data["stale"]:
                plan_data["content"] = None
                plan_data["review_opinion"] = ""
        reminders = list(
            (
                await self.db.execute(
                    select(AssessmentReminder)
                    .where(
                        AssessmentReminder.tenant_id == self.tenant_id,
                        AssessmentReminder.org_unit_id.in_(data["inputs"]["org_ids"]),
                        AssessmentReminder.year == year,
                        AssessmentReminder.owner_id == str(self.user.id),
                        AssessmentReminder.is_deleted.is_(False),
                    )
                    .order_by(AssessmentReminder.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        shared_policy = await archive_policy(self.db, self.tenant_id)
        policy_data = (
            row_view(data["policy"])
            if data["policy"]
            else {"version": 0, "reminder_advance_days": 14}
        )
        policy_data.update(
            archive_enabled=shared_policy.get("enabled") is True,
            archive_version=shared_policy.get("revision", 0),
            confirmation_note=shared_policy.get("evidence", ""),
        )
        return {
            "org_unit_id": org_id,
            "org_name": data["selected"].name,
            "school_org_id": str(data["school"].id),
            "year": year,
            "as_of": date.today().isoformat(),
            "fingerprint": data["fingerprint"],
            "engine_version": ENGINE_VERSION,
            "indicators": [
                {**row_view(rule), "active": rule in data["rules"]} for rule in data["all_rules"]
            ],
            "results": data["results"],
            "tasks": data["tasks"],
            "evidence": data["evidence"],
            "owners": [
                {"id": str(owner.id), "name": owner.name} for owner in await self._owners(org_id)
            ],
            "runs": [
                {
                    **run_view(run),
                    "review_opinion": (
                        run.review_opinion if run.fingerprint == data["fingerprint"] else ""
                    ),
                    "stale": run.fingerprint != data["fingerprint"],
                }
                for run in runs
            ],
            "plan": plan_data,
            "policy": policy_data,
            "reminders": [row_view(reminder) for reminder in reminders],
            "needs_recalculation": current is None,
            "notices": [
                "真实学校指标及人工台账对照尚待组织人员验收。",
                "上游缺失、待审核或无权限数据列为缺项；人员材料名称不能替代已核验文件。",
                "规则比较和计划仅供组织人员研究，正式评价须人工审核。",
            ],
        }

    async def recalculate(self, org_id: str, year: int) -> AssessmentRun:
        """锁组织行并复用相同输入快照，多次归集不产生重复业务数据。"""
        await self.scope(org_id)
        await self._lock_org(org_id)
        data = await self.collect(org_id, year)
        if not data["rules"]:
            raise HTTPException(422, "本年度尚无已生效指标，请先维护学校指标")
        run = (
            await self.db.execute(
                select(AssessmentRun).where(
                    AssessmentRun.tenant_id == self.tenant_id,
                    AssessmentRun.org_unit_id == org_id,
                    AssessmentRun.year == year,
                    AssessmentRun.fingerprint == data["fingerprint"],
                )
            )
        ).scalar_one_or_none()
        if run is None:
            run = AssessmentRun(
                tenant_id=self.tenant_id,
                org_unit_id=org_id,
                school_org_id=str(data["school"].id),
                year=year,
                fingerprint=data["fingerprint"],
                engine_version=ENGINE_VERSION,
                inputs=data["inputs"],
                results=data["results"],
                created_by=str(self.user.id),
            )
            self.db.add(run)
            await self.db.flush()
            await self._save_revision("runs", run, "create")
        await self.sync_reminders(org_id, year, data=data)
        return run

    async def fresh_run(
        self, run_id: str, *, lock: bool = False
    ) -> tuple[AssessmentRun, dict[str, Any]]:
        """导出、审核、归档都重新核对当前权限和输入，不信任历史快照。"""
        run = await self._get(AssessmentRun, run_id, lock=lock)
        data = await self.collect(run.org_unit_id, run.year)
        if run.fingerprint != data["fingerprint"]:
            raise HTTPException(409, "规则、源记录或权限已变化，请先重新归集")
        return run, data

    async def historical_run(self, run_id: str) -> dict[str, Any]:
        """保留历史数值与规则；失去来源权限/记录时隐藏旧数值和引用。"""
        run = await self._get(AssessmentRun, run_id)
        live = await self.collect(run.org_unit_id, run.year)
        authorized = await authorized_historical_sources(
            self.db,
            self.user,
            [item for result in run.results for item in result["sources"]],
            set(live["inputs"]["org_ids"]),
        )
        links = {item["id"]: item for item in live["evidence"]}
        scope_changed = not set(run.inputs["org_ids"]) <= set(live["inputs"]["org_ids"])
        results, restricted = [], False
        for saved in run.results:
            result = dict(saved)
            permitted_sources = [
                item
                for item in saved["sources"]
                if (item["source"], item["record_id"]) in authorized
            ]
            permitted_evidence = [
                item for item in saved["evidence"] if links.get(item["id"], {}).get("doc_id")
            ]
            hidden = (
                scope_changed
                or len(permitted_sources) != len(saved["sources"])
                or len(permitted_evidence) != len(saved["evidence"])
            )
            if hidden:
                result.update(
                    actual=None,
                    satisfied=None,
                    sources=[],
                    evidence=[],
                    missing=["历史来源已删除、转接或当前无权核查，旧数值及引用已隐藏"],
                )
            restricted |= hidden
            results.append(result)
        return {
            **run_view(run),
            "review_opinion": "" if restricted else run.review_opinion,
            "results": results,
            "stale": run.fingerprint != live["fingerprint"],
            "notice": "历史归集仅供核查版本；正式导出、审核及归档须使用与当前数据一致的归集。",
        }

    async def review(self, kind: str, record_id: str, body: ReviewRequest) -> Any:
        """每次审核读取当前源版本；录入人/修订人不能自行审核。"""
        models = {
            "tasks": AssessmentTask,
            "evidence": AssessmentEvidence,
            "runs": AssessmentRun,
            "plans": AssessmentPlan,
        }
        if kind not in models:
            raise HTTPException(404, "审核对象不存在")
        record = await self._get(models[kind], record_id, lock=True)
        if record.created_by == str(self.user.id):
            raise HTTPException(403, "录入或修订人须提交另一位授权人员审核")
        if record.revision != body.expected_revision:
            raise HTTPException(409, "对象已被修改，请刷新后重新审核")
        if kind == "plans":
            await self.fresh_run(record.run_id)
        if body.status == "approved":
            if kind == "tasks":
                if record.manual_value is not None and not record.basis:
                    raise HTTPException(409, "人工值缺少录入依据")
            elif kind == "evidence":
                view = (await self._evidence_views([record]))[0]
                if view["status"] not in {"pending", "returned", "approved"}:
                    raise HTTPException(409, "材料无效、越权或已更新，须重新绑定有效版本")
            else:
                if kind == "runs":
                    _, data = await self.fresh_run(record.id)
                    if any(result["missing"] for result in data["results"]):
                        raise HTTPException(409, "归集仍有缺项，补齐并重算后才能确认评价")
                if kind == "plans":
                    latest = await self._latest_plan(record.org_unit_id, record.year)
                    if latest.id != record.id:
                        raise HTTPException(409, "该计划已修订，请审核最新版本")
        old = row_view(record)
        record.review_status, record.review_opinion = body.status, body.opinion
        record.reviewed_by, record.reviewed_at = str(self.user.id), utc_now()
        record.revision += 1
        await self.db.flush()
        await self.db.refresh(record)
        await self._save_revision(kind, record, "review", old=old)
        return record

    async def create_plan(self, body: PlanCreate) -> AssessmentPlan:
        """用授权指标/任务生成确定性草案，数据不足保留待补，支持人工改写。"""
        run, data = await self.fresh_run(body.run_id)
        await self._lock_org(run.org_unit_id)
        latest = await self._latest_plan(run.org_unit_id, run.year)
        version = latest.version if latest else 0
        if version != body.expected_version:
            raise HTTPException(409, "计划已被修订，请刷新后重试")
        lines = [
            f"{run.year}年度{data['selected'].name}党建工作计划（参考草案）",
            "供组织人员研究确定；不构成正式考核结论。",
            "",
        ]
        for result in data["results"]:
            actual = "待补" if result["actual"] is None else str(result["actual"])
            lines.extend(
                [
                    f"{result['code']} {result['name']}：{result['requirement']}",
                    f"统计期间 {result['period_start']} 至 {result['period_end']}；"
                    f"当前 {actual}{result['unit']}，目标 {result['target']}{result['unit']}。",
                ]
            )
            relevant = [task for task in data["tasks"] if task["indicator_code"] == result["code"]]
            if relevant:
                lines.extend(
                    f"- {task['title']}；责任用户 {task['owner_id']}；"
                    f"期限 {task['due_date']}；进度 {task['progress']}%。"
                    for task in relevant
                )
            else:
                lines.append("- 工作任务、责任人和时间安排待补，提交人工研究。")
            if result["missing"]:
                lines.append("待补：" + "；".join(result["missing"]))
            lines.append("")
        plan = AssessmentPlan(
            tenant_id=self.tenant_id,
            org_unit_id=run.org_unit_id,
            year=run.year,
            version=version + 1,
            run_id=str(run.id),
            content=body.content or "\n".join(lines),
            created_by=str(self.user.id),
        )
        self.db.add(plan)
        await self.db.flush()
        await self._save_revision("plans", plan, "create")
        return plan

    async def sync_reminders(
        self, org_id: str, year: int, *, data: dict | None = None
    ) -> list[AssessmentReminder]:
        """自动/手动扫描共用去重台账；责任或期限修改后旧提醒标为已失效。"""
        await self.scope(org_id)
        await self._lock_org(org_id)
        data = data or await self.collect(org_id, year)
        desired: dict[str, tuple[dict, str]] = {}
        for task in data["tasks"]:
            if task["complete"]:
                continue
            kinds = []
            if task["overdue"]:
                kinds.append("overdue")
            elif task["due_soon"]:
                kinds.append("due_soon")
            if task["missing"]:
                kinds.append("missing_evidence")
            for kind in kinds:
                key = fingerprint([task["id"], task["owner_id"], task["due_date"], kind])
                desired[key] = (task, kind)
        existing = list(
            (
                await self.db.execute(
                    select(AssessmentReminder)
                    .where(
                        AssessmentReminder.tenant_id == self.tenant_id,
                        AssessmentReminder.year == year,
                        AssessmentReminder.org_unit_id.in_(data["inputs"]["org_ids"]),
                    )
                    .order_by(AssessmentReminder.dedup_key)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        indexed = {item.dedup_key: item for item in existing}
        for item in existing:
            if item.status in {"open", "handled"} and item.dedup_key not in desired:
                old = row_view(item)
                item.status = "resolved"
                await self._save_revision("reminders", item, "resolve", old=old)
        for key, (task, kind) in desired.items():
            if key in indexed:
                if indexed[key].status == "resolved":
                    item = indexed[key]
                    old = row_view(item)
                    item.status, item.handled_at, item.handled_by = "open", None, None
                    item.handling_note = ""
                    await self._save_revision("reminders", item, "reopen", old=old)
                continue
            values = {
                "tenant_id": self.tenant_id,
                "task_id": task["id"],
                "org_unit_id": task["org_unit_id"],
                "year": year,
                "owner_id": task["owner_id"],
                "kind": kind,
                "dedup_key": key,
            }
            # 学校与子支部扫描可能重叠；数据库唯一键处理多个进程间的去重。
            statement = (
                insert(AssessmentReminder)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["tenant_id", "dedup_key"])
                .returning(AssessmentReminder.id)
            )
            record_id = (await self.db.execute(statement)).scalar_one_or_none()
            if record_id:
                item = (
                    await self.db.execute(
                        select(AssessmentReminder).where(
                            AssessmentReminder.id == record_id,
                            AssessmentReminder.tenant_id == self.tenant_id,
                        )
                    )
                ).scalar_one()
                existing.append(item)
                await self._save_revision("reminders", item, "create")
        await self.db.flush()
        return existing

    async def handle_reminder(self, record_id: str, note: str) -> AssessmentReminder:
        record = await self._get(AssessmentReminder, record_id, lock=True)
        if record.owner_id != str(self.user.id):
            raise HTTPException(403, "仅当前责任人可登记提醒处理结果")
        if record.status != "open":
            raise HTTPException(409, "提醒已处理或已失效，请刷新任务状态")
        old = row_view(record)
        record.status, record.handling_note = "handled", note
        record.handled_by, record.handled_at = str(self.user.id), utc_now()
        await self.db.flush()
        await self.db.refresh(record)
        await self._save_revision("reminders", record, "handle", old=old)
        return record

    async def archive(self, run_id: str) -> AssessmentArchive:
        """只归档已审核且仍有效的佐证目录，合规确认默认拒绝。"""
        run, data = await self.fresh_run(run_id, lock=True)
        policy = await require_archive_policy(self.db, self.tenant_id)
        if run.review_status != "approved" or any(result["missing"] for result in data["results"]):
            raise HTTPException(409, "归集评价须先经人工审核，佐证缺项须补齐")
        record = (
            await self.db.execute(
                select(AssessmentArchive).where(
                    AssessmentArchive.tenant_id == self.tenant_id,
                    AssessmentArchive.run_id == run_id,
                )
            )
        ).scalar_one_or_none()
        if record is None:
            record = AssessmentArchive(
                tenant_id=self.tenant_id,
                org_unit_id=run.org_unit_id,
                year=run.year,
                run_id=run_id,
                policy_version=policy["revision"],
                created_by=str(self.user.id),
                manifest={
                    "fingerprint": run.fingerprint,
                    "engine_version": run.engine_version,
                    "reviewed_by": run.reviewed_by,
                    "reviewed_at": str(run.reviewed_at),
                    "policy_confirmation": {
                        "version": policy["revision"],
                        "by": policy["confirmed_by"],
                        "at": policy["confirmed_at"],
                    },
                    "evidence": data["evidence"],
                    "sources": [result["sources"] for result in data["results"]],
                },
            )
            self.db.add(record)
            await self.db.flush()
        return record

    async def export(self, run_id: str) -> tuple[bytes, dict[str, Any]]:
        """当前权限下导出表和来源目录；草稿/缺项明示，CSV防公式注入。"""
        run, data = await self.fresh_run(run_id)
        payload = {
            "run": run_view(run),
            "results": data["results"],
            "tasks": data["tasks"],
            "evidence": data["evidence"],
            "label": "已人工审核" if run.review_status == "approved" else "待人工审核的考核草案",
            "as_of": date.today().isoformat(),
            "scope": run.org_unit_id,
            "notice": "仅含授权数据和佐证目录；真实指标、组织人工台账对照待验收。原文件下载与加密存储依赖知识库/安全模块。",
        }
        indicators = [
            [
                result["code"],
                result["name"],
                result["rule_version"],
                result["requirement"],
                "待补" if result["actual"] is None else result["actual"],
                result["target"],
                (
                    "待核验"
                    if result["satisfied"] is None
                    else ("满足规则" if result["satisfied"] else "未满足规则")
                ),
                "；".join(result["missing"]),
                payload["label"],
            ]
            for result in data["results"]
        ]
        tasks = [
            [
                task["id"],
                task["title"],
                task["indicator_code"],
                task["owner_id"],
                task["due_date"],
                task["progress"],
                "完成" if task["complete"] else "待完成",
                "是" if task["overdue"] else "否",
                "；".join(task["missing"]),
                task["review_status"],
                task["basis"],
            ]
            for task in data["tasks"]
        ]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr(
                "indicators.csv",
                csv_bytes(
                    [
                        "指标编码",
                        "名称",
                        "规则版本",
                        "要求",
                        "实际值",
                        "目标",
                        "规则比较",
                        "缺项",
                        "审核标识",
                    ],
                    indicators,
                ),
            )
            package.writestr(
                "tasks.csv",
                csv_bytes(
                    [
                        "任务编号",
                        "任务",
                        "指标",
                        "责任用户",
                        "期限",
                        "进度",
                        "状态",
                        "逾期",
                        "缺项",
                        "审核",
                        "录入依据",
                    ],
                    tasks,
                ),
            )
            package.writestr(
                "evidence.json", json.dumps(data["evidence"], ensure_ascii=False, indent=2)
            )
            package.writestr("assessment.json", json.dumps(payload, ensure_ascii=False, indent=2))
            plan = await self._latest_plan(run.org_unit_id, run.year)
            if plan and plan.run_id == run.id:
                package.writestr(
                    "plan.txt",
                    f"计划v{plan.version}；审核状态：{plan.review_status}\n{plan.content}",
                )
        return buffer.getvalue(), {
            "run_id": run_id,
            "fingerprint": run.fingerprint,
            "indicator_count": len(data["results"]),
            "task_count": len(tasks),
            "evidence_count": len(data["evidence"]),
        }


def csv_bytes(headers: list[str], rows: list[list[Any]]) -> bytes:
    """UTF-8 BOM供Excel打开，危险首字符转为文本，未知值保留待补标签。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        cells = []
        for value in row:
            text = str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(
                ("\t", "\r", "\n")
            ):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return output.getvalue().encode("utf-8-sig")
