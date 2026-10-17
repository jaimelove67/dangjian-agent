"""民主评议党员（模块3 / T-ORG-11）：按年度记录程序与等次，人工审核通过后才生效。

制度依据《中国共产党支部工作条例（试行）》第十九条：党支部一般每年开展 1 次
民主评议党员，按照个人自评、党员互评、民主测评的程序组织党员评议，由支委会或
党员大会根据评议情况和党员日常表现提出评定意见；民主评议党员可以结合组织生活会
一并进行，评议结果作为党员档案与考核的复用来源。

系统只做三件事：把组织人员录入的程序与等次如实留下来、要求**另一位**有权限的
人员审核、审核通过后供本人档案与考核复用。等次不由模型生成、不按测评票数自动排名、
也不自动限制优秀比例——优秀比例上限按上级组织部门规定执行，系统无从知晓。
拟评定不合格的，组织处置（限期改正、劝退、除名等）须按党章党规由党组织研究决定，
系统只提示"需研究处置"，不生成处置意见。

未接入统一审核前先说明边界：本模块自带送审/审核入口，同时登记进治理页的
「人工审核」队列（``ReviewService`` source_kind = ``member_review``），两条入口
操作的是同一条记录与同一套状态，不会出现两个互相矛盾的审核结果。
"""

from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.meeting import ContentRevision
from app.models.member import MemberProfile, MemberReview
from app.models.user import User
from app.rules.data_sensitivity import (
    THIRD_PARTY_FIELDS,
    annotate_level,
    is_redaction_placeholder,
    redact_third_party,
    review_level,
    viewer_level,
)
from app.rules.member_stages import STAGE_LABELS, MemberStage
from app.schemas.member_review import (
    ReviewCreate,
    ReviewDecision,
    ReviewLaunch,
    ReviewSubmit,
    ReviewUpdate,
)
from app.services.meeting_service import apply_review, reset_review
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "business_rules.yaml"

# 等次用稳定英文键；中文说法只在这里与界面各出现一次，筛选、汇总、导出共用同一张表。
GRADE_LABELS: dict[str, str] = {
    "outstanding": "优秀",
    "qualified": "合格",
    "basic": "基本合格",
    "unqualified": "不合格",
}
DEFAULT_GRADES: tuple[str, ...] = ("outstanding", "qualified", "basic", "unqualified")

# 评议对象：正式党员与预备党员。申请人、积极分子、发展对象不参加民主评议。
REVIEW_STAGES: tuple[str, ...] = (MemberStage.MEMBER.value, MemberStage.PROBATIONARY.value)

# 单次汇总/工作区最多列出的评议对象数；超过时明确提示按支部筛选，不静默截断。
MAX_TARGETS = 500

REVIEW_NOTICE = "评议程序与等次由组织人员记录、审核人确认；系统不按票数自动排名或定等次"
DECISION_BOUNDARY = "等次与组织处置属于组织结论，须人工形成；系统只记录、送审与留痕"
LAUNCH_NOTICE = "已为在册党员建立本年度评议草稿，均需录入程序与等次后送审；已有记录不会被覆盖"

DEFAULT_OUTSTANDING_NOTICE = "优秀等次比例上限按学校党委组织部门的规定执行，系统不自动截断或排名"
DEFAULT_UNQUALIFIED_NOTICE = (
    "拟评定不合格的，组织处置须按党章党规由党组织研究决定，系统不自动生成处置意见"
)
DEFAULT_FEEDBACK_NOTICE = "评定意见应向本人反馈；本人只能在“本人档案”查看自己的评议结果"

# 送审必填项：缺一项都不许送审，但不逼组织编造没有做过的事（互评与测评只作提示）。
BLOCKING_FIELDS = (
    ("self_assessment", "个人自评待录"),
    ("branch_opinion", "支部评定意见待录"),
)
ADVISORY_FIELDS = (
    ("peer_review", "未登记党员互评意见"),
    ("test", "未登记民主测评票数"),
)


def stage_label(value: str | None) -> str:
    """阶段快照回读：历史行的阶段值可能已不在枚举内，读不出就留空而不是报错。"""
    try:
        return STAGE_LABELS.get(MemberStage(value or ""), "")
    except ValueError:
        return ""


def load_rules() -> dict[str, Any]:
    """读取评议配置；文件缺失或字段非法时回落到默认口径，不阻断业务。"""
    try:
        data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    entry = data.get("democratic_review") or {}
    grades = [key for key in (entry.get("grades") or []) if key in GRADE_LABELS]
    return {
        "grades": grades or list(DEFAULT_GRADES),
        "outstanding_notice": str(entry.get("outstanding_notice") or DEFAULT_OUTSTANDING_NOTICE),
        "unqualified_notice": str(entry.get("unqualified_notice") or DEFAULT_UNQUALIFIED_NOTICE),
        "feedback_notice": str(entry.get("feedback_notice") or DEFAULT_FEEDBACK_NOTICE),
    }


class MemberReviewService:
    """在请求事务内完成评议业务，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []
        # 谁有审核权由权限矩阵决定；"能不能审这一条"还要看是不是本人提交的。
        self.can_decide = has_permission(user.role, Permission.MEETING_REVIEW)

    async def initialize(self) -> "MemberReviewService":
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

    async def review_row(self, review_id: str, *, lock: bool = False) -> MemberReview:
        stmt = select(MemberReview).where(*self._scope(MemberReview), MemberReview.id == review_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "民主评议记录不存在或不在授权组织范围")
        return row

    async def profile(self, profile_id: str, *, lock: bool = False) -> MemberProfile:
        stmt = select(MemberProfile).where(
            *self._scope(MemberProfile), MemberProfile.id == profile_id
        )
        if lock:
            stmt = stmt.with_for_update()
        profile = (await self.db.execute(stmt)).scalar_one_or_none()
        if profile is None:
            raise HTTPException(404, "党员档案不存在或不在授权组织范围")
        return profile

    @staticmethod
    def check_revision(row: MemberReview, expected: int) -> None:
        """拒绝覆盖别人已经修订的内容。"""
        if row.revision != expected:
            raise HTTPException(409, "内容已被修订，请刷新并核对当前版本后重试")

    async def _snapshot(self, row: MemberReview) -> dict[str, Any]:
        return row_data(row)

    async def _save_revision(
        self, row: MemberReview, action: str, reason: str, *, initial: bool = False
    ) -> None:
        """保存只追加的完整版本与真实操作人。"""
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type="member_review",
                resource_id=str(row.id),
                revision=row.revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=row_data(row),
            )
        )
        await self.db.flush()

    # ==================== 缺项与提示 ====================

    def missing(self, row: MemberReview) -> list[str]:
        """送审必填项：缺一项都不许送审。"""
        procedure = row.procedure or {}
        missing = [
            text for key, text in BLOCKING_FIELDS if not str(procedure.get(key) or "").strip()
        ]
        if not row.grade:
            missing.append("评定等次待定")
        if not str(row.basis or "").strip():
            missing.append("评定依据待填")
        return missing

    def advisories(self, row: MemberReview) -> list[str]:
        """提示项：不阻断送审，但让人看见"这一步还没记"。"""
        procedure = row.procedure or {}
        return [text for key, text in ADVISORY_FIELDS if not procedure.get(key)]

    # ==================== 发起与录入 ====================

    async def _party_members(self, org_unit_id: str) -> list[MemberProfile]:
        self._require_org(org_unit_id)
        rows = (
            (
                await self.db.execute(
                    select(MemberProfile)
                    .where(
                        *self._scope(MemberProfile),
                        MemberProfile.org_unit_id == org_unit_id,
                        MemberProfile.current_stage.in_(REVIEW_STAGES),
                        MemberProfile.is_active.is_(True),
                        # 组织关系已转出（T-MEM-14）的人不参加本组织民主评议：
                        # 他已经不属于这个支部，不能一边显示"已转出"一边还在评他。
                        MemberProfile.relation_status != "transferred_out",
                    )
                    .order_by(MemberProfile.name, MemberProfile.id)
                    .limit(MAX_TARGETS + 1)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def launch(self, body: ReviewLaunch) -> dict[str, Any]:
        """按年度发起：为支部在册党员建立草稿，已有记录原样保留。"""
        org_name = self._require_org(body.org_unit_id)
        members = await self._party_members(body.org_unit_id)
        if len(members) > MAX_TARGETS:
            raise HTTPException(
                422, f"在册党员超过 {MAX_TARGETS} 人，请按支部逐个发起，避免一次建立过多草稿"
            )
        existing = set(
            (
                await self.db.execute(
                    select(MemberReview.profile_id).where(
                        *self._scope(MemberReview),
                        MemberReview.year == body.year,
                    )
                )
            )
            .scalars()
            .all()
        )
        created: list[MemberReview] = []
        for profile in members:
            if str(profile.id) in existing:
                continue
            row = MemberReview(
                tenant_id=self.tenant_id,
                year=body.year,
                profile_id=str(profile.id),
                org_unit_id=body.org_unit_id,
                org_name=profile.org_name or org_name,
                member_name=profile.name,
                stage=profile.current_stage,
                data_level=review_level().value,
            )
            self.db.add(row)
            await self.db.flush()
            await self._save_revision(row, "launch", body.reason, initial=True)
            created.append(row)
        return {
            "year": body.year,
            "org_unit_id": body.org_unit_id,
            "org_name": org_name,
            "created": len(created),
            "skipped": len(members) - len(created),
            "target_total": len(members),
            "items": [self.target_view(None, row, org_name) for row in created],
            "notice": LAUNCH_NOTICE,
        }

    async def create(self, body: ReviewCreate) -> MemberReview:
        """为一名党员建立本年度评议记录；已存在时明确报错，不生成第二条。"""
        profile = await self.profile(body.profile_id)
        if profile.current_stage not in REVIEW_STAGES:
            raise HTTPException(422, "民主评议对象为正式党员与预备党员")
        if not profile.org_unit_id:
            raise HTTPException(422, "该党员未归属有效组织，请先在档案中补齐")
        self._require_org(profile.org_unit_id)
        existing = (
            await self.db.execute(
                select(MemberReview.id).where(
                    *self._scope(MemberReview),
                    MemberReview.year == body.year,
                    MemberReview.profile_id == str(profile.id),
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "该党员本年度已有评议记录，请沿用既有记录")
        row = MemberReview(
            tenant_id=self.tenant_id,
            year=body.year,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id,
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            data_level=review_level().value,
            procedure=self._without_placeholders(body.procedure.model_dump()),
            grade=body.grade or "",
            basis=body.basis,
            rectification=body.rectification,
        )
        self.db.add(row)
        await self.db.flush()
        await self._save_revision(row, "create", body.reason, initial=True)
        return row

    async def update(self, review_id: str, body: ReviewUpdate) -> MemberReview:
        """修订程序或等次；修改后必须重新送审，旧版本留在修订表中。"""
        row = await self.review_row(review_id, lock=True)
        self.check_revision(row, body.expected_revision)
        if body.procedure is not None:
            # 详情面板按等级脱敏后回填的占位文本不当内容写回（T-MEM-12）。
            incoming = self._without_placeholders(body.procedure.model_dump())
            row.procedure = {**(row.procedure or {}), **incoming}
        if body.grade is not None:
            row.grade = body.grade
        if body.basis is not None:
            row.basis = body.basis
        if body.rectification is not None:
            row.rectification = body.rectification
        reset_review(row)
        await self._save_revision(row, "revise", body.reason)
        return row

    # ==================== 送审与审核 ====================

    async def submit(self, review_id: str, body: ReviewSubmit) -> MemberReview:
        """核查必填项后送审；缺项时把缺什么一次说清。"""
        row = await self.review_row(review_id, lock=True)
        self.check_revision(row, body.expected_revision)
        if row.review_status not in ("draft", "rejected"):
            raise HTTPException(409, "当前评议不能再次提交，请先修订")
        missing = self.missing(row)
        if missing:
            raise HTTPException(422, "；".join(missing))
        row.review_status, row.submitted_by = "pending", str(self.user.id)
        await self._save_revision(row, "submit", body.reason)
        return row

    async def review(self, review_id: str, body: ReviewDecision) -> MemberReview:
        """人工审核当前版本，不允许自审；通过前再核一遍必填项。"""
        row = await self.review_row(review_id, lock=True)
        self.check_revision(row, body.expected_revision)
        if body.decision == "approved":
            missing = self.missing(row)
            if missing:
                raise HTTPException(422, "；".join(missing))
        apply_review(row, str(self.user.id), body.decision, body.reason)
        await self._save_revision(row, "review", body.reason)
        return row

    # ==================== 读取与汇总 ====================

    def target_view(
        self, profile: MemberProfile | None, row: MemberReview | None, org_name: str
    ) -> dict[str, Any]:
        """把"应评议对象"与"已有记录"合成一行，未发起的显式标出。"""
        grade = (row.grade if row else "") or ""
        return {
            "profile_id": str(profile.id) if profile else (row.profile_id if row else ""),
            "member_name": profile.name if profile else (row.member_name if row else ""),
            "stage": profile.current_stage if profile else (row.stage if row else ""),
            "stage_label": stage_label(
                profile.current_stage if profile else (row.stage if row else "")
            ),
            "org_unit_id": profile.org_unit_id if profile else (row.org_unit_id if row else ""),
            "org_name": profile.org_name if profile else (row.org_name if row else org_name),
            "in_roster": profile is not None,
            "review_id": str(row.id) if row else None,
            "revision": row.revision if row else 0,
            "review_status": (row.review_status if row else "not_started"),
            "submitted_by": (row.submitted_by if row else None),
            "can_review": bool(
                row
                and row.review_status == "pending"
                and row.submitted_by != str(self.user.id)
                and self.can_decide
            ),
            "grade": grade,
            "grade_label": GRADE_LABELS.get(grade, ""),
            "rectification": (row.rectification if row else "") or "",
            "missing": self.missing(row) if row else [],
            "advisories": self.advisories(row) if row else [],
        }

    async def workspace(self, *, year: int, org_unit_id: str | None) -> dict[str, Any]:
        """某年度（可指定支部）的评议进度、程序明细与汇总，一次取齐。"""
        rules = load_rules()
        if org_unit_id is not None:
            self._require_org(org_unit_id)
        org_ids = [org_unit_id] if org_unit_id else list(self.org_ids)
        org_names = {str(org.id): org.name for org in self.orgs}
        members = list(
            (
                await self.db.execute(
                    select(MemberProfile)
                    .where(
                        *self._scope(MemberProfile),
                        MemberProfile.org_unit_id.in_(org_ids),
                        MemberProfile.current_stage.in_(REVIEW_STAGES),
                        MemberProfile.is_active.is_(True),
                        # 与发起口径一致：已转出人员不进应评议名单（T-MEM-14）。
                        MemberProfile.relation_status != "transferred_out",
                    )
                    .order_by(MemberProfile.org_unit_id, MemberProfile.name, MemberProfile.id)
                    .limit(MAX_TARGETS + 1)
                )
            )
            .scalars()
            .all()
        )
        truncated = len(members) > MAX_TARGETS
        if truncated:
            members = members[:MAX_TARGETS]
        rows = list(
            (
                await self.db.execute(
                    select(MemberReview).where(
                        *self._scope(MemberReview),
                        MemberReview.org_unit_id.in_(org_ids),
                        MemberReview.year == year,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_profile = {row.profile_id: row for row in rows}
        targets: list[dict[str, Any]] = []
        for profile in members:
            row = by_profile.pop(str(profile.id), None)
            targets.append(
                self.target_view(profile, row, org_names.get(str(profile.org_unit_id), ""))
            )
        # 已调出、已停止参加评议但当年有记录的：不能因为不在在册名单里就查不到。
        for row in sorted(by_profile.values(), key=lambda item: (item.member_name, item.id)):
            targets.append(
                self.target_view(None, row, org_names.get(row.org_unit_id, row.org_name))
            )
        progress = {
            "target_total": len(targets),
            "launched": 0,
            "not_started": 0,
            "draft": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
        }
        grades = {key: 0 for key in GRADE_LABELS}
        attention: list[dict[str, Any]] = []
        advisory_count = 0
        for item in targets:
            status = item["review_status"]
            if status == "not_started":
                progress["not_started"] += 1
            else:
                progress["launched"] += 1
                progress[status] = progress.get(status, 0) + 1
                if item["advisories"]:
                    advisory_count += 1
            if item["grade"] in grades and status == "approved":
                grades[item["grade"]] += 1
                if item["grade"] in ("basic", "unqualified"):
                    attention.append(
                        {
                            "review_id": item["review_id"],
                            "member_name": item["member_name"],
                            "org_name": item["org_name"],
                            "grade": item["grade"],
                            "grade_label": item["grade_label"],
                            "rectification": item["rectification"],
                        }
                    )
        outstanding = grades.get("outstanding", 0)
        return {
            "year": year,
            "org_unit_id": org_unit_id,
            "org_name": org_names.get(org_unit_id or "", ""),
            "targets": targets,
            "target_total": progress["target_total"],
            "progress": progress,
            "grades": grades,
            "grade_options": [{"key": key, "label": GRADE_LABELS[key]} for key in rules["grades"]],
            "outstanding": outstanding,
            "outstanding_ratio": (
                round(outstanding * 100 / progress["target_total"], 1)
                if progress["target_total"]
                else 0.0
            ),
            "attention": attention,
            "advisory_count": advisory_count,
            "truncated": truncated,
            "missing": (
                [f"在册党员超过 {MAX_TARGETS} 人，请按支部筛选后查看"] if truncated else []
            ),
            "notices": {
                "outstanding_notice": rules["outstanding_notice"],
                "unqualified_notice": rules["unqualified_notice"],
                "feedback_notice": rules["feedback_notice"],
            },
            "notice": REVIEW_NOTICE,
            "boundary": DECISION_BOUNDARY,
        }

    @staticmethod
    def _without_placeholders(incoming: dict[str, Any]) -> dict[str, Any]:
        """丢掉第三人字段里的脱敏占位：占位不是内容，不能覆盖真实正文。"""
        return {
            key: value
            for key, value in incoming.items()
            if not (key in THIRD_PARTY_FIELDS and is_redaction_placeholder(value))
        }

    def visible_review(self, data: dict[str, Any], level: str) -> dict[str, Any]:
        """按密级脱敏（T-MEM-12）：第三人字段（党员互评等，含留痕快照）高于查看者
        等级时不返回正文；密级不高于查看者时原样返回，只补上密级标注。"""
        masked, redacted = redact_third_party(data, level=level, viewer=viewer_level(self.user))
        masked.update(annotate_level(level))
        masked["redacted_fields"] = redacted
        return masked

    async def detail(self, review_id: str) -> dict[str, Any]:
        row = await self.review_row(review_id)
        level = row.data_level or review_level().value
        revisions = [
            self.visible_review(row_data(item), level) for item in await self.revisions(review_id)
        ]
        data = self.visible_review(row_data(row), level)
        data.update(
            {
                "grade_label": GRADE_LABELS.get(row.grade, ""),
                "missing": self.missing(row),
                "advisories": self.advisories(row),
                "revisions": revisions,
                "notice": REVIEW_NOTICE,
                "boundary": DECISION_BOUNDARY,
            }
        )
        return data

    async def revisions(self, review_id: str) -> list[ContentRevision]:
        """只追加修订记录：能看到改前改后分别是什么（脱敏在 ``detail`` 出口统一做）。"""
        await self.review_row(review_id)
        return list(
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == "member_review",
                        ContentRevision.resource_id == str(review_id),
                        ContentRevision.is_deleted.is_(False),
                    )
                    .order_by(ContentRevision.revision.desc(), ContentRevision.id)
                )
            )
            .scalars()
            .all()
        )


async def own_reviews(
    db: AsyncSession, user: User, profile_id: str, *, year: int | None = None
) -> list[dict[str, Any]]:
    """本人查看自己的评议结果：只取本人档案下、且已通过审核的记录。

    ``profile_id`` 由调用方从登录账号解析得到（见 ``member_self._own_profile``），
    不接受客户端传入的目标人员编号；本人也看不到未生效的草稿或送审中版本。
    """
    stmt = select(MemberReview).where(
        MemberReview.tenant_id == str(user.tenant_id),
        MemberReview.profile_id == profile_id,
        MemberReview.is_deleted.is_(False),
        MemberReview.review_status == "approved",
    )
    if year is not None:
        stmt = stmt.where(MemberReview.year == year)
    rows = (await db.execute(stmt.order_by(MemberReview.year.desc()))).scalars().all()
    return [
        {
            "id": str(row.id),
            "year": row.year,
            "grade": row.grade,
            "grade_label": GRADE_LABELS.get(row.grade, ""),
            "basis": row.basis,
            "rectification": row.rectification,
            "branch_opinion": (row.procedure or {}).get("branch_opinion", ""),
            "reviewed_at": row.reviewed_at,
        }
        for row in rows
    ]
