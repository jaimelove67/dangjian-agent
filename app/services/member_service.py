"""发展党员全流程业务闭环；阶段流转仅人工操作，规则建议不写入阶段字段。

所有读写带租户及有效组织范围；流转校验复用 business_rules 阶段规则与材料要求，
评分与档案检查仅输出辅助结果并保留证据来源，不自动形成组织认定。
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import yaml
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import tenant_config
from app.core.decision_boundary import ASSISTED_REFERENCE_NOTE, STAGE_TRANSITION_NOTE, evidence_note
from app.models.meeting import ContentRevision
from app.models.member import (
    MemberArchiveCheck,
    MemberBatch,
    MemberCultivation,
    MemberMaterial,
    MemberProfile,
    MemberReminder,
    MemberStageHistory,
    MemberVote,
)
from app.models.user import User
from app.rules.data_sensitivity import (
    annotate_level,
    material_level,
    redact_third_party,
    viewer_level,
    vote_level,
)
from app.rules.member_stages import STAGE_LABELS, MemberStage, StageRules, load_stage_rules
from app.schemas.member_ext import (
    ArchiveCheckRun,
    BatchCreate,
    CultivationCreate,
    MaterialCreate,
    MaterialReview,
    ProfileUpdate,
    ReminderResolve,
    ScoringRequest,
    TransitionRequest,
    VoteBatch,
)
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

DECISION_BOUNDARY = STAGE_TRANSITION_NOTE
BATCH_RULES_PATH = "config/business_rules.yaml"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_scoring_rules() -> dict[str, Any]:
    """评分维度权重与风险项，来自 business_rules.yaml。"""
    try:
        with open(BATCH_RULES_PATH, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError:
        data = {}
    rules = data.get("scoring_rules") or {}
    weights = rules.get("weights") or {}
    return {
        "weights": {
            str(key): float(value)
            for key, value in weights.items()
            if isinstance(value, (int, float))
        },
        "risk_items": list(rules.get("risk_items") or []),
    }


def _load_reminder_rules() -> dict[str, Any]:
    try:
        with open(BATCH_RULES_PATH, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError:
        data = {}
    return data.get("reminder_rules") or {}


class MemberDevelopment:
    """在请求事务内完成发展业务，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.rules: StageRules = load_stage_rules()
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []

    async def initialize(self) -> "MemberDevelopment":
        self.orgs = await visible_org_units(self.db, self.user)
        self.org_ids = [str(org.id) for org in self.orgs]
        return self

    def _scope(self, model: Any) -> list[Any]:
        return [
            model.tenant_id == self.tenant_id,
            model.is_deleted.is_(False),
            model.org_unit_id.in_(self.org_ids),
        ]

    async def profile(self, profile_id: str, *, lock: bool = False) -> MemberProfile:
        stmt = select(MemberProfile).where(
            *self._scope(MemberProfile), MemberProfile.id == profile_id
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        profile = (await self.db.execute(stmt)).scalar_one_or_none()
        if profile is None:
            raise HTTPException(404, "培养对象不存在或无权访问")
        return profile

    # ==================== 年度与批次 ====================

    async def create_batch(self, body: BatchCreate) -> MemberBatch:
        if body.org_unit_id not in self.org_ids:
            raise HTTPException(403, "请选择权限范围内有效的组织")
        existing = await self.db.scalar(
            select(MemberBatch.id).where(
                MemberBatch.tenant_id == self.tenant_id,
                MemberBatch.year == body.year,
                MemberBatch.batch_no == body.batch_no,
            )
        )
        if existing:
            raise HTTPException(409, "该年度批次已存在，请沿用既有批次")
        org = next(org for org in self.orgs if str(org.id) == body.org_unit_id)
        batch = MemberBatch(
            tenant_id=self.tenant_id,
            year=body.year,
            batch_no=body.batch_no,
            label=body.label,
            org_unit_id=str(org.id),
            org_name=org.name,
        )
        self.db.add(batch)
        await self.db.flush()
        return batch

    async def list_batches(
        self, *, year: int | None, org_unit_id: str | None, page: int, page_size: int
    ) -> dict[str, Any]:
        conditions = self._scope(MemberBatch)
        if year:
            conditions.append(MemberBatch.year == year)
        if org_unit_id:
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "无权查询该组织")
            conditions.append(MemberBatch.org_unit_id == org_unit_id)
        total = await self.db.scalar(select(func.count(MemberBatch.id)).where(*conditions))
        batches = (
            (
                await self.db.execute(
                    select(MemberBatch)
                    .where(*conditions)
                    .order_by(MemberBatch.year.desc(), MemberBatch.batch_no, MemberBatch.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        items = []
        for batch in batches:
            count = await self.db.scalar(
                select(func.count(MemberProfile.id)).where(
                    *self._scope(MemberProfile),
                    MemberProfile.batch_no == batch.batch_no,
                    MemberProfile.year == batch.year,
                )
            )
            items.append({**row_data(batch), "member_count": count or 0})
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def update_profile(self, profile_id: str, body: ProfileUpdate) -> MemberProfile:
        profile = await self.profile(profile_id, lock=True)
        if body.batch_no is not None:
            if not body.batch_no:
                raise HTTPException(422, "批次号不能为空")
            batch = await self.db.scalar(
                select(MemberBatch.id).where(
                    MemberBatch.tenant_id == self.tenant_id,
                    MemberBatch.batch_no == body.batch_no,
                    MemberBatch.year == (body.year or profile.year or date.today().year),
                )
            )
            if not batch:
                raise HTTPException(422, "请先建立年度批次，或选择既有批次")
        if body.name is not None:
            profile.name = body.name
        if body.batch_no is not None:
            profile.batch_no = body.batch_no
        if body.year is not None:
            profile.year = body.year
        if body.is_active is not None:
            profile.is_active = body.is_active
        await self.save_profile_revision(profile, "revise", body.reason)
        return profile

    async def save_profile_revision(self, profile: MemberProfile, action: str, reason: str) -> None:
        latest = await self.db.scalar(
            select(func.max(ContentRevision.revision)).where(
                ContentRevision.tenant_id == self.tenant_id,
                ContentRevision.resource_type == "member_profile",
                ContentRevision.resource_id == str(profile.id),
            )
        )
        revision = (latest or 0) + 1
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type="member_profile",
                resource_id=str(profile.id),
                revision=revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=row_data(profile),
            )
        )
        await self.db.flush()

    # ==================== 材料记录 ====================

    async def add_material(self, profile_id: str, body: MaterialCreate) -> MemberMaterial:
        profile = await self.profile(profile_id, lock=True)
        material = MemberMaterial(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            stage=body.stage or profile.current_stage,
            material_type=body.material_type,
            data_level=material_level(body.material_type).value,
            file_version=body.file_version,
            submit_date=body.submit_date or date.today(),
            submitter_id=str(self.user.id),
            review_status="pending",
        )
        self.db.add(material)
        await self.db.flush()
        return material

    def material_view(self, material: Any) -> dict[str, Any]:
        """材料写入后的回显口径：带密级与出网 / 向量化标注。

        第三人字段正文**不在这里脱敏**：写材料 / 写审核备注的人看到的是自己刚录的内容，
        对写入动作的留痕（审计快照）也应当是真实内容；按查看者等级收敛只发生在读取出口
        ``list_materials``。
        """
        data = row_data(material)
        level = data.get("data_level") or material_level(data.get("material_type")).value
        data.update(annotate_level(level))
        return data

    async def list_materials(self, profile_id: str) -> list[dict[str, Any]]:
        profile = await self.profile(profile_id)
        records = (
            (
                await self.db.execute(
                    select(MemberMaterial)
                    .where(
                        MemberMaterial.tenant_id == self.tenant_id,
                        MemberMaterial.profile_id == str(profile.id),
                        MemberMaterial.is_deleted.is_(False),
                    )
                    .order_by(MemberMaterial.submit_date, MemberMaterial.id)
                )
            )
            .scalars()
            .all()
        )
        items = [row_data(record) for record in records]
        if records:
            revisions = (
                (
                    await self.db.execute(
                        select(ContentRevision)
                        .where(
                            ContentRevision.tenant_id == self.tenant_id,
                            ContentRevision.resource_type == "member_material",
                            ContentRevision.resource_id.in_([str(record.id) for record in records]),
                            ContentRevision.is_deleted.is_(False),
                        )
                        .order_by(ContentRevision.revision)
                    )
                )
                .scalars()
                .all()
            )
            for item in items:
                item["review_history"] = [
                    row_data(revision)
                    for revision in revisions
                    if revision.resource_id == item["id"]
                ]
        # 旧材料名称升级为“待核验”，不虚构原始文件或通过状态。
        for legacy in profile.materials or []:
            if not any(item["material_type"] == legacy for item in items):
                items.append(
                    {
                        "legacy_material": True,
                        "material_type": legacy,
                        "review_status": "pending",
                        "note": "历史材料名称，待组织人员核验原始文件后归档",
                    }
                )
        # 字段级敏感分级（T-MEM-12）：密级高于查看者时不返回第三人字段正文（含留痕快照）。
        viewer = viewer_level(self.user)
        for index, item in enumerate(items):
            level = item.get("data_level") or material_level(item.get("material_type")).value
            masked, redacted = redact_third_party(item, level=level, viewer=viewer)
            masked.update(annotate_level(level))
            masked["redacted_fields"] = redacted
            items[index] = masked
        return items

    async def review_material(self, material_id: str, body: MaterialReview) -> MemberMaterial:
        material = (
            await self.db.execute(
                select(MemberMaterial)
                .where(*self._scope(MemberMaterial), MemberMaterial.id == material_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if material is None:
            raise HTTPException(404, "材料记录不存在或无权访问")
        latest = await self.db.scalar(
            select(func.max(ContentRevision.revision)).where(
                ContentRevision.tenant_id == self.tenant_id,
                ContentRevision.resource_type == "member_material",
                ContentRevision.resource_id == material_id,
            )
        )
        if latest is None:
            latest = 1
            self.db.add(
                ContentRevision(
                    tenant_id=self.tenant_id,
                    resource_type="member_material",
                    resource_id=material_id,
                    revision=latest,
                    action="baseline",
                    actor_id=str(self.user.id),
                    reason="保存首次审核前状态，既往审核来源待核验",
                    snapshot=row_data(material),
                )
            )
        material.review_status = body.review_status
        material.note = body.note
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type="member_material",
                resource_id=material_id,
                revision=latest + 1,
                action="review",
                actor_id=str(self.user.id),
                reason=body.reason,
                snapshot=row_data(material),
            )
        )
        await self.db.flush()
        return material

    # ==================== 人工阶段流转 ====================

    async def transition(self, profile_id: str, body: TransitionRequest) -> MemberProfile:
        profile = await self.profile(profile_id, lock=True)
        try:
            rule = self.rules.get_rule(
                MemberStage(profile.current_stage), MemberStage(body.target_stage)
            )
        except ValueError:
            raise HTTPException(422, "人员阶段无效，须先核验历史记录") from None
        if rule is None:
            raise HTTPException(
                422,
                f"不允许的流转：{stage_label(profile.current_stage)}"
                f" → {stage_label(body.target_stage)}",
            )
        if body.decision_date < profile.stage_joined_on:
            raise HTTPException(422, "决策日期不能早于进入当前阶段日期")
        if body.decision_date > date.today():
            raise HTTPException(422, "决策日期不能晚于今天")
        approved = set(
            (
                await self.db.execute(
                    select(MemberMaterial.material_type).where(
                        MemberMaterial.tenant_id == self.tenant_id,
                        MemberMaterial.profile_id == str(profile.id),
                        MemberMaterial.review_status == "approved",
                        MemberMaterial.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        missing = [name for name in rule.required_materials if name not in approved]
        if missing:
            raise HTTPException(422, "材料未齐或未核验通过：" + "、".join(missing))
        if rule.min_days > 0:
            stayed = (body.decision_date - profile.stage_joined_on).days
            if stayed < rule.min_days:
                raise HTTPException(422, f"未满足最短时限：需 {rule.min_days} 天，当前 {stayed} 天")
        history = MemberStageHistory(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            from_stage=profile.current_stage,
            to_stage=body.target_stage,
            decision_date=body.decision_date,
            basis=body.basis,
            opinion=body.opinion,
            decided_by=str(self.user.id),
        )
        self.db.add(history)
        profile.current_stage = body.target_stage
        profile.stage_joined_on = body.decision_date
        await self.db.flush()
        return profile

    async def stage_history(self, profile_id: str) -> list[dict[str, Any]]:
        profile = await self.profile(profile_id)
        history = (
            (
                await self.db.execute(
                    select(MemberStageHistory)
                    .where(
                        MemberStageHistory.tenant_id == self.tenant_id,
                        MemberStageHistory.profile_id == str(profile.id),
                        MemberStageHistory.is_deleted.is_(False),
                    )
                    .order_by(MemberStageHistory.decision_date, MemberStageHistory.id)
                )
            )
            .scalars()
            .all()
        )
        return [row_data(record) for record in history]

    # ==================== 提醒台账 ====================

    def _due_reminders(self, profile: MemberProfile) -> list[tuple[str, date]]:
        """按阶段时限生成到期与提前提醒；规则来自 business_rules.yaml。"""
        config = _load_reminder_rules()
        plan = {
            "activist": {
                "training_period": ("training_period", 365),
                "material_submission": ("material_submission", 365),
            },
            "candidate": {"meeting_discussion": ("meeting_discussion", 90)},
            "probationary": {
                "probationary_expiration": ("probationary_expiration", 365),
                "material_submission": ("material_submission", 365),
            },
        }
        result: list[tuple[str, date]] = []
        for kind, (config_key, limit_days) in plan.get(profile.current_stage, {}).items():
            settings = config.get(config_key) or {}
            if settings.get("enabled", True) is False:
                continue
            try:
                advance = int(settings.get("advance_days", 30))
            except (TypeError, ValueError):
                advance = 30
            expire = profile.stage_joined_on + timedelta(days=limit_days)
            result.append((kind, expire))
            if advance > 0:
                result.append((kind + "_advance", expire - timedelta(days=advance)))
        return result

    async def sync_reminders(self, profile: MemberProfile) -> list[MemberReminder]:
        created: list[MemberReminder] = []
        for kind, due_on in self._due_reminders(profile):
            existing = await self.db.scalar(
                select(MemberReminder.id).where(
                    MemberReminder.tenant_id == self.tenant_id,
                    MemberReminder.profile_id == str(profile.id),
                    MemberReminder.kind == kind,
                    MemberReminder.due_on == due_on,
                )
            )
            if existing:
                continue
            reminder = MemberReminder(
                tenant_id=self.tenant_id,
                profile_id=str(profile.id),
                org_unit_id=profile.org_unit_id or "",
                kind=kind,
                due_on=due_on,
            )
            self.db.add(reminder)
            created.append(reminder)
        await self.db.flush()
        return created

    async def scan_all_reminders(self) -> int:
        """调度扫描：为范围内全部培养对象补齐提醒，重复运行不去重不重复写入。"""
        profiles = (
            (await self.db.execute(select(MemberProfile).where(*self._scope(MemberProfile))))
            .scalars()
            .all()
        )
        created = 0
        for profile in profiles:
            created += len(await self.sync_reminders(profile))
        return created

    async def reminders(
        self, *, org_unit_id: str | None, status: str | None, page: int, page_size: int
    ) -> dict[str, Any]:
        conditions = self._scope(MemberReminder)
        if org_unit_id:
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "无权查询该组织")
            conditions.append(MemberReminder.org_unit_id == org_unit_id)
        if status:
            conditions.append(MemberReminder.status == status)
        total = await self.db.scalar(select(func.count(MemberReminder.id)).where(*conditions))
        reminders = (
            (
                await self.db.execute(
                    select(MemberReminder)
                    .where(*conditions)
                    .order_by(MemberReminder.due_on, MemberReminder.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [row_data(item) for item in reminders],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def resolve_reminder(self, reminder_id: str, body: ReminderResolve) -> MemberReminder:
        reminder = (
            await self.db.execute(
                select(MemberReminder).where(
                    *self._scope(MemberReminder), MemberReminder.id == reminder_id
                )
            )
        ).scalar_one_or_none()
        if reminder is None:
            raise HTTPException(404, "提醒不存在或无权访问")
        if reminder.status != "open":
            raise HTTPException(409, "提醒已处理，不能重复操作")
        reminder.status = body.status
        reminder.processed_by = str(self.user.id)
        reminder.processed_at = utc_now()
        reminder.note = body.note
        return reminder

    # ==================== 培养与表现数据 ====================

    async def add_cultivation(
        self, body: CultivationCreate, profile_id: str | None = None
    ) -> MemberCultivation:
        target_id = profile_id or body.profile_id
        profile = await self.profile(target_id)
        record = MemberCultivation(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            category=body.category,
            score=body.score,
            period=body.period,
            source_note=body.source_note,
            verified_by=str(self.user.id),
            verified_at=utc_now(),
            is_risk=body.is_risk,
            risk_note=body.risk_note,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def cultivation(self, profile_id: str) -> list[dict[str, Any]]:
        profile = await self.profile(profile_id)
        records = (
            (
                await self.db.execute(
                    select(MemberCultivation)
                    .where(
                        MemberCultivation.tenant_id == self.tenant_id,
                        MemberCultivation.profile_id == str(profile.id),
                        MemberCultivation.is_deleted.is_(False),
                    )
                    .order_by(MemberCultivation.created_at, MemberCultivation.id)
                )
            )
            .scalars()
            .all()
        )
        return [row_data(record) for record in records]

    # ==================== 多轮选优投票 ====================

    async def submit_votes(self, body: VoteBatch) -> dict[str, Any]:
        for entry in body.votes:
            await self.profile(entry.profile_id)
        existing = await self.db.scalar(
            select(MemberVote.id).where(
                MemberVote.tenant_id == self.tenant_id,
                MemberVote.batch_no == body.batch_no,
                MemberVote.round_no == body.round_no,
                MemberVote.voter_id == str(self.user.id),
                MemberVote.is_deleted.is_(False),
            )
        )
        if existing:
            raise HTTPException(409, "同一投票人本轮已投票，不能重复提交")
        rows = [
            MemberVote(
                tenant_id=self.tenant_id,
                batch_no=body.batch_no,
                round_no=body.round_no,
                profile_id=entry.profile_id,
                voter_id=str(self.user.id),
                vote=entry.vote,
                comment=entry.comment,
            )
            for entry in body.votes
        ]
        try:
            async with self.db.begin_nested():
                self.db.add_all(rows)
                await self.db.flush()
        except IntegrityError as exc:
            # 并发兜底：唯一约束（租户 + 批次 + 轮次 + 投票人 + 投票对象）与上面的查重是同一条
            # 规则，撞上说明另一个请求刚提交完，这时要给 409 而不是把数据库异常抛成 500。
            raise HTTPException(409, "同一投票人本轮已投票，不能重复提交") from exc
        return {"batch_no": body.batch_no, "round_no": body.round_no, "recorded": len(rows)}

    async def vote_summary(self, batch_no: str, round_no: int) -> dict[str, Any]:
        rows = (
            (
                await self.db.execute(
                    select(MemberVote)
                    .join(MemberProfile, MemberVote.profile_id == MemberProfile.id)
                    .where(
                        *self._scope(MemberProfile),
                        MemberVote.tenant_id == self.tenant_id,
                        MemberVote.batch_no == batch_no,
                        MemberVote.round_no == round_no,
                        MemberVote.is_deleted.is_(False),
                    )
                    .order_by(MemberVote.profile_id, MemberVote.voter_id)
                )
            )
            .scalars()
            .all()
        )
        tally: dict[str, dict[str, Any]] = {}
        voters: set[str] = set()
        mine = str(self.user.id)
        for row in rows:
            voters.add(row.voter_id)
            bucket = tally.setdefault(
                row.profile_id,
                {"agree": 0, "disagree": 0, "abstain": 0, "voted_by_me": False},
            )
            bucket[row.vote] += 1
            # 无记名：只回答"我投没投过这个人"，不回答"谁投了这个人"（T-MEM-12）。
            bucket["voted_by_me"] = bucket["voted_by_me"] or row.voter_id == mine
        return {
            "batch_no": batch_no,
            "round_no": round_no,
            "voter_count": len(voters),
            "tally": tally,
            "note": (
                f"{ASSISTED_REFERENCE_NOTE}；本汇总仅为过程记录，排序与入选由组织人员依规认定。"
                "汇总为无记名口径：只给出票数与票数分布，不给出投票人身份。"
                + evidence_note("投票明细")
            ),
            **annotate_level(vote_level()),
        }

    async def vote_voter_count(self, batch_no: str, round_no: int, profile_ids: list[str]) -> int:
        """无记名口径下的投票人数：只在服务端计数，任何身份都不经过接口。

        统一审核重算冻结候选范围时仍需要票数规模，但汇总已不返回 ``voters``
        （T-MEM-12），因此计数必须由服务端按授权范围完成，不能靠返回明细再数。
        """
        if not profile_ids:
            return 0
        total = (
            await self.db.execute(
                select(func.count(func.distinct(MemberVote.voter_id)))
                .join(MemberProfile, MemberVote.profile_id == MemberProfile.id)
                .where(
                    *self._scope(MemberProfile),
                    MemberVote.tenant_id == self.tenant_id,
                    MemberVote.batch_no == batch_no,
                    MemberVote.round_no == round_no,
                    MemberVote.is_deleted.is_(False),
                    MemberVote.profile_id.in_(profile_ids),
                )
            )
        ).scalar_one()
        return int(total or 0)

    # ==================== 有证据的辅助评分 ====================

    async def scoring(self, body: ScoringRequest) -> dict[str, Any]:
        profile = await self.profile(body.profile_id)
        catalog = _load_scoring_rules()
        weights = tenant_config.get(self.tenant_id, "scoring_weights", {}) or catalog["weights"]
        conditions = [
            MemberCultivation.tenant_id == self.tenant_id,
            MemberCultivation.profile_id == str(profile.id),
            MemberCultivation.is_deleted.is_(False),
            MemberCultivation.is_risk.is_(False),
        ]
        if body.year is not None:
            conditions.append(MemberCultivation.period == str(body.year))
        rows = (
            (
                await self.db.execute(
                    select(MemberCultivation).where(*conditions).order_by(MemberCultivation.id)
                )
            )
            .scalars()
            .all()
        )
        risk_rows = (
            (
                await self.db.execute(
                    select(MemberCultivation).where(
                        MemberCultivation.tenant_id == self.tenant_id,
                        MemberCultivation.profile_id == str(profile.id),
                        MemberCultivation.is_deleted.is_(False),
                        MemberCultivation.is_risk.is_(True),
                        *(
                            [MemberCultivation.period == str(body.year)]
                            if body.year is not None
                            else []
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        dimensions: dict[str, dict[str, Any]] = {}
        for row in rows:
            dim = dimensions.setdefault(row.category, {"scores": [], "evidence": []})
            if row.score is not None:
                dim["scores"].append(float(row.score))
            dim["evidence"].append(
                {
                    "source_id": "member_cultivation:" + str(row.id),
                    "period": row.period,
                    "note": row.source_note,
                }
            )
        weighted_total = 0.0
        weight_sum = 0.0
        output: dict[str, dict[str, Any]] = {}
        for category, weight in sorted(weights.items()):
            dim = dimensions.get(category) or {}
            if not dim or not dim["scores"]:
                output[category] = {
                    "value": None,
                    "status": "no_evidence",
                    "weight": weight,
                    "evidence": [],
                }
                continue
            value = sum(dim["scores"]) / len(dim["scores"])
            output[category] = {
                "value": round(value, 2),
                "status": "known",
                "weight": weight,
                "evidence": dim["evidence"],
                "count": len(dim["scores"]),
            }
            weighted_total += value * weight
            weight_sum += weight
        risks = [
            {"source_id": "member_cultivation:" + str(row.id), "risk_note": row.risk_note}
            for row in risk_rows
        ]
        return {
            "profile_id": body.profile_id,
            "year": body.year,
            "rule_version": "business_rules.yaml:scoring_rules",
            "weights": weights,
            "dimensions": output,
            "weighted_score": round(weighted_total / weight_sum, 2) if weight_sum else None,
            "risks": risks,
            "risk_items_hint": catalog["risk_items"],
            "missing": [key for key, value in output.items() if value["status"] == "no_evidence"],
            "disclaimer": (
                f"{ASSISTED_REFERENCE_NOTE}；无证据维度不打分，"
                + evidence_note("各维度 evidence 字段")
            ),
        }

    # ==================== 接续发展与档案检查 ====================

    async def archive_check(self, body: ArchiveCheckRun) -> dict[str, Any]:
        profile = await self.profile(body.profile_id)
        rule = None
        for candidate in self.rules.transitions:
            if candidate.source == profile.current_stage and candidate.target != "rejected":
                rule = candidate
                break
        rule_name = (
            f"{stage_label(profile.current_stage)} → "
            f"{STAGE_LABELS.get(rule.target) if rule else '下一步'}"
        )
        required = list(rule.required_materials) if rule else []
        missing = [name for name in required if name not in body.materials_note]
        irregular: list[str] = []
        history = await self.stage_history(str(profile.id))
        for earlier, later in zip(history, history[1:], strict=False):
            if earlier["decision_date"] > later["decision_date"]:
                irregular.append(
                    f"阶段时间顺序异常：{earlier['to_stage']} 晚于 {later['to_stage']} 的决策日期"
                )
        risks: list[str] = []
        for name, text in body.materials_note.items():
            if name not in missing and self._checkable(name):
                if not text:
                    risks.append(f"{name}：未提供可识别的原始材料内容")
                elif not _has_evidence_markers(text):
                    risks.append(f"{name}：未发现可识别的签字、盖章或日期标记，请人工核验")
        check = MemberArchiveCheck(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            checked_at=utc_now(),
            checked_by=str(self.user.id),
            rule_version="business_rules:1",
            result={
                "required_for": rule_name,
                "missing": missing,
                "irregular": irregular,
                "risks": risks,
            },
        )
        self.db.add(check)
        await self.db.flush()
        return {
            "check_id": str(check.id),
            "checked_at": jsonable_encoder(check.checked_at),
            "rule_version": check.rule_version,
            "result": check.result,
            "note": (
                f"{ASSISTED_REFERENCE_NOTE}；档案检查结果仅为提示，组织认定由授权人员完成。"
                + evidence_note("材料记录与阶段历史")
            ),
        }

    @staticmethod
    def _checkable(material: str) -> bool:
        uncertain = ("签字", "盖章", "日期", "决议", "意见")
        return not any(keyword in material for keyword in uncertain)

    # ==================== 名册延伸统计 ====================

    async def roster_stats(
        self, *, year: int | None, batch_no: str | None, org_unit_id: str | None = None
    ) -> dict[str, Any]:
        conditions = [
            *self._scope(MemberProfile),
            MemberProfile.is_active.is_(True),
            # 名册统计与名册列表口径一致：组织关系已转出的人员不再计入在册
            # （T-MEM-14），否则会出现"名册里 10 人、统计说 12 人"。
            MemberProfile.relation_status != "transferred_out",
        ]
        if year:
            conditions.append(MemberProfile.year == year)
        if batch_no:
            conditions.append(MemberProfile.batch_no == batch_no)
        if org_unit_id:
            # 组织筛选只接受权限范围内的组织（T-MEM-02）：传范围外的组织直接 403，
            # 不静默忽略——否则"某个支部的统计"看起来有效，数字其实是整个院系的
            if org_unit_id not in self.org_ids:
                raise HTTPException(403, "该组织不在你的权限范围内，不能按它统计名册")
            conditions.append(MemberProfile.org_unit_id == org_unit_id)
        stages = (
            await self.db.execute(
                select(MemberProfile.current_stage, func.count(MemberProfile.id))
                .where(*conditions)
                .group_by(MemberProfile.current_stage)
            )
        ).all()
        return {
            "year": year,
            "batch_no": batch_no,
            "org_unit_id": org_unit_id,
            "by_stage": {stage: count for stage, count in stages},
            "total": await self.db.scalar(select(func.count(MemberProfile.id)).where(*conditions)),
        }


def _has_evidence_markers(text: str) -> bool:
    markers = ("签字", "签名", "盖章", "日期", "年", "月", "日", "支部", "党委")
    return any(marker in text for marker in markers)


def stage_label(stage: str) -> str:
    try:
        return STAGE_LABELS.get(MemberStage(stage), stage)
    except ValueError:
        return stage
