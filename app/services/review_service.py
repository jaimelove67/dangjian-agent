"""统一人工审核，快照由授权业务服务生成，不接受客户端正文或审核人。"""

import hashlib
import json
from datetime import datetime
from typing import Any, cast

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.assessment import AssessmentPlan, AssessmentRun
from app.models.governance import HumanReview
from app.models.user import User
from app.schemas.assessment import ReviewRequest as AssessmentDecision
from app.schemas.governance import ReviewDecision, ReviewSubmit
from app.schemas.meeting import ReviewRequest as MeetingDecision
from app.schemas.meeting import RevisionRequest
from app.schemas.member_ext import ScoringRequest
from app.schemas.member_review import ReviewDecision as MemberReviewDecision
from app.schemas.member_review import ReviewSubmit as MemberReviewSubmit
from app.schemas.study import ReviewRequest as StudyDecision
from app.services.activity_service import ActivityService
from app.services.assessment_service import AssessmentService, row_view
from app.services.member_review_service import MemberReviewService
from app.services.member_service import MemberDevelopment
from app.services.study_service import StudyService

PERMISSIONS = {
    "score": Permission.SCORING,
    "vote": Permission.SCORING,
    "meeting": Permission.MEETING_REVIEW,
    "member_review": Permission.MEETING_REVIEW,
    "study_activity": Permission.STUDY_REVIEW,
    "study_plan": Permission.STUDY_REVIEW,
    "assessment_report": Permission.ASSESSMENT_REVIEW,
    "assessment_plan": Permission.ASSESSMENT_REVIEW,
}
# 指纹里必须忽略"随查看者变化"的字段，否则同一份内容在不同审核人眼里会被判成版本失效。
VOLATILE = {
    "created_at",
    "updated_at",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "review_comment",
    "review_opinion",
    "submitted_by",
    "revision",
    "archived_at",
    "archive_policy_version",
    # 无记名选优汇总给当前查看者的"我已投"标记，不是内容本身（T-MEM-12）。
    "voted_by_me",
}


def fingerprint(value: Any) -> str:
    def stable(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: stable(val) for key, val in item.items() if key not in VOLATILE}
        if isinstance(item, list):
            return [stable(val) for val in item]
        return item

    content = json.dumps(stable(value), ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(content).hexdigest()


class ReviewService:
    def __init__(self, db: AsyncSession, user: User):
        self.db, self.user = db, user

    async def source(self, body: ReviewSubmit, *, lock: bool = False) -> tuple[dict, Any, Any]:
        service: Any
        row: Any
        permission = PERMISSIONS.get(body.source_kind)
        if permission is None or not has_permission(self.user.role, permission):
            raise HTTPException(403, "没有此类业务审核权限")
        if body.source_kind in {"score", "vote"}:
            service = await MemberDevelopment(self.db, self.user).initialize()
            if body.source_kind == "score":
                profile = await service.profile(body.source_id, lock=lock)
                data = await service.scoring(ScoringRequest(profile_id=profile.id, year=body.year))
            else:
                data = await service.vote_summary(body.source_id, body.round)
                if not data.get("tally"):
                    raise HTTPException(404, "选优记录不存在或不在授权组织范围")
                # 结果从授权范围产生；不会通过批次号读取他组织候选人。
            return jsonable_encoder(data), service, None
        if body.source_kind == "meeting":
            service = await ActivityService(self.db, self.user).initialize()
            row = await service.record(body.source_id, lock=lock)
            await service.require_visible_content(row)
            return await service._snapshot(row), service, row
        if body.source_kind == "member_review":
            service = await MemberReviewService(self.db, self.user).initialize()
            row = await service.review_row(body.source_id, lock=lock)
            return await service._snapshot(row), service, row
        if body.source_kind in {"study_activity", "study_plan"}:
            service = await StudyService(self.db, self.user).initialize()
            if body.source_kind == "study_activity":
                row = await service.activity(body.source_id, lock=lock)
                visible = await service.activity_data(row)
            else:
                row = await service.plan(body.source_id, lock=lock)
                visible = await service.plan_data(row)
            if visible.get("restricted"):
                raise HTTPException(404, "审核对象关联资料已失去访问权限")
            return await service._snapshot(row), service, row
        service = AssessmentService(self.db, self.user)
        model = AssessmentPlan if body.source_kind == "assessment_plan" else AssessmentRun
        row = await service._get(model, body.source_id, lock=lock)
        _, run = await service.fresh_run(row.run_id if model is AssessmentPlan else row.id)
        return {"record": row_view(row), "source": jsonable_encoder(run)}, service, row

    async def current_source(
        self, row: HumanReview, *, lock: bool = False
    ) -> tuple[dict[str, Any], Any, Any]:
        params = ReviewSubmit.model_validate(row.snapshot["parameters"])
        current, service, source = await self.source(params, lock=lock)
        if params.source_kind == "vote":
            # 审核人可能比提交人有更广组织权限；固定提交的候选范围后重算。
            scope_ids = list(row.snapshot["content"]["tally"])
            for profile_id in scope_ids:
                await service.profile(profile_id, lock=lock)
            current["tally"] = {
                key: value for key, value in current["tally"].items() if key in scope_ids
            }
            # 无记名汇总不返回投票人身份（T-MEM-12），票数规模改由服务端按冻结范围计数。
            current["voter_count"] = await service.vote_voter_count(
                params.source_id, params.round, scope_ids
            )
        return current, service, source

    async def visible_reviews(self) -> list[dict[str, Any]]:
        # 历史量过大时明确拒绝全量统计，不能返回误导的审核积压。
        rows = list(
            (
                await self.db.execute(
                    select(HumanReview)
                    .where(
                        HumanReview.tenant_id == str(self.user.tenant_id),
                        HumanReview.is_deleted.is_(False),
                    )
                    .order_by(HumanReview.created_at.desc(), HumanReview.id)
                    .limit(5001)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) > 5000:
            raise HTTPException(503, "审核历史超过当前统计容量，请分批归档后查询")
        items: list[dict[str, Any]] = []
        latest: set[str] = set()
        for row in rows:
            try:
                item = await self.view(row)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            key = fingerprint(row.snapshot["parameters"])
            if key in latest:
                item.update(effective_status="superseded", superseded=True)
            else:
                latest.add(key)
                item["superseded"] = False
            items.append(item)
        return items

    async def submit(self, body: ReviewSubmit) -> HumanReview:
        snapshot, service, source = await self.source(body, lock=True)
        # 重要纪要/学习计划复用原业务送审校验，不能从统一入口跳过资料核验。
        if source is not None and body.source_kind in {
            "meeting",
            "study_activity",
            "study_plan",
            "member_review",
        }:
            if source.review_status in {"draft", "rejected"}:
                reason = "提交统一人工审核"
                if body.source_kind == "member_review":
                    await service.submit(
                        source.id,
                        MemberReviewSubmit(expected_revision=source.revision, reason=reason),
                    )
                else:
                    revision = RevisionRequest(expected_revision=source.revision, reason=reason)
                    if body.source_kind == "meeting":
                        await service.submit(source.id, revision)
                    elif body.source_kind == "study_activity":
                        await service.submit_activity(source.id, revision)
                    else:
                        await service.submit_plan(source.id, revision)
                snapshot, _, _ = await self.source(body, lock=True)
            elif source.review_status != "pending":
                raise HTTPException(409, "当前对象须先修订为待审核版本")
        version = fingerprint(snapshot)
        existing = (
            await self.db.execute(
                select(HumanReview)
                .where(
                    HumanReview.tenant_id == str(self.user.tenant_id),
                    HumanReview.source_kind == body.source_kind,
                    HumanReview.source_id == body.source_id,
                    HumanReview.source_version == version,
                    HumanReview.status == "pending",
                    HumanReview.is_deleted.is_(False),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        row = HumanReview(
            tenant_id=str(self.user.tenant_id),
            source_kind=body.source_kind,
            source_id=body.source_id,
            source_version=version,
            snapshot={"parameters": body.model_dump(), "content": snapshot},
            status="pending",
            submitted_by=str(self.user.id),
        )
        try:
            async with self.db.begin_nested():
                self.db.add(row)
                await self.db.flush()
        except IntegrityError:
            existing = (
                await self.db.execute(
                    select(HumanReview).where(
                        HumanReview.tenant_id == str(self.user.tenant_id),
                        HumanReview.source_kind == body.source_kind,
                        HumanReview.source_id == body.source_id,
                        HumanReview.source_version == version,
                        HumanReview.status == "pending",
                        HumanReview.is_deleted.is_(False),
                    )
                )
            ).scalar_one()
            return existing
        return row

    async def view(self, row: HumanReview, *, include_content: bool = False) -> dict:
        try:
            current, _, _ = await self.current_source(row)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise HTTPException(404, "审核对象不存在或已失去访问权限") from None
            # 已授权的考核来源失效时保留审核元数据，隐藏旧正文。
            current = None
        stale = current is None or fingerprint(current) != row.source_version
        data = {
            key: getattr(row, key)
            for key in (
                "id",
                "source_kind",
                "source_id",
                "source_version",
                "status",
                "submitted_by",
                "reviewed_by",
                "reviewed_at",
                "opinion",
                "created_at",
            )
        }
        data.update(effective_status="pending" if stale else row.status, stale=stale)
        if include_content:
            # 当前资料授权不能授权历史来源；版本失效时只给元数据，要求重新送审。
            data["snapshot"] = None if stale else row.snapshot["content"]
        return cast(dict[Any, Any], jsonable_encoder(data))

    async def decide(self, record_id: str, body: ReviewDecision) -> HumanReview:
        row = (
            await self.db.execute(
                select(HumanReview)
                .where(
                    HumanReview.id == record_id,
                    HumanReview.tenant_id == str(self.user.tenant_id),
                    HumanReview.is_deleted.is_(False),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "审核记录不存在")
        if row.status != "pending":
            raise HTTPException(409, "此版本已经审核，不能重复审核")
        if row.submitted_by == str(self.user.id):
            raise HTTPException(403, "提交人不能审核自己的版本")
        params = ReviewSubmit.model_validate(row.snapshot["parameters"])
        current, service, source = await self.current_source(row, lock=True)
        if body.source_version != row.source_version or fingerprint(current) != row.source_version:
            raise HTTPException(409, "源内容已修改，请重新提交审核")
        if params.source_kind == "meeting":
            await service.review(
                source.id,
                MeetingDecision(
                    expected_revision=source.revision,
                    reason=body.opinion,
                    decision="approved" if body.decision == "approved" else "rejected",
                ),
            )
        elif params.source_kind == "member_review":
            await service.review(
                source.id,
                MemberReviewDecision(
                    expected_revision=source.revision,
                    decision="approved" if body.decision == "approved" else "rejected",
                    reason=body.opinion,
                ),
            )
        elif params.source_kind in {"study_activity", "study_plan"}:
            decision = StudyDecision(
                expected_revision=source.revision,
                reason=body.opinion,
                decision="approved" if body.decision == "approved" else "rejected",
            )
            if params.source_kind == "study_activity":
                await service.review_activity(source.id, decision)
            else:
                await service.review_plan(source.id, decision)
        elif params.source_kind in {"assessment_report", "assessment_plan"}:
            await service.review(
                "plans" if params.source_kind == "assessment_plan" else "runs",
                source.id,
                AssessmentDecision(
                    status=body.decision, opinion=body.opinion, expected_revision=source.revision
                ),
            )
        row.status, row.opinion = body.decision, body.opinion
        row.reviewed_by, row.reviewed_at = str(self.user.id), datetime.utcnow()
        await self.db.flush()
        return row
