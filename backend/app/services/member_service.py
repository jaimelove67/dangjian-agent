"""发展党员全流程业务闭环；阶段流转仅人工操作，规则建议不写入阶段字段。

所有读写带租户及有效组织范围；流转校验复用 business_rules 阶段规则与材料要求，
评分与档案检查仅输出辅助结果并保留证据来源，不自动形成组织认定。
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import yaml
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.config import tenant_config
from app.core.decision_boundary import ASSISTED_REFERENCE_NOTE, STAGE_TRANSITION_NOTE, evidence_note
from app.core.desensitization import mask_id_card, mask_text
from app.core.security import Permission, has_permission
from app.models.meeting import ContentRevision
from app.models.member import (
    MemberArchiveCheck,
    MemberBatch,
    MemberCultivation,
    MemberMaterial,
    MemberPoliticalReview,
    MemberProcedure,
    MemberProfile,
    MemberReminder,
    MemberStageHistory,
    MemberTraining,
    MemberVote,
)
from app.models.user import User, UserRole
from app.rules.application_form_checklist import APPLICATION_FORM_CHECKLIST
from app.rules.data_sensitivity import (
    annotate_level,
    cloud_allowed,
    level_at_least,
    material_level,
    redact_third_party,
    viewer_level,
    vote_level,
)
from app.rules.member_league import age_on
from app.rules.member_outcomes import PROBATION_OUTCOME_REASONS
from app.rules.member_secondary import SECONDARY_REVIEW_NODES
from app.rules.member_stages import (
    MIN_TRAINING_DAYS,
    MIN_TRAINING_HOURS,
    STAGE_LABELS,
    MemberStage,
    StageRules,
    add_months,
    load_stage_rules,
    political_review_blocker,
    training_blocker,
)
from app.rules.political_review import (
    POLITICAL_REVIEW_ASPECTS,
    POLITICAL_REVIEW_NEGATIVE_CATEGORIES,
)
from app.schemas.member_ext import (
    ArchiveCheckRun,
    BatchCreate,
    CultivationCreate,
    MaterialCreate,
    MaterialReview,
    PoliticalReviewCreate,
    ProcedureCreate,
    ProfileUpdate,
    ReminderResolve,
    ScoringRequest,
    TrainingCreate,
    TransitionRequest,
    VoteBatch,
)
from app.services.file_store import read_member_archive, save_member_archive
from app.services.member_archive_service import extract_material_fields, extract_scan_text
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

DECISION_BOUNDARY = STAGE_TRANSITION_NOTE
BATCH_RULES_PATH = "config/business_rules.yaml"
#: 识别文本的边界说明：随文本一起返回，界面必须显示——识别不是原件
OCR_BOUNDARY_NOTE = (
    "以下文字由系统从扫描件识别/抽取，可能存在误差或错字；"
    "材料内容与是否通过核验，仍以影像原件与人工核对为准。其中的身份证号、手机号已脱敏。"
)

#: 发展程序记录的最低登记阶段：联系人从积极分子起，介绍人/审查/志愿书从发展对象起，
#: 上级谈话从预备党员起。历史补录允许在更晚阶段登记，不改变当前阶段。
PROCEDURE_MIN_STAGE: dict[str, MemberStage] = {
    "contact": MemberStage.ACTIVIST,
    "introducer": MemberStage.CANDIDATE,
    "branch_committee_review": MemberStage.CANDIDATE,
    "upper_pre_review": MemberStage.CANDIDATE,
    "application_form": MemberStage.CANDIDATE,
    "publicity": MemberStage.CANDIDATE,
    "upper_talk": MemberStage.PROBATIONARY,
    "branch_vote": MemberStage.CANDIDATE,
    "probation_outcome": MemberStage.PROBATIONARY,
    "higher_record": MemberStage.PROBATIONARY,
    "party_group": MemberStage.PROBATIONARY,
    "secondary_review": MemberStage.ACTIVIST,
}
PROCEDURE_TITLES: dict[str, str] = {
    "contact": "培养联系人",
    "introducer": "入党介绍人",
    "branch_committee_review": "支委会审查",
    "upper_pre_review": "上级党委预审",
    "application_form": "入党志愿书",
    "publicity": "公示",
    "upper_talk": "上级党委派人谈话",
    "branch_vote": "支部大会票决",
    "probation_outcome": "预备党员转正结果",
    "higher_record": "再上一级党委组织部门备案",
    "party_group": "编入党支部和党小组",
    "secondary_review": "二级党组织审议与组织员签字",
}
PROCEDURE_STATUSES: dict[str, set[str]] = {
    "contact": {"assigned"},
    "introducer": {"confirmed"},
    "branch_committee_review": {"in_progress", "passed", "failed"},
    "upper_pre_review": {"in_progress", "passed", "supplement", "failed"},
    "application_form": {"draft", "submitted", "reviewed"},
    "publicity": {"completed"},
    "upper_talk": {"completed"},
    "branch_vote": {"passed", "not_passed"},
    "probation_outcome": {"qualified", "extended", "disqualified"},
    "higher_record": {"recorded"},
    "party_group": {"assigned"},
    "secondary_review": {"completed"},
}
PROCEDURE_REQUIREMENT = (
    "接收预备党员前应完成培养联系人、2名不同入党介绍人、支委会审查、上级党委预审和入党志愿书登记；"
    "公示应登记起止日期并按5个工作日核对。上级党委派人谈话应在上级审批前完成。"
    "预备党员转正前应登记支部大会票决和转正结果；二级党组织审议与专职组织员签字"
    "按学校节点单独登记。延长预备期作为独立记录，取消预备党员资格为终态。"
    "系统只登记事实，不替代组织程序。"
)
#: 登记权限按程序分组：支部程序由支部日常登记，上级程序由学校/院系办理；
#: 平台管理员不介入学校党务，其他角色即使具备阶段流转权限也不能代登记。
PROCEDURE_ROLE_GROUPS: dict[str, frozenset[UserRole]] = {
    "branch": frozenset({UserRole.BRANCH_SECRETARY, UserRole.ORGANIZER}),
    "upper": frozenset({UserRole.SCHOOL_ADMIN, UserRole.DEPARTMENT_ADMIN}),
}
PROCEDURE_ROLE_LABELS: dict[str, str] = {
    "branch": "支部书记或支部组织员",
    "upper": "学校管理员或院系管理员",
}
PROCEDURE_GROUP: dict[str, str] = {
    "contact": "branch",
    "introducer": "branch",
    "branch_committee_review": "branch",
    "application_form": "branch",
    "publicity": "branch",
    "upper_pre_review": "upper",
    "upper_talk": "upper",
    "branch_vote": "branch",
    "probation_outcome": "branch",
    "higher_record": "upper",
    "party_group": "branch",
    "secondary_review": "upper",
}

#: 支部大会票决事项。接收预备党员与转正分别登记，避免把两种决议混成一条。
BRANCH_VOTE_MEETING_FOR = {"reception", "conversion", "disqualification"}
BRANCH_VOTE_LABELS = {
    "reception": "接收预备党员",
    "conversion": "预备党员转正",
    "disqualification": "取消预备党员资格",
}
PROBATION_OUTCOME_LABELS = {
    "qualified": "按期转正",
    "extended": "延长预备期",
    "disqualified": "取消预备党员资格",
}
#: 流程看板单次最多汇总的档案数；超出时明确提示，不静默截断。
FLOW_BOARD_MAX_ROWS = 500


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


def _load_school_rules() -> dict[str, int]:
    """校本硬门禁配置；0 表示不启用，按档案 year 判断新老批次。"""
    try:
        with open(BATCH_RULES_PATH, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError:
        data = {}
    rules = data.get("school_rules") or {}

    def year(value: Any) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and 2000 <= value <= 2100:
            return value
        return 0

    return {
        "secondary_review_hard_gate_from_year": year(
            rules.get("secondary_review_hard_gate_from_year")
        ),
        "publicity_hard_gate_from_year": year(rules.get("publicity_hard_gate_from_year")),
    }


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

    @staticmethod
    def _validate_material_date(
        profile: MemberProfile, material_type: str, document_date: date | None
    ) -> None:
        """材料落款日期校验；入党申请书额外核验申请时年满18周岁。

        出生年月缺失时明确要求补录，不用身份证号推算、不默认通过；其他材料只校验
        日期不晚于今天，避免把未来日期当成历史事实。
        """
        if document_date and document_date > date.today():
            raise HTTPException(422, "材料落款日期不能晚于今天")
        if material_type != "入党申请书":
            return
        if document_date is None:
            raise HTTPException(
                422, "入党申请书须填写落款日期，用于核验申请时年满18周岁和申请满6个月"
            )
        if profile.birth_date is None:
            raise HTTPException(
                422, "档案缺少出生年月，无法核验入党申请书落款时是否年满18周岁；请先补录档案"
            )
        if document_date < profile.birth_date:
            raise HTTPException(422, "入党申请书落款日期不能早于出生年月，请核对档案")
        age = age_on(profile.birth_date, document_date)
        if age < 18:
            raise HTTPException(
                422,
                f"入党申请书落款日期未满18周岁（档案年龄 {age} 周岁），不能登记为有效申请",
            )

    @staticmethod
    def _stage_or_422(value: str) -> MemberStage:
        try:
            return MemberStage(value)
        except ValueError:
            raise HTTPException(422, "人员阶段无效，须先核验历史记录") from None

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
        if body.id_card_no is not None:
            await self._assign_id_card(profile, body.id_card_no)
        birth_date = body.birth_date or profile.birth_date
        league_joined_on = body.league_joined_on or profile.league_joined_on
        if birth_date and league_joined_on and league_joined_on < birth_date:
            raise HTTPException(422, "入团时间不能早于出生年月，请核对档案")
        if body.birth_date is not None:
            profile.birth_date = body.birth_date
        if body.league_joined_on is not None:
            profile.league_joined_on = body.league_joined_on
        if body.batch_no is not None:
            profile.batch_no = body.batch_no
        if body.year is not None:
            profile.year = body.year
        if body.is_active is not None:
            profile.is_active = body.is_active
        await self.save_profile_revision(profile, "revise", body.reason)
        return profile

    async def _assign_id_card(self, profile: MemberProfile, id_card_no: str) -> None:
        """补录或更正身份证号。

        身份证号是开户时的登录账号来源，因此必须租户内唯一，也不能撞上已有账号的登录名。
        但它只影响"以后开户用哪个号"：既有账号的登录名不跟着改——
        档案更正不等于账号变更，改登录名目前不开放（UserUpdate 不含 username），
        静默改名会把正在使用的人挡在门外。
        """
        if profile.id_card_no == id_card_no:
            return
        occupied_by = await self.db.scalar(
            select(MemberProfile.name).where(
                MemberProfile.tenant_id == profile.tenant_id,
                MemberProfile.id_card_no == id_card_no,
                MemberProfile.id != profile.id,
            )
        )
        if occupied_by:
            raise HTTPException(409, f"该身份证号已登记在「{occupied_by}」的档案中，请先核对")
        account_conditions = [User.username == id_card_no]
        if profile.user_id:
            account_conditions.append(User.id != profile.user_id)
        if await self.db.scalar(select(User.id).where(*account_conditions)):
            raise HTTPException(409, "该身份证号已被其他账号用作登录名，请先核对")
        profile.id_card_no = id_card_no

    async def attach_scan(
        self,
        profile_id: str,
        *,
        file_name: str,
        content: bytes,
        material_type: str,
        note: str = "",
        cloud_ocr: bool = False,
        document_date: date | None = None,
        submit_date: date | None = None,
        file_version: str = "扫描归档",
    ) -> tuple[MemberMaterial, list[str]]:
        """干事代扫归档：影像进加密文件卷，识别文本入台账，材料记为待核验。

        归档与核验是两件事：这里只登记"组织已经收到这份材料"，是否通过仍要人工审核。
        入党申请书的落款日期必须在归档前校验，避免先落文件、后因年龄/日期不合格
        留下无法解释的影像件。
        """
        profile = await self.profile(profile_id, lock=True)
        self._validate_material_date(profile, material_type, document_date)
        material_id = str(uuid4())
        stored = save_member_archive(self.tenant_id, material_id, content)
        level = material_level(material_type)
        # 敏感 / 涉密材料不出网：勾了云端识别也不发，只留影像
        cloud = cloud_ocr and cloud_allowed(level)
        scan = await extract_scan_text(
            content,
            file_name=file_name,
            cloud_ocr=cloud,
            context={"tenant_id": self.tenant_id, "user_id": str(self.user.id)},
        )
        notes = list(scan.notes)
        if cloud_ocr and not cloud:
            notes.insert(0, "该材料按密级不允许出网识别，已只保存影像件。")
        # 识别成功才抽字段：同一次同意、同一份材料再出网一次文本（不含影像）。
        # 抽到的是建议值，只为帮人核对，不写进任何台账字段。
        fields: dict[str, Any] = {}
        if scan.done and cloud:
            fields = await extract_material_fields(
                scan.text,
                context={
                    "tenant_id": self.tenant_id,
                    "user_id": str(self.user.id),
                    "material_id": material_id,
                },
            )
        material = MemberMaterial(
            id=material_id,
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            stage=profile.current_stage,
            material_type=material_type,
            data_level=level.value,
            file_version=file_version,
            document_date=document_date,
            submit_date=submit_date or date.today(),
            submitter_id=str(self.user.id),
            review_status="pending",
            note=note,
            title=material_type,
            category="archive",
            description="组织扫描归档",
            file_name=file_name,
            file_size=stored["size"],
            content_sha256=stored["sha256"],
            file_path=stored["path"],
            extracted_text=scan.text,
            ocr_status=scan.status,
            ocr_pages=scan.pages,
            extracted_fields=fields,
        )
        self.db.add(material)
        await self.db.flush()
        return material, notes

    async def material_original(self, material_id: str) -> tuple[MemberMaterial, bytes]:
        record = await self.db.scalar(
            select(MemberMaterial)
            .options(undefer(MemberMaterial.content))
            .where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == self.tenant_id,
                MemberMaterial.is_deleted.is_(False),
            )
        )
        if record is None:
            raise HTTPException(404, "材料不存在")
        await self.profile(str(record.profile_id))
        level = record.data_level or material_level(record.material_type).value
        if not level_at_least(viewer_level(self.user), level):
            raise HTTPException(403, "这份材料的敏感级别高于你的查看权限")
        content = record.content
        if content is None and record.file_path:
            content = read_member_archive(record.file_path, record.content_sha256)
        if content is None:
            raise HTTPException(404, "该材料没有原件文件")
        return record, content

    async def material_text(self, material_id: str) -> dict[str, Any]:
        """读取识别文本：先校验材料属于本人可见档案，再单独取 deferred 列。"""
        record = await self.db.scalar(
            select(MemberMaterial)
            .options(undefer(MemberMaterial.extracted_text))
            .where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == self.tenant_id,
                MemberMaterial.is_deleted.is_(False),
            )
        )
        if record is None:
            raise HTTPException(404, "材料不存在")
        await self.profile(str(record.profile_id))
        level = record.data_level or material_level(record.material_type).value
        viewer = viewer_level(self.user)
        if not level_at_least(viewer, level):
            raise HTTPException(403, "这份材料的敏感级别高于你的查看权限")
        return {
            "material_id": str(record.id),
            "material_type": record.material_type,
            "ocr_status": record.ocr_status,
            "ocr_pages": record.ocr_pages,
            "text": mask_text(record.extracted_text or ""),
            # 抽取建议值随文本一起给：界面并排展示"原件说了什么 / 系统认成什么"
            "fields": record.extracted_fields or {},
            "note": OCR_BOUNDARY_NOTE,
        }

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
                snapshot=self._snapshot(profile),
            )
        )
        await self.db.flush()

    @staticmethod
    def _snapshot(profile: MemberProfile) -> dict[str, Any]:
        """版本快照：身份证号只留脱敏值，完整号不落版本表。"""
        data = row_data(profile)
        raw = data.get("id_card_no")
        data["id_card_no"] = mask_id_card(raw) if raw else None
        return data

    # ==================== 材料记录 ====================

    async def add_material(self, profile_id: str, body: MaterialCreate) -> MemberMaterial:
        profile = await self.profile(profile_id, lock=True)
        self._validate_material_date(profile, body.material_type, body.document_date)
        material = MemberMaterial(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            stage=body.stage or profile.current_stage,
            material_type=body.material_type,
            data_level=material_level(body.material_type).value,
            file_version=body.file_version,
            document_date=body.document_date,
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
        # 识别文本可能几万字：回显只给状态与页数，正文单独走 material_text
        data.pop("extracted_text", None)
        data.pop("file_path", None)
        data["has_file"] = bool(getattr(material, "file_path", "") or data.get("content_sha256"))
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
        items = []
        for record in records:
            data = row_data(record)
            # 影像件在文件卷里，路径不对外露；界面只关心"能不能打开原件"。
            # 识别正文可能几万字，列表不返回（同一个会话里对象被 undefer 过也要摘掉）
            data.pop("file_path", None)
            data.pop("extracted_text", None)
            data["has_file"] = bool(record.file_path or record.content_sha256)
            # 本人提交与组织登记共用一张材料表：来源只用于展示和过滤，
            # 个人材料没有 material_type，不能计入发展材料核验或阶段流转。
            data["source"] = (
                "personal" if record.user_id or record.submission_key else "development"
            )
            items.append(data)
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
                        "source": "legacy",
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

    async def policy_checks(
        self,
        profile_id: str,
        materials: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """校本时限核对：返回可自动核算的提示，不把人工判断伪装成系统结论。

        核对谈话、公示、季度汇报、半年考察、转正申请和上级预审等已经登记的事实；
        没有登记起止日期的项目明确返回待登记或待核对，不用其他日期倒推。
        """
        if materials is None:
            materials = await self.list_materials(profile_id)
        profile = await self.profile(profile_id)
        publicity = await self._current_procedure(profile_id, "publicity")

        def material_date(item: dict[str, Any], *, use_submit_fallback: bool = True) -> date | None:
            value = item.get("document_date")
            if not value and use_submit_fallback:
                value = item.get("submit_date")
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str) and value:
                try:
                    return date.fromisoformat(value[:10])
                except ValueError:
                    return None
            return None

        approved = [
            item
            for item in materials
            if item.get("review_status") == "approved" and not item.get("legacy_material")
        ]
        application_dates = [
            value
            for item in approved
            if item.get("material_type") == "入党申请书"
            if (value := material_date(item, use_submit_fallback=False)) is not None
        ]
        talk_dates = [
            value
            for item in approved
            if item.get("material_type") == "党组织谈话记录"
            if (value := material_date(item)) is not None
        ]
        application_on = min(application_dates) if application_dates else None
        if application_on is not None:
            after_application = [value for value in talk_dates if value >= application_on]
            talk_on = (
                min(after_application)
                if after_application
                else (min(talk_dates) if talk_dates else None)
            )
        else:
            talk_on = min(talk_dates) if talk_dates else None
        deadline = add_months(application_on, 1) if application_on else None
        if application_on is None:
            talk_check = {
                "status": "unknown",
                "label": "待补录",
                "message": "未登记已核验入党申请书的落款日期，无法核算 1 个月谈话时限。",
            }
        elif talk_on is None:
            talk_check = {
                "status": "pending",
                "label": "待补录",
                "message": f"应在 {deadline.isoformat()} 前完成谈话并归档记录。",
            }
        elif talk_on < application_on:
            talk_check = {
                "status": "invalid",
                "label": "待核对",
                "message": f"谈话日期 {talk_on.isoformat()} 早于申请日期 {application_on.isoformat()}，请核对材料。",
            }
        elif talk_on > deadline:
            talk_check = {
                "status": "overdue",
                "label": "已超期",
                "message": (
                    f"谈话日期 {talk_on.isoformat()} 晚于应完成日期 {deadline.isoformat()}；"
                    "细则要求收到申请书后 1 个月内派人谈话。"
                ),
            }
        else:
            talk_check = {
                "status": "ok",
                "label": "符合",
                "message": f"谈话日期 {talk_on.isoformat()}，在 {deadline.isoformat()} 前完成。",
            }
        publicity_details = (publicity.details or {}) if publicity else {}
        try:
            publicity_days = int(publicity_details.get("working_days") or 0)
        except (TypeError, ValueError):
            publicity_days = 0
        publicity_hard_gate = self._school_gate_enabled(profile, "publicity_hard_gate_from_year")
        if publicity is None:
            publicity_check = {
                "status": "pending",
                "label": "待登记",
                "hard_gate": publicity_hard_gate,
                "message": (
                    "细则要求公示 5 个工作日；请在“发展程序”中登记公示起止日期，"
                    "系统按周一至周五核算，不替代“公示情况报告”原件。"
                ),
            }
        elif publicity_days < 5:
            publicity_check = {
                "status": "invalid",
                "label": "待核对",
                "hard_gate": publicity_hard_gate,
                "message": f"已登记公示 {publicity_days} 个工作日，未满 5 个工作日，请核对起止日期。",
            }
        else:
            publicity_check = {
                "status": "ok",
                "label": "符合",
                "hard_gate": publicity_hard_gate,
                "message": (
                    f"公示期 {publicity_details.get('start_on', '未登记')} 至 "
                    f"{publicity_details.get('end_on', '未登记')}，"
                    f"共 {publicity_days} 个工作日。"
                ),
            }

        def latest_material_on(types: set[str]) -> date | None:
            dates = [
                value
                for item in approved
                if item.get("material_type") in types
                if (value := material_date(item)) is not None
            ]
            return max(dates) if dates else None

        stage = profile.current_stage
        today = date.today()
        report_latest = latest_material_on({"思想汇报"})
        report_due = (report_latest or profile.stage_joined_on) + timedelta(days=90)
        if stage not in {"activist", "candidate", "probationary"}:
            quarterly_check = {
                "status": "not_applicable",
                "label": "不适用",
                "message": "",
            }
        elif report_latest is None:
            quarterly_check = {
                "status": "pending",
                "label": "待登记",
                "message": f"本阶段尚未登记思想汇报；应在 {report_due.isoformat()} 前完成首次季度汇报。",
            }
        elif today > report_due:
            quarterly_check = {
                "status": "overdue",
                "label": "已超期",
                "message": f"最近一次思想汇报为 {report_latest.isoformat()}，下一季度汇报应在 {report_due.isoformat()} 前完成。",
            }
        else:
            quarterly_check = {
                "status": "ok",
                "label": "符合",
                "message": f"最近一次思想汇报为 {report_latest.isoformat()}，下一季度汇报应在 {report_due.isoformat()} 前完成。",
            }

        review_types = {"预备期考察记录"} if stage == "probationary" else {"培养考察记录"}
        review_latest = latest_material_on(review_types)
        review_due = (review_latest or profile.stage_joined_on) + timedelta(days=180)
        if stage not in {"activist", "candidate", "probationary"}:
            semi_annual_check = {
                "status": "not_applicable",
                "label": "不适用",
                "message": "",
            }
        elif review_latest is None:
            semi_annual_check = {
                "status": "pending",
                "label": "待登记",
                "message": f"本阶段尚未登记培养考察记录；应在 {review_due.isoformat()} 前完成首次半年考察。",
            }
        elif today > review_due:
            semi_annual_check = {
                "status": "overdue",
                "label": "已超期",
                "message": f"最近一次培养考察记录为 {review_latest.isoformat()}，下一次半年考察应在 {review_due.isoformat()} 前完成。",
            }
        else:
            semi_annual_check = {
                "status": "ok",
                "label": "符合",
                "message": f"最近一次培养考察记录为 {review_latest.isoformat()}，下一次半年考察应在 {review_due.isoformat()} 前完成。",
            }

        transfer_application = latest_material_on({"转正申请书"})
        transfer_due = profile.stage_joined_on + timedelta(days=365)
        transfer_apply_by = transfer_due - timedelta(days=7)
        if stage != "probationary":
            transfer_check = {
                "status": "not_applicable",
                "label": "不适用",
                "message": "",
            }
        elif transfer_application is None:
            transfer_check = {
                "status": "pending",
                "label": "待提交",
                "message": f"预备期满前一周提出转正申请，应在 {transfer_apply_by.isoformat()} 前完成。",
            }
        elif transfer_application > transfer_apply_by:
            transfer_check = {
                "status": "overdue",
                "label": "已超期",
                "message": f"转正申请日期 {transfer_application.isoformat()} 晚于应提出日期 {transfer_apply_by.isoformat()}。",
            }
        else:
            transfer_check = {
                "status": "ok",
                "label": "符合",
                "message": f"转正申请日期 {transfer_application.isoformat()}，不晚于 {transfer_apply_by.isoformat()}。",
            }

        pre_review = await self._current_procedure(profile_id, "upper_pre_review")
        pre_review_details = (pre_review.details or {}) if pre_review else {}
        submitted_raw = pre_review_details.get("submitted_on")
        submitted_on: date | None = None
        if isinstance(submitted_raw, str) and submitted_raw:
            try:
                submitted_on = date.fromisoformat(submitted_raw[:10])
            except ValueError:
                submitted_on = None
        if stage != "candidate":
            pre_review_check = {
                "status": "not_applicable",
                "label": "不适用",
                "message": "",
            }
        elif pre_review is None:
            pre_review_check = {
                "status": "pending",
                "label": "待登记",
                "message": "尚未登记上级党委预审；请先登记报送日期和预审结论。",
            }
        elif submitted_on is None:
            pre_review_check = {
                "status": "unknown",
                "label": "待补录",
                "message": "预审记录缺少报送日期，无法核算 1 个月时限；请补录后核对。",
            }
        else:
            pre_due = add_months(submitted_on, 1)
            if pre_review.occurred_on > pre_due:
                pre_review_check = {
                    "status": "overdue",
                    "label": "已超期",
                    "message": f"预审日期 {pre_review.occurred_on.isoformat()} 晚于应完成日期 {pre_due.isoformat()}。",
                }
            else:
                pre_review_check = {
                    "status": "ok",
                    "label": "符合",
                    "message": f"预审日期 {pre_review.occurred_on.isoformat()}，在 {pre_due.isoformat()} 前完成。",
                }

        application_form = await self._current_procedure(profile_id, "application_form")
        form_checklist = (
            (application_form.details or {}).get("checklist", []) if application_form else []
        )
        if not isinstance(form_checklist, list):
            form_checklist = []
        if stage != "candidate":
            form_check = {
                "status": "not_applicable",
                "label": "不适用",
                "message": "",
            }
        elif application_form is None:
            form_check = {
                "status": "pending",
                "label": "待登记",
                "message": "尚未登记入党志愿书；请填写后逐项核对 19 项规范。",
            }
        elif application_form.status == "draft":
            form_check = {
                "status": "pending",
                "label": "填写中",
                "message": f"志愿书正在填写；已勾选 {len(form_checklist)}/{len(APPLICATION_FORM_CHECKLIST)} 项。",
            }
        elif len(form_checklist) < len(APPLICATION_FORM_CHECKLIST):
            form_check = {
                "status": "pending",
                "label": "待核对",
                "message": f"志愿书核对清单已勾选 {len(form_checklist)}/{len(APPLICATION_FORM_CHECKLIST)} 项。",
            }
        else:
            form_check = {
                "status": "ok",
                "label": "符合",
                "message": f"志愿书核对清单已勾选 {len(APPLICATION_FORM_CHECKLIST)} 项。",
            }

        secondary_items = [
            row for row in await self._procedure_rows(profile_id) if row.kind == "secondary_review"
        ]
        secondary_nodes = {(row.details or {}).get("node") for row in secondary_items}
        if stage == "activist":
            required_nodes = ("candidate_determination",)
        elif stage == "candidate":
            required_nodes = (
                "candidate_determination",
                "pre_reception",
                "reception",
            )
        elif stage == "probationary":
            required_nodes = ("conversion",)
        else:
            required_nodes = ()
        secondary_hard_gate = self._school_gate_enabled(
            profile, "secondary_review_hard_gate_from_year"
        )
        if not required_nodes:
            secondary_check = {
                "status": "not_applicable",
                "label": "不适用",
                "hard_gate": False,
                "message": "",
            }
        else:
            missing_nodes = [
                SECONDARY_REVIEW_NODES[node]["label"]
                for node in required_nodes
                if node not in secondary_nodes
            ]
            if missing_nodes:
                secondary_check = {
                    "status": "pending",
                    "label": "待登记",
                    "hard_gate": secondary_hard_gate,
                    "message": "待登记二级党组织审议与组织员签字："
                    + "、".join(str(label) for label in missing_nodes),
                }
            else:
                secondary_check = {
                    "status": "ok",
                    "label": "符合",
                    "hard_gate": secondary_hard_gate,
                    "message": "本阶段要求的二级党组织审议与组织员签字已登记。",
                }

        return {
            "talk_within_one_month": talk_check,
            "publicity_five_workdays": publicity_check,
            "quarterly_report": quarterly_check,
            "semi_annual_review": semi_annual_check,
            "transfer_application": transfer_check,
            "upper_pre_review_within_one_month": pre_review_check,
            "application_form_checklist": form_check,
            "secondary_review": secondary_check,
        }

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
        if material.user_id or material.submission_key:
            raise HTTPException(422, "个人提交材料不纳入发展材料核验，请另行登记发展材料")
        profile = await self.profile(str(material.profile_id))
        # 历史材料没有落款日期时，允许在核验时按原件补录；基线快照保留补录前的状态。
        effective_date = (
            body.document_date if body.document_date is not None else material.document_date
        )
        if body.review_status == "approved":
            self._validate_material_date(profile, material.material_type, effective_date)
        elif effective_date and effective_date > date.today():
            raise HTTPException(422, "材料落款日期不能晚于今天")
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
        if body.document_date is not None:
            material.document_date = body.document_date
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
        approved_rows = (
            await self.db.execute(
                select(
                    MemberMaterial.material_type,
                    MemberMaterial.document_date,
                    MemberMaterial.submit_date,
                ).where(
                    MemberMaterial.tenant_id == self.tenant_id,
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.review_status == "approved",
                    MemberMaterial.is_deleted.is_(False),
                    # 个人提交材料只作展示，不得满足发展材料要求或成为 6 个月锚点。
                    MemberMaterial.user_id.is_(None),
                    MemberMaterial.submission_key.is_(None),
                )
            )
        ).all()
        approved = {row.material_type for row in approved_rows}
        missing = [name for name in rule.required_materials if name not in approved]
        if missing:
            raise HTTPException(422, "材料未齐或未核验通过：" + "、".join(missing))

        # "申请满 6 个月"以最早一份已核验入党申请书的落款日期为锚点，不能用建档日期
        # 或组织收到日期代替。落款日期缺失时不默认通过，要求先补录。
        application_dates = [
            row.document_date
            for row in approved_rows
            if row.material_type == "入党申请书" and row.document_date is not None
        ]
        application_date: date | None = min(application_dates) if application_dates else None
        if application_date and body.decision_date < application_date:
            raise HTTPException(422, "决策日期不能早于入党申请书落款日期")
        from_application = (
            profile.current_stage == MemberStage.APPLICANT.value
            and body.target_stage == MemberStage.ACTIVIST.value
        )
        if from_application:
            # 历史已核验材料可能早于本次校验上线；流转时再核一次，避免旧数据绕过 18 周岁规则。
            if profile.birth_date is None:
                raise HTTPException(
                    422,
                    "档案缺少出生年月，无法核验申请时年满18周岁；请先补录档案信息",
                )
            if application_date and age_on(profile.birth_date, application_date) < 18:
                raise HTTPException(
                    422,
                    "入党申请书落款日期时未满18周岁，不能确定为入党积极分子",
                )
        if rule.min_days > 0:
            stayed = (body.decision_date - profile.stage_joined_on).days
            if stayed < rule.min_days:
                raise HTTPException(422, f"未满足最短时限：需 {rule.min_days} 天，当前 {stayed} 天")
        if rule.min_months > 0:
            anchor = application_date if from_application else profile.stage_joined_on
            if anchor is None:
                raise HTTPException(
                    422,
                    "入党申请书缺少落款日期，无法核算申请满6个月；请先在材料记录中补录落款日期",
                )
            earliest = add_months(anchor, rule.min_months)
            if body.decision_date < earliest:
                raise HTTPException(
                    422,
                    f"未满足最短时限：需满 {rule.min_months} 个月，"
                    f"最早可于 {earliest.isoformat()} 办理"
                    + (f"（入党申请书落款 {anchor.isoformat()}）" if from_application else ""),
                )

        # 接收预备党员前的硬前置：政审须有明确合格结论，集中培训不少于 3 天 / 24 学时。
        # 这两项只校验事实是否具备，不替代支部大会、公示和上级审批。
        if (
            profile.current_stage == MemberStage.CANDIDATE.value
            and body.target_stage == MemberStage.PROBATIONARY.value
        ):
            review = await self._latest_political_review(str(profile.id))
            blocker = political_review_blocker(review.status if review else None)
            if blocker:
                raise HTTPException(422, blocker)
            training = await self._best_training(str(profile.id))
            blocker = training_blocker(
                training.days if training else None,
                training.hours if training else None,
            )
            if blocker:
                raise HTTPException(422, blocker)

        # 程序性前置：培养联系人、入党介绍人、支委会审查、上级党委预审和入党志愿书。
        # 系统只核对组织已登记的事实，不代替支部大会、公示或上级审批；缺项时要求补录。
        if (
            profile.current_stage == MemberStage.ACTIVIST.value
            and body.target_stage == MemberStage.CANDIDATE.value
        ):
            contact = await self._current_procedure(str(profile.id), "contact")
            if contact is None:
                raise HTTPException(
                    422,
                    "培养联系人未登记，请先在“发展程序”中登记培养联系人",
                )
            procedures = await self._procedure_rows(str(profile.id))
            if self._school_gate_enabled(
                profile, "secondary_review_hard_gate_from_year"
            ) and "candidate_determination" not in self._secondary_nodes(procedures):
                raise HTTPException(
                    422,
                    "本校硬控批次确定发展对象前须登记二级党组织会议审议和专职组织员签字",
                )
        if (
            profile.current_stage == MemberStage.CANDIDATE.value
            and body.target_stage == MemberStage.PROBATIONARY.value
        ):
            contact = await self._current_procedure(str(profile.id), "contact")
            if contact is None:
                raise HTTPException(
                    422,
                    "培养联系人未登记，请先在“发展程序”中登记培养联系人",
                )
            introducers = [
                row
                for row in await self._procedure_rows(str(profile.id))
                if row.kind == "introducer"
            ]
            if len({self._introducer_key(row) for row in introducers}) < 2:
                raise HTTPException(
                    422,
                    "入党介绍人须登记2名不同正式党员，请先在“发展程序”中补齐入党介绍人",
                )
            branch_review = await self._current_procedure(
                str(profile.id), "branch_committee_review"
            )
            if branch_review is None or branch_review.status != "passed":
                raise HTTPException(
                    422,
                    "支委会审查未通过或未登记，请先在“发展程序”中登记审查结论",
                )
            pre_review = await self._current_procedure(str(profile.id), "upper_pre_review")
            if pre_review is None or pre_review.status != "passed":
                raise HTTPException(
                    422,
                    "上级党委预审未通过或未登记，请先在“发展程序”中登记预审结论",
                )
            application_form = await self._current_procedure(str(profile.id), "application_form")
            if application_form is None or application_form.status not in {
                "submitted",
                "reviewed",
            }:
                raise HTTPException(
                    422,
                    "入党志愿书未提交或未登记，请先在“发展程序”中登记入党志愿书",
                )
            procedures = await self._procedure_rows(str(profile.id))
            if self._school_gate_enabled(profile, "secondary_review_hard_gate_from_year"):
                required_nodes = {
                    "candidate_determination": "确定发展对象",
                    "pre_reception": "接收预备党员前支委会审查",
                    "reception": "接收预备党员支部大会",
                }
                nodes = self._secondary_nodes(procedures)
                missing_nodes = [
                    label for code, label in required_nodes.items() if code not in nodes
                ]
                if missing_nodes:
                    raise HTTPException(
                        422,
                        "本校硬控批次缺少二级党组织审议与组织员签字：" + "、".join(missing_nodes),
                    )
            if self._school_gate_enabled(
                profile, "publicity_hard_gate_from_year"
            ) and not self._publicity_ready(procedures):
                raise HTTPException(
                    422,
                    "本校硬控批次接收预备党员前须登记公示起止日期并满5个工作日",
                )

        # 预备党员转正与取消资格：只核对组织已经登记的票决和结论事实，不按票数
        # 自动判定结果，也不把上级审批回填当成支部大会前的前置。
        if (
            profile.current_stage == MemberStage.PROBATIONARY.value
            and body.target_stage == MemberStage.MEMBER.value
        ):
            outcome = await self._current_procedure(str(profile.id), "probation_outcome")
            if outcome is None:
                raise HTTPException(
                    422,
                    "预备党员转正结果未登记，请先在“发展程序”中登记支部大会形成的转正结论",
                )
            if outcome.status == "extended":
                until = self._procedure_effective_until(outcome)
                raise HTTPException(
                    422,
                    "当前转正结果为延长预备期"
                    + (f"，最早可于 {until.isoformat()} 后办理" if until else "，不能办理按期转正"),
                )
            if outcome.status != "qualified":
                raise HTTPException(
                    422,
                    "当前转正结果不是按期转正；取消预备党员资格须通过对应阶段变更办理",
                )
            vote = await self._current_branch_vote(str(profile.id), "conversion")
            if vote is None:
                raise HTTPException(
                    422,
                    "支部大会转正票决未登记，请先在“发展程序”中登记票决结果",
                )
            if vote.status != "passed":
                raise HTTPException(422, "支部大会转正票决未通过，不能办理按期转正")
            procedures = await self._procedure_rows(str(profile.id))
            if self._school_gate_enabled(
                profile, "secondary_review_hard_gate_from_year"
            ) and "conversion" not in self._secondary_nodes(procedures):
                raise HTTPException(
                    422,
                    "本校硬控批次预备党员转正前须登记二级党组织会议审议和专职组织员签字",
                )

        if (
            profile.current_stage == MemberStage.PROBATIONARY.value
            and body.target_stage == MemberStage.DISQUALIFIED.value
        ):
            outcome = await self._current_procedure(str(profile.id), "probation_outcome")
            if outcome is None or outcome.status != "disqualified":
                raise HTTPException(
                    422,
                    "取消预备党员资格的转正结果未登记，请先在“发展程序”中登记组织结论",
                )
            vote = await self._current_branch_vote(str(profile.id), "conversion")
            if vote is None:
                vote = await self._current_branch_vote(str(profile.id), "disqualification")
            if vote is None:
                raise HTTPException(
                    422,
                    "支部大会讨论票决未登记，请先在“发展程序”中登记票决事实",
                )

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
        from_stage = profile.current_stage
        self.db.add(history)
        profile.current_stage = body.target_stage
        profile.stage_joined_on = body.decision_date
        await self.db.flush()
        if from_stage == MemberStage.PROBATIONARY.value and body.target_stage in {
            MemberStage.MEMBER.value,
            MemberStage.DISQUALIFIED.value,
        }:
            # 转正或取消资格后，原预备期到期 / 材料提醒不再适用；18/19/20 的
            # 任务提醒继续保留，直到备案、编组或宣誓实际办结。
            for reminder_kind in (
                "probationary_expiration",
                "probationary_expiration_advance",
                "material_submission",
                "material_submission_advance",
            ):
                await self._close_reminders(
                    str(profile.id),
                    reminder_kind,
                    "已办理预备党员转正结果",
                )
            if body.target_stage == MemberStage.DISQUALIFIED.value:
                for reminder_kind in ("higher_record", "party_group", "oath"):
                    await self._close_reminders(
                        str(profile.id),
                        reminder_kind,
                        "已办理取消预备党员资格",
                    )
        return profile

    async def _latest_political_review(self, profile_id: str) -> MemberPoliticalReview | None:
        """当前政审结论：按审查日期、登记时间、编号取最新一条。"""
        return (
            await self.db.execute(
                select(MemberPoliticalReview)
                .where(
                    MemberPoliticalReview.tenant_id == self.tenant_id,
                    MemberPoliticalReview.profile_id == profile_id,
                    MemberPoliticalReview.is_deleted.is_(False),
                )
                .order_by(
                    MemberPoliticalReview.reviewed_on.desc(),
                    MemberPoliticalReview.created_at.desc(),
                    MemberPoliticalReview.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _best_training(self, profile_id: str) -> MemberTraining | None:
        """取已登记培训中天数 / 学时最多的一条；任一条达标即可满足前置。"""
        rows = (
            (
                await self.db.execute(
                    select(MemberTraining).where(
                        MemberTraining.tenant_id == self.tenant_id,
                        MemberTraining.profile_id == profile_id,
                        MemberTraining.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None

        def rank(row: MemberTraining) -> tuple[bool, int, int, date, datetime]:
            qualifies = (row.days or 0) >= MIN_TRAINING_DAYS or (
                row.hours or 0
            ) >= MIN_TRAINING_HOURS
            return (
                qualifies,
                row.days or 0,
                row.hours or 0,
                row.end_on,
                row.created_at or datetime.min,
            )

        return max(rows, key=rank)

    async def add_political_review(
        self, profile_id: str, body: PoliticalReviewCreate
    ) -> MemberPoliticalReview:
        profile = await self.profile(profile_id)
        rank = self.rules.development_rank(self._stage_or_422(profile.current_stage))
        candidate_rank = self.rules.development_rank(MemberStage.CANDIDATE)
        if rank is None or candidate_rank is None or rank < candidate_rank:
            raise HTTPException(422, "政治审查应在确定为发展对象后登记，请先核对发展阶段")
        if body.material_id:
            material = await self.db.scalar(
                select(MemberMaterial).where(
                    MemberMaterial.id == body.material_id,
                    MemberMaterial.tenant_id == self.tenant_id,
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.is_deleted.is_(False),
                )
            )
            if material is None:
                raise HTTPException(422, "关联的政审材料不存在或不属于该档案")
            if material.user_id or material.submission_key:
                raise HTTPException(422, "个人提交材料不能作为政审结论的依据材料")
            if material.material_type != "政治审查材料":
                raise HTTPException(422, "关联材料类型须为政治审查材料")
        unknown_checks = set(body.content_checks) - set(POLITICAL_REVIEW_ASPECTS)
        if unknown_checks:
            raise HTTPException(422, "政审内容核对项无效")
        content_checks = {
            code: bool(body.content_checks.get(code, False)) for code in POLITICAL_REVIEW_ASPECTS
        }
        if body.status in {"passed", "failed"} and not all(content_checks.values()):
            raise HTTPException(
                422,
                "形成政审结论前须核对四项内容：" + "、".join(POLITICAL_REVIEW_ASPECTS.values()),
            )
        invalid_negative = set(body.negative_categories) - set(POLITICAL_REVIEW_NEGATIVE_CATEGORIES)
        if invalid_negative:
            raise HTTPException(422, "政审不合格情形分类无效")
        negative_categories = [
            code
            for code in POLITICAL_REVIEW_NEGATIVE_CATEGORIES
            if code in set(body.negative_categories)
        ]
        checklist = {
            "content_checks": content_checks,
            "negative_categories": negative_categories,
        }
        latest = await self.db.scalar(
            select(func.max(MemberPoliticalReview.revision)).where(
                MemberPoliticalReview.tenant_id == self.tenant_id,
                MemberPoliticalReview.profile_id == str(profile.id),
            )
        )
        record = MemberPoliticalReview(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            status=body.status,
            reviewed_on=body.reviewed_on,
            reviewed_by=str(self.user.id),
            scope=body.scope,
            conclusion=body.conclusion,
            note=body.note,
            reason=body.reason,
            material_id=body.material_id,
            checklist=checklist,
            data_level="sensitive",
            revision=(latest or 0) + 1,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def political_reviews(self, profile_id: str) -> dict[str, Any]:
        profile = await self.profile(profile_id)
        records = (
            (
                await self.db.execute(
                    select(MemberPoliticalReview)
                    .where(
                        MemberPoliticalReview.tenant_id == self.tenant_id,
                        MemberPoliticalReview.profile_id == str(profile.id),
                        MemberPoliticalReview.is_deleted.is_(False),
                    )
                    .order_by(
                        MemberPoliticalReview.reviewed_on.desc(),
                        MemberPoliticalReview.created_at.desc(),
                        MemberPoliticalReview.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        viewer = viewer_level(self.user)
        # 政审状态、日期、范围供有查询权的组织角色核对；完整结论只给有阶段办理权的角色。
        can_read_conclusion = has_permission(self.user.role, Permission.STAGE_TRANSITION)
        items = []
        for index, record in enumerate(records):
            data = row_data(record)
            data["status_label"] = {
                "in_progress": "审查中",
                "passed": "合格",
                "failed": "不合格",
            }.get(record.status, "状态待核对")
            data["is_current"] = index == 0
            if not can_read_conclusion:
                data["conclusion"] = ""
                data["note"] = ""
                data["reason"] = ""
                data["conclusion_restricted"] = True
            level = record.data_level or "sensitive"
            masked, redacted = redact_third_party(data, level=level, viewer=viewer)
            masked.update(annotate_level(level))
            masked["redacted_fields"] = redacted
            items.append(masked)
        current = items[0] if items else None
        status = current["status"] if current else None
        notice = {
            None: "尚未登记政治审查结论",
            "in_progress": "政治审查进行中，尚未形成结论",
            "passed": "政治审查结论为合格",
            "failed": "政治审查结论为不合格，不能办理接收预备党员",
        }.get(status, "政治审查结论状态待核对")
        return {
            "items": items,
            "current": current,
            "satisfied": status == "passed",
            "notice": notice,
            "requirement": "接收预备党员前须有组织形成的政审合格结论；原始政审材料按涉密级管理",
            **annotate_level("sensitive"),
        }

    async def add_training(self, profile_id: str, body: TrainingCreate) -> MemberTraining:
        profile = await self.profile(profile_id)
        rank = self.rules.development_rank(self._stage_or_422(profile.current_stage))
        candidate_rank = self.rules.development_rank(MemberStage.CANDIDATE)
        if rank is None or candidate_rank is None or rank < candidate_rank:
            raise HTTPException(422, "集中培训应在确定为发展对象后登记，请先核对发展阶段")
        if body.certificate_material_id:
            material = await self.db.scalar(
                select(MemberMaterial).where(
                    MemberMaterial.id == body.certificate_material_id,
                    MemberMaterial.tenant_id == self.tenant_id,
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.is_deleted.is_(False),
                )
            )
            if material is None:
                raise HTTPException(422, "关联的培训证明材料不存在或不属于该档案")
            if material.user_id or material.submission_key:
                raise HTTPException(422, "个人提交材料不能作为培训证明依据")
            if material.material_type != "党课培训证明":
                raise HTTPException(422, "关联材料类型须为党课培训证明")
        latest = await self.db.scalar(
            select(func.max(MemberTraining.revision)).where(
                MemberTraining.tenant_id == self.tenant_id,
                MemberTraining.profile_id == str(profile.id),
            )
        )
        record = MemberTraining(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            training_type=body.training_type,
            start_on=body.start_on,
            end_on=body.end_on,
            days=body.days,
            hours=body.hours,
            issuer=body.issuer,
            certificate_material_id=body.certificate_material_id,
            note=body.note,
            reason=body.reason,
            data_level="internal",
            revision=(latest or 0) + 1,
            created_by=str(self.user.id),
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def trainings(self, profile_id: str) -> dict[str, Any]:
        profile = await self.profile(profile_id)
        records = (
            (
                await self.db.execute(
                    select(MemberTraining)
                    .where(
                        MemberTraining.tenant_id == self.tenant_id,
                        MemberTraining.profile_id == str(profile.id),
                        MemberTraining.is_deleted.is_(False),
                    )
                    .order_by(MemberTraining.end_on.desc(), MemberTraining.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        items = []
        for record in records:
            data = row_data(record)
            data["meets_requirement"] = (record.days or 0) >= MIN_TRAINING_DAYS or (
                record.hours or 0
            ) >= MIN_TRAINING_HOURS
            data.update(annotate_level(record.data_level or "internal"))
            items.append(data)
        satisfied = any(item["meets_requirement"] for item in items)
        qualified = [item for item in items if item["meets_requirement"]]
        best = max(
            qualified or items,
            key=lambda item: (item.get("days") or 0, item.get("hours") or 0),
            default=None,
        )
        notice = (
            "已登记集中培训达到 3 天 / 24 学时要求"
            if satisfied
            else ("集中培训未达 3 天或 24 学时，请补充培训记录" if items else "尚未登记集中培训")
        )
        return {
            "items": items,
            "best": best,
            "satisfied": satisfied,
            "notice": notice,
            "requirement": "集中培训不少于 3 天或 24 学时；是否计入发展程序仍须人工核验原件",
            **annotate_level("internal"),
        }

    # ==================== 发展程序事实 ====================

    async def _procedure_rows(self, profile_id: str) -> list[MemberProcedure]:
        rows = (
            (
                await self.db.execute(
                    select(MemberProcedure)
                    .where(
                        MemberProcedure.tenant_id == self.tenant_id,
                        MemberProcedure.profile_id == profile_id,
                        MemberProcedure.is_deleted.is_(False),
                    )
                    .order_by(
                        MemberProcedure.occurred_on.desc(),
                        MemberProcedure.created_at.desc(),
                        MemberProcedure.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _current_procedure(self, profile_id: str, kind: str) -> MemberProcedure | None:
        return (
            await self.db.execute(
                select(MemberProcedure)
                .where(
                    MemberProcedure.tenant_id == self.tenant_id,
                    MemberProcedure.profile_id == profile_id,
                    MemberProcedure.kind == kind,
                    MemberProcedure.is_deleted.is_(False),
                )
                .order_by(
                    MemberProcedure.occurred_on.desc(),
                    MemberProcedure.created_at.desc(),
                    MemberProcedure.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _procedure_group(
        items: list[dict[str, Any]],
        current: dict[str, Any] | None,
        satisfied_notices: dict[str, str],
        missing_notice: str,
        other_notices: dict[str, str],
    ) -> dict[str, Any]:
        status = current.get("status") if current else None
        if not current:
            notice = missing_notice
        elif status in satisfied_notices:
            notice = satisfied_notices[status]
        else:
            notice = other_notices.get(status or "", "程序状态待核对")
        return {
            "items": items,
            "current": current,
            "satisfied": bool(current and status in satisfied_notices),
            "notice": notice,
        }

    async def procedures(self, profile_id: str) -> dict[str, Any]:
        """按程序类型汇总当前状态与历史记录；只读，不改变阶段。"""
        profile = await self.profile(profile_id)
        records = await self._procedure_rows(str(profile.id))
        items: list[dict[str, Any]] = []
        for record in records:
            data = row_data(record)
            level = record.data_level or "internal"
            data.update(annotate_level(level))
            masked, redacted = redact_third_party(data, level=level, viewer=viewer_level(self.user))
            masked["redacted_fields"] = redacted
            items.append(masked)

        def group(kind: str) -> list[dict[str, Any]]:
            return [item for item in items if item["kind"] == kind]

        def latest(kind: str) -> dict[str, Any] | None:
            rows = group(kind)
            return rows[0] if rows else None

        contacts = group("contact")
        introducers = group("introducer")
        introducer_current: list[dict[str, Any]] = []
        introducer_keys: set[str] = set()
        for row in introducers:
            key = self._introducer_key(row)
            if key in introducer_keys:
                continue
            introducer_keys.add(key)
            introducer_current.append(row)
            if len(introducer_current) >= 2:
                break
        branch_items = group("branch_committee_review")
        pre_review_items = group("upper_pre_review")
        form_items = group("application_form")
        publicity_items = group("publicity")
        talk_items = group("upper_talk")
        vote_items = group("branch_vote")
        outcome_items = group("probation_outcome")
        higher_record_items = group("higher_record")
        party_group_items = group("party_group")
        secondary_items = group("secondary_review")
        secondary_by_node: dict[str, dict[str, Any]] = {}
        for item in secondary_items:
            node = (item.get("details") or {}).get("node")
            if node and node not in secondary_by_node:
                secondary_by_node[node] = item

        return {
            "contacts": {
                "items": contacts,
                "current": contacts[0] if contacts else None,
                "satisfied": bool(contacts),
                "notice": "已登记培养联系人" if contacts else "尚未登记培养联系人",
            },
            "introducers": {
                "items": introducers,
                "current": introducer_current,
                "count": len(introducer_current),
                "satisfied": len(introducer_current) >= 2,
                "notice": (
                    "尚未登记入党介绍人"
                    if not introducer_current
                    else (
                        "已登记1名入党介绍人；接收预备党员前须登记2名"
                        if len(introducer_current) < 2
                        else "已登记2名入党介绍人"
                    )
                ),
            },
            "branch_committee_review": self._procedure_group(
                branch_items,
                branch_items[0] if branch_items else None,
                {"passed": "支委会审查已通过"},
                "尚未登记支委会审查",
                {"in_progress": "支委会审查进行中", "failed": "支委会审查未通过"},
            ),
            "upper_pre_review": self._procedure_group(
                pre_review_items,
                pre_review_items[0] if pre_review_items else None,
                {"passed": "上级党委预审已通过"},
                "尚未登记上级党委预审",
                {
                    "in_progress": "上级党委预审进行中",
                    "supplement": "上级党委预审要求补充材料",
                    "failed": "上级党委预审未通过",
                },
            ),
            "application_form": self._procedure_group(
                form_items,
                form_items[0] if form_items else None,
                {"submitted": "入党志愿书已提交", "reviewed": "入党志愿书已审核"},
                "尚未登记入党志愿书",
                {"draft": "入党志愿书正在填写"},
            ),
            "publicity": self._procedure_group(
                publicity_items,
                publicity_items[0] if publicity_items else None,
                {"completed": "公示已满5个工作日"},
                "尚未登记公示起止日期",
                {},
            ),
            "upper_talk": self._procedure_group(
                talk_items,
                talk_items[0] if talk_items else None,
                {"completed": "上级党委派人谈话已完成"},
                "尚未登记上级党委派人谈话",
                {},
            ),
            "branch_vote": self._procedure_group(
                vote_items,
                vote_items[0] if vote_items else None,
                {"passed": "支部大会票决通过"},
                "尚未登记支部大会票决",
                {"not_passed": "支部大会票决未通过"},
            ),
            "probation_outcome": self._procedure_group(
                outcome_items,
                outcome_items[0] if outcome_items else None,
                {
                    "qualified": "预备党员已按期转正",
                    "extended": "已登记延长预备期",
                    "disqualified": "已登记取消预备党员资格",
                },
                "尚未登记预备党员转正结果",
                {},
            ),
            "higher_record": self._procedure_group(
                higher_record_items,
                higher_record_items[0] if higher_record_items else None,
                {"recorded": "再上一级党委组织部门备案已登记"},
                "尚未登记再上一级党委组织部门备案",
                {},
            ),
            "party_group": self._procedure_group(
                party_group_items,
                party_group_items[0] if party_group_items else None,
                {"assigned": "已编入党支部和党小组"},
                "尚未登记编入党支部和党小组",
                {},
            ),
            "secondary_review": {
                "items": secondary_items,
                "current": secondary_items[0] if secondary_items else None,
                "by_node": secondary_by_node,
                "satisfied": bool(secondary_items),
                "notice": (
                    f"已登记 {len(secondary_by_node)} 个二级审议节点"
                    if secondary_items
                    else "尚未登记二级党组织审议与组织员签字"
                ),
            },
            "requirement": PROCEDURE_REQUIREMENT,
            **annotate_level("internal"),
        }

    @staticmethod
    def _procedure_text(
        details: dict[str, Any],
        key: str,
        label: str,
        *,
        required: bool = False,
        max_length: int = 200,
    ) -> str:
        value = details.get(key)
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise HTTPException(422, f"{label}格式无效")
        value = value.strip()
        if required and not value:
            raise HTTPException(422, f"请填写{label}")
        if len(value) > max_length:
            raise HTTPException(422, f"{label}过长")
        return value

    @staticmethod
    def _procedure_date(
        details: dict[str, Any],
        key: str,
        label: str,
        *,
        required: bool = False,
        allow_future: bool = False,
    ) -> date | None:
        raw = details.get(key)
        if raw in (None, ""):
            if required:
                raise HTTPException(422, f"请填写{label}")
            return None
        try:
            value = date.fromisoformat(str(raw))
        except ValueError:
            raise HTTPException(422, f"{label}格式无效") from None
        if not allow_future and value > date.today():
            raise HTTPException(422, f"{label}不能晚于今天")
        return value

    @staticmethod
    def _working_days(start_on: date, end_on: date) -> int:
        """按周一至周五计算公示工作日；法定节假日由组织人员按通知核对。"""
        if end_on < start_on:
            return 0
        count = 0
        cursor = start_on
        while cursor <= end_on:
            if cursor.weekday() < 5:
                count += 1
            cursor += timedelta(days=1)
        return count

    @staticmethod
    def _procedure_int(
        details: dict[str, Any],
        key: str,
        label: str,
        *,
        required: bool = True,
        maximum: int = 10000,
    ) -> int | None:
        raw = details.get(key)
        if raw in (None, ""):
            if required:
                raise HTTPException(422, f"请填写{label}")
            return None
        if isinstance(raw, bool):
            raise HTTPException(422, f"{label}格式无效")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{label}格式无效") from None
        if value < 0 or value > maximum:
            raise HTTPException(422, f"{label}须为 0 至 {maximum} 的整数")
        return value

    @staticmethod
    def _introducer_key(row: MemberProcedure | dict[str, Any]) -> str:
        details = (
            row.details or {} if isinstance(row, MemberProcedure) else (row.get("details") or {})
        )
        linked = str(details.get("linked_profile_id") or "").strip()
        if linked:
            return f"profile:{linked}"
        return "external:{name}|{org}".format(
            name=str(details.get("external_name") or "").strip(),
            org=str(details.get("external_org") or "").strip(),
        )

    @staticmethod
    def _school_gate_enabled(profile: MemberProfile, key: str) -> bool:
        threshold = _load_school_rules().get(key, 0)
        return bool(threshold and profile.year and profile.year >= threshold)

    @staticmethod
    def _secondary_nodes(procedures: list[MemberProcedure]) -> set[str]:
        nodes: set[str] = set()
        for row in procedures:
            if row.kind != "secondary_review":
                continue
            node = str((row.details or {}).get("node") or "").strip()
            if node:
                nodes.add(node)
        return nodes

    @staticmethod
    def _publicity_ready(procedures: list[MemberProcedure]) -> bool:
        for row in procedures:
            if row.kind != "publicity" or row.status != "completed":
                continue
            try:
                days = int((row.details or {}).get("working_days") or 0)
            except (TypeError, ValueError):
                days = 0
            if days >= 5:
                return True
        return False

    @staticmethod
    def _procedure_effective_until(row: MemberProcedure | None) -> date | None:
        if row is None or row.status != "extended":
            return None
        raw = (row.details or {}).get("effective_until")
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            return None

    async def _current_branch_vote(
        self, profile_id: str, meeting_for: str | None = None
    ) -> MemberProcedure | None:
        """取最新一条支部大会票决；可按票决事项过滤，避免把接收票决当成转正票决。"""
        for row in await self._procedure_rows(profile_id):
            if row.kind != "branch_vote":
                continue
            if meeting_for and (row.details or {}).get("meeting_for") != meeting_for:
                continue
            return row
        return None

    async def _close_reminders(self, profile_id: str, kind: str, note: str) -> None:
        rows = (
            (
                await self.db.execute(
                    select(MemberReminder).where(
                        MemberReminder.tenant_id == self.tenant_id,
                        MemberReminder.profile_id == profile_id,
                        MemberReminder.kind == kind,
                        MemberReminder.status == "open",
                        MemberReminder.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        for reminder in rows:
            reminder.status = "closed"
            reminder.processed_by = str(self.user.id)
            reminder.processed_at = utc_now()
            reminder.note = note

    async def add_procedure(self, profile_id: str, body: ProcedureCreate) -> MemberProcedure:
        """登记一条发展程序事实；类型、角色、阶段和字段按程序分别校验。"""
        kind = body.kind
        group = PROCEDURE_GROUP.get(kind)
        if group is None:
            raise HTTPException(422, "发展程序类型无效")
        if self.user.role not in PROCEDURE_ROLE_GROUPS[group]:
            raise HTTPException(
                403,
                f"当前角色不能登记{PROCEDURE_TITLES[kind]}；"
                f"该程序由{PROCEDURE_ROLE_LABELS[group]}登记",
            )

        profile = await self.profile(profile_id)
        stage = self._stage_or_422(profile.current_stage)
        rank = self.rules.development_rank(stage)
        min_rank = self.rules.development_rank(PROCEDURE_MIN_STAGE[kind])
        if rank is None or min_rank is None or rank < min_rank:
            raise HTTPException(
                422,
                f"{PROCEDURE_TITLES[kind]}应在{stage_label(PROCEDURE_MIN_STAGE[kind].value)}"
                "阶段及以后登记；请先核对发展阶段",
            )

        details = dict(body.details or {})
        status = body.status.strip()
        title = body.title.strip() or PROCEDURE_TITLES[kind]
        summary = body.summary.strip()
        note = body.note.strip()
        reason = body.reason.strip()
        occurred_on = body.occurred_on

        if kind in {"contact", "introducer"}:
            linked_id = self._procedure_text(
                details, "linked_profile_id", "关联正式党员", max_length=36
            )
            if linked_id:
                linked = await self.db.scalar(
                    select(MemberProfile).where(
                        MemberProfile.id == linked_id,
                        MemberProfile.tenant_id == self.tenant_id,
                        MemberProfile.is_deleted.is_(False),
                    )
                )
                if linked is None:
                    raise HTTPException(422, "关联人员不存在或无权访问")
                if str(linked.id) == str(profile.id):
                    raise HTTPException(422, "不能将本人登记为培养联系人/入党介绍人")
                if linked.current_stage != MemberStage.MEMBER.value:
                    raise HTTPException(
                        422,
                        "关联人员须为正式党员；如为外部正式党员，请填写外部信息和核验依据",
                    )
                details = {
                    "linked_profile_id": str(linked.id),
                    "linked_name": linked.name,
                    "linked_org": linked.org_name,
                    "external": False,
                    "external_name": "",
                    "external_org": "",
                    "external_title": "",
                    "verified_on": "",
                }
            else:
                external_name = self._procedure_text(
                    details, "external_name", "外部正式党员姓名", required=True, max_length=50
                )
                external_org = self._procedure_text(
                    details,
                    "external_org",
                    "外部正式党员所在组织",
                    required=True,
                    max_length=200,
                )
                external_title = self._procedure_text(
                    details, "external_title", "外部正式党员职务", max_length=100
                )
                verified_on = self._procedure_date(
                    details, "verified_on", "核验日期", required=True
                )
                if not note:
                    raise HTTPException(422, "外部正式党员须在备注中填写核验依据")
                details = {
                    "linked_profile_id": "",
                    "linked_name": "",
                    "linked_org": "",
                    "external": True,
                    "external_name": external_name,
                    "external_org": external_org,
                    "external_title": external_title,
                    "verified_on": verified_on.isoformat() if verified_on else "",
                }
            if kind == "introducer":
                existing_introducers = [
                    row
                    for row in await self._procedure_rows(str(profile.id))
                    if row.kind == "introducer"
                ]
                duplicate = any(
                    (linked_id and (row.details or {}).get("linked_profile_id") == linked_id)
                    or (
                        not linked_id
                        and (row.details or {}).get("external_name") == external_name
                        and (row.details or {}).get("external_org") == external_org
                    )
                    for row in existing_introducers
                )
                if duplicate:
                    raise HTTPException(422, "不能重复登记同一名入党介绍人")
            status = "assigned" if kind == "contact" else "confirmed"
        elif kind == "publicity":
            if status and status != "completed":
                raise HTTPException(422, "公示状态无效")
            start_on = self._procedure_date(details, "start_on", "公示开始日期", required=True)
            end_on = occurred_on
            assert start_on is not None
            if end_on < start_on:
                raise HTTPException(422, "公示结束日期不能早于开始日期")
            working_days = self._working_days(start_on, end_on)
            if working_days < 5:
                raise HTTPException(
                    422,
                    f"公示须满5个工作日，当前为{working_days}个工作日；请核对公示起止日期",
                )
            details = {
                "start_on": start_on.isoformat(),
                "end_on": end_on.isoformat(),
                "working_days": working_days,
            }
            status = "completed"
            if not summary:
                summary = (
                    f"公示期{start_on.isoformat()}至{end_on.isoformat()}，共{working_days}个工作日"
                )
        elif kind == "branch_committee_review":
            if status not in PROCEDURE_STATUSES[kind]:
                raise HTTPException(422, "支委会审查结论无效")
            if status in {"passed", "failed"} and not summary:
                raise HTTPException(422, "支委会审查形成结论时须填写审查意见")
            details = {
                "attendees": self._procedure_text(details, "attendees", "参加人员", max_length=500)
            }
        elif kind == "upper_pre_review":
            if status not in PROCEDURE_STATUSES[kind]:
                raise HTTPException(422, "上级党委预审结论无效")
            upper_org = self._procedure_text(
                details, "upper_org", "上级党组织", required=True, max_length=200
            )
            reply_no = self._procedure_text(details, "reply_no", "批复文号", max_length=64)
            submitted_on = self._procedure_date(details, "submitted_on", "报送日期")
            if submitted_on and submitted_on > occurred_on:
                raise HTTPException(422, "报送日期不能晚于预审日期")
            if status in {"passed", "supplement", "failed"} and not summary:
                raise HTTPException(422, "上级党委预审形成结论时须填写预审意见")
            details = {
                "upper_org": upper_org,
                "reply_no": reply_no,
                "submitted_on": submitted_on.isoformat() if submitted_on else "",
            }
        elif kind == "application_form":
            if status not in PROCEDURE_STATUSES[kind]:
                raise HTTPException(422, "入党志愿书状态无效")
            form_no = self._procedure_text(details, "form_no", "志愿书编号", max_length=64)
            reviewed_on = self._procedure_date(details, "reviewed_on", "审核日期")
            if reviewed_on and reviewed_on < occurred_on:
                raise HTTPException(422, "审核日期不能早于填写日期")
            if status == "reviewed" and (not form_no or not reviewed_on):
                raise HTTPException(422, "志愿书审核通过时须填写编号和审核日期")
            raw_checklist = details.get("checklist") or []
            if not isinstance(raw_checklist, list):
                raise HTTPException(422, "志愿书核对清单格式无效")
            checklist_codes = {code for code, _ in APPLICATION_FORM_CHECKLIST}
            selected = {str(code) for code in raw_checklist}
            if selected - checklist_codes:
                raise HTTPException(422, "志愿书核对清单包含无效项")
            checklist = [code for code, _ in APPLICATION_FORM_CHECKLIST if code in selected]
            details = {
                "form_no": form_no,
                "reviewed_on": reviewed_on.isoformat() if reviewed_on else "",
                "checklist": checklist,
            }
        elif kind == "upper_talk":
            if status and status != "completed":
                raise HTTPException(422, "上级谈话状态无效")
            talker = self._procedure_text(
                details, "talker", "谈话人", required=True, max_length=100
            )
            talker_org = self._procedure_text(
                details, "talker_org", "谈话人所在组织", max_length=200
            )
            if not summary:
                raise HTTPException(422, "请填写上级党委派人谈话情况")
            details = {"talker": talker, "talker_org": talker_org}
            status = "completed"
        elif kind == "branch_vote":
            if status not in PROCEDURE_STATUSES[kind]:
                raise HTTPException(422, "支部大会票决结果无效")
            meeting_for = self._procedure_text(
                details, "meeting_for", "票决事项", required=True, max_length=30
            )
            if meeting_for not in BRANCH_VOTE_MEETING_FOR:
                raise HTTPException(422, "票决事项无效")
            if stage == MemberStage.CANDIDATE and meeting_for != "reception":
                raise HTTPException(
                    422,
                    "发展对象阶段只能登记接收预备党员票决；转正或取消资格票决须在预备党员阶段登记",
                )
            eligible = self._procedure_int(details, "eligible_count", "应到人数")
            attended = self._procedure_int(details, "attended_count", "实到人数")
            agree = self._procedure_int(details, "agree_count", "同意票数")
            disagree = self._procedure_int(details, "disagree_count", "不同意票数")
            abstain = self._procedure_int(details, "abstain_count", "弃权票数")
            assert eligible is not None and attended is not None
            assert agree is not None and disagree is not None and abstain is not None
            if attended > eligible:
                raise HTTPException(422, "实到人数不能大于应到人数")
            if agree + disagree + abstain > attended:
                raise HTTPException(422, "同意、不同意和弃权票数之和不能大于实到人数")
            if not summary:
                raise HTTPException(422, "请填写票决结果和决议内容")
            details = {
                "meeting_for": meeting_for,
                "eligible_count": eligible,
                "attended_count": attended,
                "agree_count": agree,
                "disagree_count": disagree,
                "abstain_count": abstain,
            }
        elif kind == "probation_outcome":
            if status not in PROCEDURE_STATUSES[kind]:
                raise HTTPException(422, "预备党员转正结果无效")
            if not summary:
                raise HTTPException(422, "请填写组织形成的转正结论")
            category_code = ""
            category_label = ""
            if status in PROBATION_OUTCOME_REASONS:
                allowed = PROBATION_OUTCOME_REASONS[status]
                category_code = self._procedure_text(
                    details, "reason_category", "情形分类", required=True, max_length=40
                )
                if category_code not in allowed:
                    raise HTTPException(422, "情形分类与转正结果不一致或无效")
                category_label = allowed[category_code]
            previous = await self._current_procedure(str(profile.id), kind)
            previous_until = self._procedure_effective_until(previous)
            effective_until: date | None = None
            if status == "extended":
                if previous is not None and previous.status == "extended":
                    raise HTTPException(422, "延长预备期只能办理一次")
                effective_until = self._procedure_date(
                    details,
                    "effective_until",
                    "延长预备期至",
                    required=True,
                    allow_future=True,
                )
                if effective_until is None or effective_until <= occurred_on:
                    raise HTTPException(422, "延长预备期截止日期须晚于本次决定日期")
                base_until = profile.stage_joined_on + timedelta(days=365)
                min_until = add_months(base_until, 6)
                max_until = add_months(base_until, 12)
                if effective_until < min_until or effective_until > max_until:
                    raise HTTPException(
                        422,
                        f"延长预备期须为6个月至1年：最早可至 {min_until.isoformat()}，"
                        f"最晚不超过 {max_until.isoformat()}",
                    )
                if effective_until <= base_until:
                    raise HTTPException(
                        422,
                        "延长预备期截止日期须晚于当前预备期届满日期",
                    )
            elif status == "qualified" and previous_until and occurred_on < previous_until:
                raise HTTPException(
                    422,
                    f"延长预备期未满，最早可于 {previous_until.isoformat()} 后登记按期转正",
                )
            details = {"effective_until": effective_until.isoformat()} if effective_until else {}
            if category_code:
                details["reason_category"] = category_code
                details["reason_label"] = category_label
        elif kind == "higher_record":
            if status and status != "recorded":
                raise HTTPException(422, "再上一级备案状态无效")
            upper_org = self._procedure_text(
                details, "upper_org", "上级党组织", required=True, max_length=200
            )
            reply_no = self._procedure_text(details, "reply_no", "批复文号", max_length=64)
            details = {"upper_org": upper_org, "reply_no": reply_no}
            status = "recorded"
        elif kind == "party_group":
            if status and status != "assigned":
                raise HTTPException(422, "编入党支部和党小组状态无效")
            party_branch = self._procedure_text(details, "party_branch", "党支部", max_length=200)
            party_group = self._procedure_text(
                details, "party_group", "党小组", required=True, max_length=200
            )
            details = {
                "party_branch": party_branch,
                "party_group": party_group,
                "assigned_on": occurred_on.isoformat(),
            }
            status = "assigned"
        elif kind == "secondary_review":
            if status and status != "completed":
                raise HTTPException(422, "二级党组织审议状态无效")
            node = self._procedure_text(details, "node", "审议节点", required=True, max_length=40)
            spec = SECONDARY_REVIEW_NODES.get(node)
            if spec is None:
                raise HTTPException(422, "审议节点无效")
            node_min_stage = spec["min_stage"]
            assert isinstance(node_min_stage, MemberStage)
            node_min_rank = self.rules.development_rank(node_min_stage)
            if rank is None or node_min_rank is None or rank < node_min_rank:
                raise HTTPException(
                    422,
                    f"{spec['label']}应在{stage_label(node_min_stage.value)}阶段及以后登记",
                )
            organizer_name = self._procedure_text(
                details, "organizer_name", "专职组织员姓名", required=True, max_length=50
            )
            meeting_on = occurred_on
            signed_on = self._procedure_date(details, "signed_on", "组织员签字日期", required=True)
            assert signed_on is not None
            if signed_on < meeting_on:
                raise HTTPException(422, "组织员签字日期不能早于二级党组织会议日期")
            if not summary:
                raise HTTPException(422, "请填写二级党组织审议意见")
            details = {
                "node": node,
                "node_label": spec["label"],
                "meeting_on": meeting_on.isoformat(),
                "organizer_name": organizer_name,
                "signed_on": signed_on.isoformat(),
            }
            status = "completed"
        else:
            raise HTTPException(422, "发展程序类型无效")

        latest = await self.db.scalar(
            select(func.max(MemberProcedure.revision)).where(
                MemberProcedure.tenant_id == self.tenant_id,
                MemberProcedure.profile_id == str(profile.id),
                MemberProcedure.kind == kind,
            )
        )
        record = MemberProcedure(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            kind=kind,
            occurred_on=occurred_on,
            status=status,
            title=title,
            summary=summary,
            note=note,
            reason=reason,
            details=details,
            data_level=(
                "sensitive"
                if kind
                in {
                    "branch_committee_review",
                    "upper_pre_review",
                    "upper_talk",
                    "branch_vote",
                    "probation_outcome",
                }
                else "internal"
            ),
            revision=int(latest or 0) + 1,
            created_by=str(self.user.id),
        )
        self.db.add(record)
        await self.db.flush()
        if kind == "higher_record":
            await self._close_reminders(
                str(profile.id), "higher_record", "已登记再上一级党委组织部门备案"
            )
        elif kind == "party_group":
            await self._close_reminders(str(profile.id), "party_group", "已登记编入党支部和党小组")
        elif kind == "probation_outcome":
            # 转正结果变化后，原预备期到期和材料提醒不再适用；延长预备期的
            # 新到期提醒由下一次流程看板/扫描按 effective_until 重新生成。
            for reminder_kind in (
                "probationary_expiration",
                "probationary_expiration_advance",
                "material_submission",
                "material_submission_advance",
            ):
                await self._close_reminders(
                    str(profile.id),
                    reminder_kind,
                    "已按最新预备党员转正结果重新核算",
                )
        return record

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

    def _due_reminders(
        self,
        profile: MemberProfile,
        procedures: list[MemberProcedure] | None = None,
    ) -> list[tuple[str, date]]:
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
            # 延长预备期后，到期提醒跟随最新一条转正结果，避免仍按原一年期催办。
            if profile.current_stage == "probationary" and procedures:
                outcome = next(
                    (row for row in procedures if row.kind == "probation_outcome"),
                    None,
                )
                if outcome is not None and outcome.status == "extended":
                    until = self._procedure_effective_until(outcome)
                    if until:
                        expire = until
            result.append((kind, expire))
            if advance > 0:
                result.append((kind + "_advance", expire - timedelta(days=advance)))
        return result

    def _task_reminders(
        self,
        profile: MemberProfile,
        procedures: list[MemberProcedure],
    ) -> list[tuple[str, date]]:
        """18/19/20 的轻量提醒：只提示待办，不替代备案、编组或宣誓程序。"""
        if profile.current_stage != "probationary":
            return []
        latest: dict[str, MemberProcedure] = {}
        for row in procedures:
            latest.setdefault(row.kind, row)
        due_on = profile.stage_joined_on
        result: list[tuple[str, date]] = []
        if "higher_record" not in latest:
            result.append(("higher_record", due_on))
        if "party_group" not in latest:
            result.append(("party_group", due_on))
        # 细则要求在批准为预备党员后三个月内宣誓；宣誓没有结构化登记，使用提醒办结
        # 作为人工确认，重复扫描不会重开已办结提醒。
        result.append(("oath", profile.stage_joined_on + timedelta(days=90)))
        return result

    async def sync_reminders(
        self,
        profile: MemberProfile,
        procedures: list[MemberProcedure] | None = None,
    ) -> list[MemberReminder]:
        if procedures is None:
            procedures = await self._procedure_rows(str(profile.id))
        created: list[MemberReminder] = []
        planned = [
            *self._due_reminders(profile, procedures),
            *self._task_reminders(profile, procedures),
        ]
        existing_rows = (
            (
                await self.db.execute(
                    select(MemberReminder).where(
                        MemberReminder.tenant_id == self.tenant_id,
                        MemberReminder.profile_id == str(profile.id),
                        MemberReminder.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_keys = {(row.kind, row.due_on) for row in existing_rows}
        open_oaths = [row for row in existing_rows if row.kind == "oath" and row.status == "open"]
        primary_oath = open_oaths[0] if open_oaths else None
        for duplicate in open_oaths[1:]:
            duplicate.status = "closed"
            duplicate.note = "已按最新宣誓期限合并，保留一条待办"
        for kind, due_on in planned:
            if (kind, due_on) in existing_keys:
                continue
            if kind == "oath" and primary_oath is not None:
                primary_oath.due_on = due_on
                primary_oath = None
                existing_keys.add((kind, due_on))
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
            existing_keys.add((kind, due_on))
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

    async def flow_board(self) -> dict[str, Any]:
        """流程看板：按组织范围汇总阶段、缺项和 18/19/20 提醒；只读汇总，不改阶段。"""
        conditions = [
            *self._scope(MemberProfile),
            MemberProfile.is_active.is_(True),
            MemberProfile.relation_status != "transferred_out",
        ]
        total = (await self.db.scalar(select(func.count(MemberProfile.id)).where(*conditions))) or 0
        profiles = (
            (
                await self.db.execute(
                    select(MemberProfile)
                    .where(*conditions)
                    .order_by(
                        MemberProfile.stage_joined_on,
                        MemberProfile.created_at,
                        MemberProfile.id,
                    )
                    .limit(FLOW_BOARD_MAX_ROWS)
                )
            )
            .scalars()
            .all()
        )
        if not profiles:
            return {
                "items": [],
                "stage_summary": self._flow_stage_summary({}),
                "total": total,
                "shown": 0,
                "truncated": False,
                "notice": "当前组织范围内暂无党员发展档案。",
            }

        profile_ids = [str(profile.id) for profile in profiles]
        procedure_rows = (
            (
                await self.db.execute(
                    select(MemberProcedure)
                    .where(
                        MemberProcedure.tenant_id == self.tenant_id,
                        MemberProcedure.profile_id.in_(profile_ids),
                        MemberProcedure.is_deleted.is_(False),
                    )
                    .order_by(
                        MemberProcedure.occurred_on.desc(),
                        MemberProcedure.created_at.desc(),
                        MemberProcedure.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        procedures_by_profile: dict[str, list[MemberProcedure]] = defaultdict(list)
        for row in procedure_rows:
            procedures_by_profile[row.profile_id].append(row)

        material_rows = (
            await self.db.execute(
                select(MemberMaterial.profile_id, MemberMaterial.material_type).where(
                    MemberMaterial.tenant_id == self.tenant_id,
                    MemberMaterial.profile_id.in_(profile_ids),
                    MemberMaterial.review_status == "approved",
                    MemberMaterial.is_deleted.is_(False),
                    MemberMaterial.user_id.is_(None),
                    MemberMaterial.submission_key.is_(None),
                )
            )
        ).all()
        approved_by_profile: dict[str, set[str]] = defaultdict(set)
        for row in material_rows:
            approved_by_profile[row.profile_id].add(row.material_type)

        review_rows = (
            (
                await self.db.execute(
                    select(MemberPoliticalReview)
                    .where(
                        MemberPoliticalReview.tenant_id == self.tenant_id,
                        MemberPoliticalReview.profile_id.in_(profile_ids),
                        MemberPoliticalReview.is_deleted.is_(False),
                    )
                    .order_by(
                        MemberPoliticalReview.profile_id,
                        MemberPoliticalReview.reviewed_on.desc(),
                        MemberPoliticalReview.created_at.desc(),
                        MemberPoliticalReview.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest_review: dict[str, MemberPoliticalReview] = {}
        for row in review_rows:
            latest_review.setdefault(row.profile_id, row)

        training_rows = (
            (
                await self.db.execute(
                    select(MemberTraining).where(
                        MemberTraining.tenant_id == self.tenant_id,
                        MemberTraining.profile_id.in_(profile_ids),
                        MemberTraining.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        training_ready: dict[str, bool] = defaultdict(bool)
        for row in training_rows:
            if (row.days or 0) >= MIN_TRAINING_DAYS or (row.hours or 0) >= MIN_TRAINING_HOURS:
                training_ready[row.profile_id] = True

        for profile in profiles:
            await self.sync_reminders(profile, procedures_by_profile.get(str(profile.id), []))
        await self.db.flush()

        reminder_rows = (
            (
                await self.db.execute(
                    select(MemberReminder)
                    .where(
                        MemberReminder.tenant_id == self.tenant_id,
                        MemberReminder.profile_id.in_(profile_ids),
                        MemberReminder.status == "open",
                        MemberReminder.is_deleted.is_(False),
                    )
                    .order_by(MemberReminder.due_on, MemberReminder.id)
                )
            )
            .scalars()
            .all()
        )
        reminders_by_profile: dict[str, list[MemberReminder]] = defaultdict(list)
        for row in reminder_rows:
            reminders_by_profile[row.profile_id].append(row)

        items = [
            self._flow_item(
                profile,
                procedures_by_profile.get(str(profile.id), []),
                approved_by_profile.get(str(profile.id), set()),
                latest_review.get(str(profile.id)),
                training_ready.get(str(profile.id), False),
                reminders_by_profile.get(str(profile.id), []),
            )
            for profile in profiles
        ]
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            counts[item["current_stage"]] += 1
        notice = (
            f"当前组织范围内共 {total} 份档案；看板最多展示 {FLOW_BOARD_MAX_ROWS} 份，"
            "请缩小组织范围后查看其余档案。"
            if total > len(items)
            else "看板汇总材料、程序事实和提醒，不自动推进阶段，也不替代组织决定。"
        )
        return {
            "items": items,
            "stage_summary": self._flow_stage_summary(counts),
            "total": total,
            "shown": len(items),
            "truncated": total > len(items),
            "notice": notice,
        }

    @staticmethod
    def _flow_stage_summary(counts: dict[str, int]) -> list[dict[str, Any]]:
        stages = [
            MemberStage.APPLICANT,
            MemberStage.ACTIVIST,
            MemberStage.CANDIDATE,
            MemberStage.PROBATIONARY,
            MemberStage.MEMBER,
            MemberStage.DISQUALIFIED,
            MemberStage.REJECTED,
        ]
        return [
            {
                "stage": stage.value,
                "label": STAGE_LABELS[stage],
                "count": counts.get(stage.value, 0),
            }
            for stage in stages
        ]

    def _flow_item(
        self,
        profile: MemberProfile,
        procedures: list[MemberProcedure],
        approved_materials: set[str],
        review: MemberPoliticalReview | None,
        training_ready: bool,
        reminders: list[MemberReminder],
    ) -> dict[str, Any]:
        latest: dict[str, MemberProcedure] = {}
        for row in procedures:
            latest.setdefault(row.kind, row)
        stage = profile.current_stage
        try:
            stage_label_value = STAGE_LABELS[MemberStage(stage)]
        except ValueError:
            stage_label_value = stage
        next_target = {
            "applicant": MemberStage.ACTIVIST,
            "activist": MemberStage.CANDIDATE,
            "candidate": MemberStage.PROBATIONARY,
            "probationary": MemberStage.MEMBER,
        }.get(stage)
        missing: list[str] = []

        def add_missing(value: str) -> None:
            if value not in missing:
                missing.append(value)

        if next_target:
            try:
                rule = self.rules.get_rule(MemberStage(stage), next_target)
            except ValueError:
                rule = None
            if rule:
                for name in rule.required_materials:
                    if name not in approved_materials:
                        add_missing(name)

        hard_secondary = self._school_gate_enabled(profile, "secondary_review_hard_gate_from_year")
        hard_publicity = self._school_gate_enabled(profile, "publicity_hard_gate_from_year")
        secondary_nodes = self._secondary_nodes(procedures)
        if stage == "activist":
            if "contact" not in latest:
                add_missing("培养联系人")
            if hard_secondary and "candidate_determination" not in secondary_nodes:
                add_missing("二级审议：确定发展对象")
        if stage == "candidate":
            if "contact" not in latest:
                add_missing("培养联系人")
            if (
                len({self._introducer_key(row) for row in procedures if row.kind == "introducer"})
                < 2
            ):
                add_missing("入党介绍人2名")
            branch_review = latest.get("branch_committee_review")
            if branch_review is None or branch_review.status != "passed":
                add_missing("支委会审查通过")
            pre_review = latest.get("upper_pre_review")
            if pre_review is None or pre_review.status != "passed":
                add_missing("上级党委预审通过")
            application_form = latest.get("application_form")
            if application_form is None or application_form.status not in {
                "submitted",
                "reviewed",
            }:
                add_missing("入党志愿书已提交或已审核")
            if review is None or review.status != "passed":
                add_missing("政治审查合格结论")
            if not training_ready:
                add_missing("集中培训不少于3天或24学时")
            if hard_secondary:
                for code, label in (
                    ("candidate_determination", "二级审议：确定发展对象"),
                    ("pre_reception", "二级审议：接收前支委会审查"),
                    ("reception", "二级审议：接收支部大会"),
                ):
                    if code not in secondary_nodes:
                        add_missing(label)
            if hard_publicity and not self._publicity_ready(procedures):
                add_missing("公示5个工作日")
        if stage == "probationary":
            conversion_vote = next(
                (
                    row
                    for row in procedures
                    if row.kind == "branch_vote"
                    and (row.details or {}).get("meeting_for") == "conversion"
                ),
                None,
            )
            outcome = latest.get("probation_outcome")
            if outcome is not None and outcome.status == "disqualified":
                discussion_vote = next(
                    (
                        row
                        for row in procedures
                        if row.kind == "branch_vote"
                        and (row.details or {}).get("meeting_for")
                        in {"conversion", "disqualification"}
                    ),
                    None,
                )
                if discussion_vote is None:
                    add_missing("支部大会讨论票决")
            elif conversion_vote is None or conversion_vote.status != "passed":
                add_missing("支部大会转正票决通过")
            if outcome is None:
                add_missing("预备党员转正结果")
            elif outcome.status == "extended":
                until = self._procedure_effective_until(outcome)
                add_missing(
                    f"延长预备期至 {until.isoformat()}，未满"
                    if until and until >= date.today()
                    else "延长预备期"
                )
            elif outcome.status == "disqualified":
                add_missing("取消预备党员资格待办理")
            if "party_group" not in latest:
                add_missing("编入党支部和党小组")
            if "higher_record" not in latest:
                add_missing("再上一级党委组织部门备案")
            if hard_secondary and "conversion" not in secondary_nodes:
                add_missing("二级审议：转正支部大会")
            if any(row.kind == "oath" for row in reminders):
                add_missing("入党宣誓")

        next_step = {
            "applicant": "递交申请并接受党组织谈话",
            "activist": "培养考察，研究确定发展对象",
            "candidate": "履行接收预备党员程序",
            "probationary": "预备期考察，办理转正",
            "member": "继续教育管理",
            "disqualified": "已终止发展",
            "rejected": "按组织意见重新考察",
        }.get(stage, "核对档案阶段")

        def snapshot(kind: str) -> dict[str, Any] | None:
            row = latest.get(kind)
            if row is None:
                return None
            # 看板只返回办理进度所需的状态与日期，不复制审查意见、票决决议或
            # 组织结论原文；完整内容仍从档案详情按数据等级和权限读取。
            data: dict[str, Any] = {
                "status": row.status,
                "occurred_on": row.occurred_on.isoformat(),
            }
            if kind == "branch_vote":
                data.update(
                    {
                        "meeting_for": (row.details or {}).get("meeting_for", ""),
                        "meeting_for_label": BRANCH_VOTE_LABELS.get(
                            (row.details or {}).get("meeting_for", ""), "支部大会"
                        ),
                    }
                )
            elif kind == "probation_outcome":
                data["effective_until"] = (row.details or {}).get("effective_until", "")
                data["status_label"] = PROBATION_OUTCOME_LABELS.get(row.status, row.status)
            elif kind == "higher_record":
                data["upper_org"] = (row.details or {}).get("upper_org", "")
                data["reply_no"] = (row.details or {}).get("reply_no", "")
            elif kind == "party_group":
                data["party_branch"] = (row.details or {}).get("party_branch", "")
                data["party_group"] = (row.details or {}).get("party_group", "")
                data["assigned_on"] = (row.details or {}).get("assigned_on", "")
            return data

        return {
            "id": str(profile.id),
            "name": profile.name,
            "org_name": profile.org_name,
            "org_unit_id": profile.org_unit_id,
            "current_stage": stage,
            "stage_label": stage_label_value,
            "stage_joined_on": profile.stage_joined_on.isoformat(),
            "days_in_stage": max(0, (date.today() - profile.stage_joined_on).days),
            "next_stage": next_target.value if next_target else "",
            "next_step": next_step,
            "missing": missing,
            "procedures": {
                kind: snapshot(kind)
                for kind in (
                    "contact",
                    "introducer",
                    "branch_committee_review",
                    "upper_pre_review",
                    "application_form",
                    "upper_talk",
                    "branch_vote",
                    "probation_outcome",
                    "higher_record",
                    "party_group",
                )
            },
            "political_review": (
                {"status": review.status, "reviewed_on": review.reviewed_on.isoformat()}
                if review
                else None
            ),
            "training_ready": training_ready,
            "reminders": [
                {
                    "id": str(row.id),
                    "kind": row.kind,
                    "due_on": row.due_on.isoformat(),
                    "status": row.status,
                }
                for row in reminders
            ],
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
