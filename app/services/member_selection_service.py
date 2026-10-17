"""选优辅助分析的人工结论与团组织推优（模块2 / `T-MEM-13`、`T-MEM-06`）。

依据《中国共产党发展党员工作细则》：确定入党积极分子、列为发展对象、接收预备党员与
预备党员转正都要**经支委会或党员大会研究确定**；发展青年党员要注重**团组织推优**。

这个模块的验收句最容易做成三件反人类的事，这里逐条绕开：

1. **不"替组织出结论"**。多轮投票与培养记录评分只是**辅助材料**：系统按名单把本轮投票的
   无记名汇总快照存进 ``evidence`` 供审核人核对依据位置，但**不按票数排序、不自动勾选人选、
   不自动生成等次**——名单与依据必须由组织人员填写（``candidates`` / ``basis``）。
2. **不"一个人点一下就算认定"**。结论走"草稿 → 送审 → **第二位**组织人员审核"，送审人
   不得自审（``apply_review``），修订后必须重新送审，全过程只追加留痕；审核另走
   ``member.stage_transition`` 权限点（登记只需 ``member.scoring``），两个权限点分开，
   将来把登记与审核拆给不同角色时不用改代码。
3. **不"用年龄规则编数据"**。细则要求 28 周岁以下青年入党有团组织推优环节，但名册里没有
   出生年月，系统判不了年龄：因此推优只登记 + 提示"请组织核对"，**不因为缺记录就阻断**
   选优或阶段流转（否则只会逼出假日期）。

结论生效也不等于流转：阶段仍由授权人员在 ``member_stage_history`` 上人工办理，系统不自动
改阶段，也不自动向上级报送（报送走 `T-MEM-11` 台账，由人登记）。
"""

from datetime import date
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.meeting import ContentRevision
from app.models.member import MemberLeagueRecommendation, MemberProfile, MemberSelection
from app.models.user import User
from app.rules.data_sensitivity import (
    annotate_level,
    redact_third_party,
    selection_level,
    viewer_level,
)
from app.rules.member_stages import STAGE_LABELS, MemberStage, load_stage_rules
from app.schemas.member_selection import (
    LeagueRecommendationCreate,
    LeagueRecommendationRevoke,
    SelectionCreate,
    SelectionDecision,
    SelectionSubmit,
    SelectionUpdate,
)
from app.services.meeting_service import apply_review, reset_review
from app.services.member_service import MemberDevelopment
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

MAX_PAGE_SIZE = 100
MAX_PROFILE_IDS = 200

RESEARCH_METHOD_LABELS: dict[str, str] = {
    "committee": "支委会",
    "member_meeting": "党员大会",
}
STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已退回",
}

SELECTION_NOTICE = (
    "结论由组织人员填写、第二位组织人员审核；投票汇总与评分只是辅助材料，"
    "系统不按票数排序、不自动产生名单、不自动定等次"
)
DECISION_BOUNDARY = (
    "生效结论是组织认定依据：阶段流转仍由授权人员按程序人工办理，系统不自动改阶段，"
    "也不自动向上级党组织报送"
)
RECOMMENDATION_NOTICE = (
    "团组织推优只登记事实：推荐团组织、推荐日期与推优说明；推优记录不自动写进选优结论"
)
AGE_NOTICE = (
    "系统不判断年龄（名册里没有出生年月）：是否属 28 周岁以下青年请组织核对，"
    "缺推优记录不阻断选优与阶段流转"
)

# 生效结论对应的上级党组织事项：**只提示，不自动报送**（报送走 T-MEM-11 台账，由人登记）。
# 条号与 T-MEM-11 台账同一口径，不另编。
REPORT_HINTS: dict[str, str] = {
    MemberStage.ACTIVIST.value: (
        "确定入党积极分子后须报上级党委备案（细则第八条）：请在「上级审批 / 备案报送台账」登记"
    ),
    MemberStage.CANDIDATE.value: (
        "列为发展对象后须报上级党委备案（细则第十三条）：请在「上级审批 / 备案报送台账」登记"
    ),
    MemberStage.PROBATIONARY.value: (
        "接收预备党员须报上级党委审批（细则第二十一 / 二十二条）：请在「上级审批 / 备案报送台账」登记"
    ),
    MemberStage.MEMBER.value: ("预备党员转正须报上级党委审批：请在「上级审批 / 备案报送台账」登记"),
}


def stage_label(value: str | None) -> str:
    try:
        return STAGE_LABELS.get(MemberStage(value or ""), value or "")
    except ValueError:
        return value or ""


class MemberSelectionService:
    """在请求事务内完成结论与推优业务，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []
        self.rules = load_stage_rules()
        self.can_decide = has_permission(user.role, Permission.STAGE_TRANSITION)

    async def initialize(self) -> "MemberSelectionService":
        self.orgs = await visible_org_units(self.db, self.user)
        self.org_ids = [str(org.id) for org in self.orgs]
        return self

    def _scope(self, model: Any) -> list[Any]:
        return [
            model.tenant_id == self.tenant_id,
            model.is_deleted.is_(False),
            model.org_unit_id.in_(self.org_ids),
        ]

    def _require_org(self, org_unit_id: str) -> str:
        if org_unit_id not in self.org_ids:
            raise HTTPException(403, "请选择权限范围内有效的组织")
        return next((org.name for org in self.orgs if str(org.id) == org_unit_id), "")

    async def profile(self, profile_id: str, *, lock: bool = False) -> MemberProfile:
        stmt = select(MemberProfile).where(
            MemberProfile.tenant_id == self.tenant_id,
            MemberProfile.is_deleted.is_(False),
            MemberProfile.id == profile_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        profile = (await self.db.execute(stmt)).scalar_one_or_none()
        if profile is None:
            raise HTTPException(404, "党员档案不存在")
        # 名册组织范围仍要卡：跨范围档案一律当作不存在，避免越权登记
        if profile.org_unit_id and profile.org_unit_id not in self.org_ids:
            raise HTTPException(404, "党员档案不存在或不在授权组织范围")
        return profile

    async def selection_row(self, selection_id: str, *, lock: bool = False) -> MemberSelection:
        stmt = select(MemberSelection).where(
            *self._scope(MemberSelection), MemberSelection.id == selection_id
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "选优结论不存在或不在授权组织范围")
        return row

    async def recommendation_row(
        self, recommendation_id: str, *, lock: bool = False
    ) -> MemberLeagueRecommendation:
        stmt = select(MemberLeagueRecommendation).where(
            *self._scope(MemberLeagueRecommendation),
            MemberLeagueRecommendation.id == recommendation_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "推优记录不存在或不在授权组织范围")
        return row

    @staticmethod
    def check_revision(row: Any, expected: int) -> None:
        """拒绝覆盖别人已经修订的内容。"""
        if row.revision != expected:
            raise HTTPException(409, "内容已被修订，请刷新并核对当前版本后重试")

    async def _save_revision(
        self, row: Any, resource_type: str, action: str, reason: str, *, initial: bool = False
    ) -> None:
        """只追加的完整版本与真实操作人；结论不能靠"改一行"抹掉历史。"""
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type=resource_type,
                resource_id=str(row.id),
                revision=row.revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=row_data(row),
            )
        )
        await self.db.flush()

    # ==================== 辅助材料：无记名投票汇总快照 ====================

    async def vote_evidence(
        self, batch_no: str, round_no: int, candidate_ids: Sequence[str]
    ) -> dict[str, Any]:
        """把本轮投票的**无记名**汇总按名单裁剪后作为依据快照。

        审核人要能核对"这一轮票数是多少"，因此快照存票数分布与投票人数；但汇总里没有、
        也不允许有投票人身份（T-MEM-12），所以既不存身份，也不存 ``voted_by_me``
        （那是"当前查看者投没投"，与结论依据无关）。
        """
        service = await MemberDevelopment(self.db, self.user).initialize()
        summary = await service.vote_summary(batch_no, round_no)
        wanted = {str(item) for item in candidate_ids}
        tally = {
            key: {
                "agree": int(bucket.get("agree") or 0),
                "disagree": int(bucket.get("disagree") or 0),
                "abstain": int(bucket.get("abstain") or 0),
            }
            for key, bucket in (summary.get("tally") or {}).items()
            if key in wanted
        }
        return {
            "batch_no": batch_no,
            "round_no": round_no,
            "voter_count": int(summary.get("voter_count") or 0),
            "tally": tally,
            "evidence_note": (
                "依据位置：本轮选优投票的无记名汇总（按拟推荐名单裁剪），"
                "只含票数与投票人数、不含投票人身份；票数不构成结论"
            ),
        }

    # ==================== 拟推荐名单（选优结论） ====================

    async def _resolve_candidates(
        self, candidate_ids: Sequence[str], target_stage: str
    ) -> tuple[list[dict[str, Any]], str]:
        """把请求里的名单解析成带姓名 / 阶段快照的名单，并卡住范围与"只能向前"。

        返回 ``(名单快照, 所属组织 id)``：一份结论只针对同一组织范围的名单（一次支部研究），
        跨组织名单会让人读不出"这是哪个支部的结论"。
        """
        profiles: list[MemberProfile] = []
        for profile_id in candidate_ids:
            profile = await self.profile(profile_id)
            if not profile.org_unit_id:
                raise HTTPException(422, "该党员未归属有效组织，请先在档案中补齐")
            self._require_org(profile.org_unit_id)
            self._check_forward_stage(profile, target_stage)
            profiles.append(profile)
        org_units = {str(profile.org_unit_id) for profile in profiles}
        if len(org_units) > 1:
            raise HTTPException(422, "一份结论只能针对同一组织范围内的名单，请分开登记")
        candidates = [
            {
                "profile_id": str(profile.id),
                "member_name": profile.name,
                "stage": profile.current_stage,
                "stage_label": stage_label(profile.current_stage),
            }
            for profile in profiles
        ]
        return candidates, str(profiles[0].org_unit_id)

    def _check_forward_stage(self, profile: MemberProfile, target_stage: str) -> None:
        """拟推进阶段必须比当前阶段更靠后：结论是"往哪推"的依据，不是回退记录。"""
        try:
            current = MemberStage(profile.current_stage)
            target = MemberStage(target_stage)
        except ValueError:
            raise HTTPException(422, "阶段取值无效，无法登记选优结论") from None
        current_rank = self.rules.development_rank(current)
        target_rank = self.rules.development_rank(target)
        if current_rank is None or target_rank is None or current_rank >= target_rank:
            raise HTTPException(
                422,
                f"{profile.name} 当前是「{stage_label(profile.current_stage)}」，"
                f"不在「{stage_label(target_stage)}」之前，不能登记为拟推荐名单",
            )

    @staticmethod
    def _check_research_date(research_on: date) -> None:
        if research_on > date.today():
            raise HTTPException(422, "研究日期不能晚于今天：结论要有已经发生的研究程序")

    def missing(self, row: MemberSelection) -> list[str]:
        """送审必填项：缺一项都不许送审。"""
        missing: list[str] = []
        if not (row.candidates or []):
            missing.append("拟推荐名单不能为空")
        if not str(row.basis or "").strip():
            missing.append("结论依据待填（请写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录）")
        if row.research_on and row.research_on > date.today():
            missing.append("研究日期不能晚于今天")
        return missing

    async def create_selection(self, body: SelectionCreate) -> dict[str, Any]:
        """登记一份拟推荐名单草稿：名单、依据与研究程序全部由人给出。"""
        self._check_research_date(body.research_on)
        candidates, org_unit_id = await self._resolve_candidates(
            body.candidate_ids, body.target_stage
        )
        evidence = await self.vote_evidence(body.batch_no, body.round_no, body.candidate_ids)
        row = MemberSelection(
            tenant_id=self.tenant_id,
            org_unit_id=org_unit_id,
            org_name=self._require_org(org_unit_id),
            batch_no=body.batch_no,
            round_no=body.round_no,
            target_stage=body.target_stage,
            candidates=candidates,
            basis=body.basis,
            evidence=evidence,
            research_on=body.research_on,
            research_method=body.research_method,
            data_level=selection_level().value,
            revision=1,
            review_status="draft",
        )
        self.db.add(row)
        await self._save_revision(row, "member_selection", "create", body.reason, initial=True)
        return await self.selection_detail(str(row.id))

    async def update_selection(self, selection_id: str, body: SelectionUpdate) -> dict[str, Any]:
        """修订结论：改后回到草稿，必须重新送审（旧版本留在修订记录里）。"""
        row = await self.selection_row(selection_id, lock=True)
        self.check_revision(row, body.expected_revision)
        target_stage = body.target_stage or row.target_stage
        if body.research_on is not None:
            self._check_research_date(body.research_on)
            row.research_on = body.research_on
        org_unit_id = row.org_unit_id
        if body.candidate_ids is not None:
            row.candidates, org_unit_id = await self._resolve_candidates(
                body.candidate_ids, target_stage
            )
            row.evidence = await self.vote_evidence(row.batch_no, row.round_no, body.candidate_ids)
        elif body.target_stage is not None:
            # 只改目标阶段：名单要按新阶段重新核对"只能向前"
            ids = [item["profile_id"] for item in (row.candidates or [])]
            row.candidates, org_unit_id = await self._resolve_candidates(ids, target_stage)
        row.org_unit_id = org_unit_id
        row.org_name = self._require_org(org_unit_id)
        row.target_stage = target_stage
        if body.basis is not None:
            row.basis = body.basis
        if body.research_method is not None:
            row.research_method = body.research_method
        reset_review(row)
        await self._save_revision(row, "member_selection", "revise", body.reason)
        return await self.selection_detail(str(row.id))

    async def submit_selection(self, selection_id: str, body: SelectionSubmit) -> dict[str, Any]:
        """核查必填项后送审；缺项时把缺什么一次说清。"""
        row = await self.selection_row(selection_id, lock=True)
        self.check_revision(row, body.expected_revision)
        if row.review_status not in ("draft", "rejected"):
            raise HTTPException(409, "当前结论不能再次送审，请先修订")
        missing = self.missing(row)
        if missing:
            raise HTTPException(422, "；".join(missing))
        row.review_status, row.submitted_by = "pending", str(self.user.id)
        await self._save_revision(row, "member_selection", "submit", body.reason)
        return await self.selection_detail(str(row.id))

    async def review_selection(self, selection_id: str, body: SelectionDecision) -> dict[str, Any]:
        """人工审核当前版本，不允许自审；通过前再核一遍必填项。"""
        if not self.can_decide:
            raise HTTPException(403, "没有审核选优结论的权限")
        row = await self.selection_row(selection_id, lock=True)
        self.check_revision(row, body.expected_revision)
        if body.decision == "approved":
            missing = self.missing(row)
            if missing:
                raise HTTPException(422, "；".join(missing))
        apply_review(row, str(self.user.id), body.decision, body.reason)
        await self._save_revision(row, "member_selection", "review", body.reason)
        return await self.selection_detail(str(row.id))

    # ==================== 读取 ====================

    def _visible(self, data: dict[str, Any], level: Any) -> dict[str, Any]:
        """按密级脱敏第三人字段（T-MEM-12），并补上密级标注。"""
        masked, redacted = redact_third_party(data, level=level, viewer=viewer_level(self.user))
        masked.update(annotate_level(level))
        masked["redacted_fields"] = redacted
        return masked

    def selection_view(self, row: MemberSelection) -> dict[str, Any]:
        level = row.data_level or selection_level().value
        data: dict[str, Any] = {
            "id": str(row.id),
            "batch_no": row.batch_no,
            "round_no": row.round_no,
            "org_unit_id": row.org_unit_id,
            "org_name": row.org_name,
            "target_stage": row.target_stage,
            "target_stage_label": stage_label(row.target_stage),
            "candidates": row.candidates or [],
            "candidate_count": len(row.candidates or []),
            "basis": row.basis,
            "evidence": row.evidence or {},
            "research_on": row.research_on,
            "research_method": row.research_method,
            "research_method_label": RESEARCH_METHOD_LABELS.get(row.research_method, ""),
            "review_status": row.review_status,
            "review_status_label": STATUS_LABELS.get(row.review_status, row.review_status),
            "submitted_by": row.submitted_by,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at,
            "review_comment": row.review_comment,
            "revision": row.revision,
            # 生效标记：只有审核通过的结论才是组织认定依据
            "effective": row.review_status == "approved",
            "can_review": bool(
                row.review_status == "pending"
                and row.submitted_by != str(self.user.id)
                and self.can_decide
            ),
            "next_step_hint": REPORT_HINTS.get(row.target_stage, ""),
            "notice": SELECTION_NOTICE,
            "boundary": DECISION_BOUNDARY,
        }
        return self._visible(data, level)

    async def selections_summary(self, conditions: Sequence[Any]) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(MemberSelection.review_status, func.count(MemberSelection.id))
                .where(*conditions)
                .group_by(MemberSelection.review_status)
            )
        ).all()
        summary = {key: 0 for key in STATUS_LABELS}
        for status, count in rows:
            summary[str(status)] = int(count)
        return summary

    async def list_selections(
        self,
        *,
        batch_no: str | None = None,
        round_no: int | None = None,
        review_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """选优结论台账：按批次 / 轮次 / 状态筛选，附状态汇总。"""
        if review_status is not None and review_status not in STATUS_LABELS:
            raise HTTPException(422, "结论状态无效")
        conditions = list(self._scope(MemberSelection))
        if batch_no:
            conditions.append(MemberSelection.batch_no == batch_no)
        if round_no is not None:
            conditions.append(MemberSelection.round_no == round_no)
        if review_status is not None:
            conditions.append(MemberSelection.review_status == review_status)
        total = (
            await self.db.execute(select(func.count(MemberSelection.id)).where(*conditions))
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(MemberSelection)
                    .where(*conditions)
                    .order_by(MemberSelection.created_at.desc(), MemberSelection.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [self.selection_view(row) for row in rows],
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "summary": await self.selections_summary(conditions),
            "notice": SELECTION_NOTICE,
            "boundary": DECISION_BOUNDARY,
        }

    async def selection_detail(self, selection_id: str) -> dict[str, Any]:
        row = await self.selection_row(selection_id)
        level = row.data_level or selection_level().value
        data = self.selection_view(row)
        data.update(
            {
                "missing": self.missing(row),
                "advisories": await self.advisories(row),
                "revisions": [
                    self._visible(row_data(item), level)
                    for item in await self.revisions(selection_id)
                ],
            }
        )
        return data

    async def advisories(self, row: MemberSelection) -> list[str]:
        """提示项：不阻断送审，但把"这一步还没记"摆在明处。"""
        ids = [str(item.get("profile_id") or "") for item in (row.candidates or [])]
        pending = await self.missing_recommendations(ids)
        if not pending:
            return []
        return [
            f"{len(pending)} 名拟推荐对象尚无团组织推优记录：{AGE_NOTICE}",
            f"尚无推优记录：{'、'.join(pending)}",
        ]

    async def revisions(self, selection_id: str) -> list[ContentRevision]:
        """只追加修订记录：能看到改前改后分别是什么（脱敏在 ``_visible`` 出口统一做）。"""
        await self.selection_row(selection_id)
        return list(
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == "member_selection",
                        ContentRevision.resource_id == selection_id,
                    )
                    .order_by(ContentRevision.revision, ContentRevision.created_at)
                )
            )
            .scalars()
            .all()
        )

    # ==================== 团组织推优台账 ====================

    async def create_recommendation(self, body: LeagueRecommendationCreate) -> dict[str, Any]:
        """登记一条推优记录：不判断年龄、不阻断业务，只把事实记下来。"""
        profile = await self.profile(body.profile_id)
        if not profile.org_unit_id:
            raise HTTPException(422, "该党员未归属有效组织，请先在档案中补齐")
        self._require_org(profile.org_unit_id)
        if body.recommended_on > date.today():
            raise HTTPException(422, "推荐日期不能晚于今天")
        row = MemberLeagueRecommendation(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id,
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            league_org=body.league_org,
            recommended_on=body.recommended_on,
            note=body.note,
            data_level=selection_level().value,
            revision=1,
        )
        self.db.add(row)
        await self._save_revision(
            row, "member_league_recommendation", "create", body.reason, initial=True
        )
        return self.recommendation_view(row)

    async def revoke_recommendation(
        self, recommendation_id: str, body: LeagueRecommendationRevoke
    ) -> dict[str, Any]:
        """作废本次推优（录错 / 未办成），记录不删除。"""
        row = await self.recommendation_row(recommendation_id, lock=True)
        if row.revoked_on is not None:
            raise HTTPException(409, "本次推优记录已作废，无需重复作废")
        row.revoked_on = date.today()
        row.revoke_reason = body.reason
        await self._save_revision(row, "member_league_recommendation", "revoke", body.reason)
        return self.recommendation_view(row)

    def recommendation_view(self, row: MemberLeagueRecommendation) -> dict[str, Any]:
        level = row.data_level or selection_level().value
        data: dict[str, Any] = {
            "id": str(row.id),
            "profile_id": row.profile_id,
            "member_name": row.member_name,
            "stage": row.stage,
            "stage_label": stage_label(row.stage),
            "org_unit_id": row.org_unit_id,
            "org_name": row.org_name,
            "league_org": row.league_org,
            "recommended_on": row.recommended_on,
            "note": row.note,
            "revoked_on": row.revoked_on,
            "revoke_reason": row.revoke_reason,
            "revision": row.revision,
            "active": row.revoked_on is None,
            "age_notice": AGE_NOTICE,
            "notice": RECOMMENDATION_NOTICE,
        }
        return self._visible(data, level)

    async def list_recommendations(
        self,
        *,
        profile_id: str | None = None,
        profile_ids: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """推优台账：按人筛选；给出 ``profile_ids`` 时附带"这些人有没有推优记录"。"""
        conditions = list(self._scope(MemberLeagueRecommendation))
        if profile_id:
            conditions.append(MemberLeagueRecommendation.profile_id == profile_id)
        total = (
            await self.db.execute(
                select(func.count(MemberLeagueRecommendation.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(MemberLeagueRecommendation)
                    .where(*conditions)
                    .order_by(
                        MemberLeagueRecommendation.recommended_on.desc(),
                        MemberLeagueRecommendation.created_at.desc(),
                        MemberLeagueRecommendation.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        active = (
            await self.db.execute(
                select(func.count(MemberLeagueRecommendation.id)).where(
                    *conditions, MemberLeagueRecommendation.revoked_on.is_(None)
                )
            )
        ).scalar_one()
        status = await self.recommendation_status(profile_ids) if profile_ids else []
        return {
            "items": [self.recommendation_view(row) for row in rows],
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "summary": {"total": int(total), "active": int(active), "revoked": int(total - active)},
            "status": status,
            "age_notice": AGE_NOTICE,
            "notice": RECOMMENDATION_NOTICE,
        }

    async def recommendation_status(self, profile_ids: str) -> list[dict[str, Any]]:
        """按人给出"有没有推优记录"：只回标记与最近一次，不做年龄判断、不阻断业务。"""
        ids = [item.strip() for item in profile_ids.split(",") if item.strip()]
        if not ids:
            return []
        if len(ids) > MAX_PROFILE_IDS:
            raise HTTPException(422, f"一次最多查询 {MAX_PROFILE_IDS} 名党员的推优记录")
        rows = (
            (
                await self.db.execute(
                    select(MemberLeagueRecommendation)
                    .where(
                        *self._scope(MemberLeagueRecommendation),
                        MemberLeagueRecommendation.profile_id.in_(ids),
                    )
                    .order_by(
                        MemberLeagueRecommendation.profile_id,
                        MemberLeagueRecommendation.recommended_on.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest: dict[str, MemberLeagueRecommendation] = {}
        counts: dict[str, int] = {}
        for row in rows:
            if row.revoked_on is None:
                counts[row.profile_id] = counts.get(row.profile_id, 0) + 1
                if row.profile_id not in latest:
                    latest[row.profile_id] = row
        missing = await self._names(ids)
        return [
            {
                "profile_id": profile_id,
                "member_name": missing.get(profile_id, ""),
                "has_record": profile_id in latest,
                "active_count": counts.get(profile_id, 0),
                "latest_on": latest[profile_id].recommended_on if profile_id in latest else None,
                "latest_org": latest[profile_id].league_org if profile_id in latest else "",
                "age_notice": AGE_NOTICE,
            }
            for profile_id in ids
        ]

    async def _names(self, profile_ids: Sequence[str]) -> dict[str, str]:
        if not profile_ids:
            return {}
        rows = (
            await self.db.execute(
                select(MemberProfile.id, MemberProfile.name).where(
                    MemberProfile.tenant_id == self.tenant_id,
                    MemberProfile.is_deleted.is_(False),
                    MemberProfile.id.in_(list(profile_ids)),
                )
            )
        ).all()
        return {str(row[0]): str(row[1]) for row in rows}

    async def missing_recommendations(self, profile_ids: Sequence[str]) -> list[str]:
        """没有有效推优记录的人名：供界面提示"别漏了"，不当拦截条件。"""
        wanted = [str(item) for item in profile_ids if item]
        if not wanted:
            return []
        rows = (
            await self.db.execute(
                select(MemberLeagueRecommendation.profile_id).where(
                    *self._scope(MemberLeagueRecommendation),
                    MemberLeagueRecommendation.profile_id.in_(wanted),
                    MemberLeagueRecommendation.revoked_on.is_(None),
                )
            )
        ).all()
        covered = {str(row[0]) for row in rows}
        names = await self._names([item for item in wanted if item not in covered])
        return [names.get(item, item) for item in wanted if item not in covered]
