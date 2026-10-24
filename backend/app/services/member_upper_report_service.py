"""上级党组织审批 / 备案报送（模块2 延伸 / T-MEM-11）：人工报送、批复回填、留痕与导出。

依据《中国共产党发展党员工作细则》：确定入党积极分子（第八条）与列为发展对象（第十三条）
应当报上级党委**备案**；接收预备党员（第二十一条、第二十二条）与预备党员转正须报上级党委
**审批**，党委应当在三个月内审批（第二十五条，特殊情况可以延长但不得超过六个月）。

本模块最容易做成"反人类"的地方，正是它**不该 replace 上级党组织**：

1. **系统不能自己批自己**。系统里没有上级党组织的登录身份，也不存在跨组织审批通道；如果
   做出一个"审批通过"按钮让支部点一下，等于把上级党组织的决定变成软件里的一个状态位。
   因此这里只有两件事：**登记"支部已把材料报送出去"**（`submitted`）与**回填上级的批复结果**
   （`settled`）——回填的是别人的结论，不是系统的结论。
2. **回填必须有可对账的凭据**。没有文号的"同意 / 不同意"不是批复，所以 `agreed` / `rejected`
   必须给批复文号；"需补充材料"必须写清缺什么。否则"已回填"就是一句空话。
3. **回填不改阶段**。入党 / 转正是组织结论，阶段仍由授权人员在 `member_stage_history` 上按
   程序人工办理（与 T-SEC-13 的决策边界一致）；批复为「不同意」时只提示按上级结论人工调整，
   系统不自动回退阶段、也不自动把人移出名册。
4. **报送材料不与阶段材料要求两写**。随报材料 = 该阶段沿发展链累加的材料要求
   （`StageRules.materials_for_stage`，与阶段流转 / 组织关系转入同一来源）+ 配置里各事项另需的
   材料（入党志愿书、备案报告等，细则明文）。落库留**快照**，配置改了也不改写历史。
5. **备案时限不编数字**。细则只对审批作了"三个月内、特殊情况不超过六个月"的规定；备案时限
   细则未统一规定，因此只有审批类事项按时限提示，备案类如实显示"按上级党委规定"，不套用。
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import yaml
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.meeting import ContentRevision
from app.models.member import MemberProfile, MemberUpperReport
from app.models.user import User
from app.rules.member_stages import STAGE_LABELS, MemberStage, StageRules, load_stage_rules
from app.schemas.member_upper_report import UpperReportCreate, UpperReportRevoke, UpperReportSettle
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "business_rules.yaml"

KIND_LABELS: dict[str, str] = {"record": "备案", "approval": "审批"}
STATUS_LABELS: dict[str, str] = {
    "submitted": "已报送待批复",
    "settled": "已回填批复",
    "revoked": "已作废",
}
RESULT_LABELS: dict[str, str] = {
    "agreed": "同意 / 批准",
    "rejected": "不同意",
    "supplement": "需补充材料",
}

DEFAULT_APPROVAL_DAYS = 90
DEFAULT_REMIND_ADVANCE_DAYS = 15
MAX_LIST = 200

REPORT_NOTICE = (
    "上级审批 / 备案只登记两件事：支部已把材料报送出去、上级的批复结果是什么；"
    "系统不代替上级党组织审批，回填批复也不自动改动党员的阶段"
)
DECISION_BOUNDARY = "入党与转正由党组织依规决定，系统只做报送登记与批复回填，不作出任何组织结论"
NO_DEADLINE_NOTE = "备案时限按上级党委规定办理，细则未统一规定，系统不设到期天数"


@dataclass(frozen=True)
class UpperItem:
    """报送事项：由目标阶段决定类别、依据与随报材料，界面与接口不再各写一套。"""

    key: str
    kind: str
    stage: str
    label: str
    basis: str
    report_to: str


# 事项与阶段一一对应：支部大会 / 支委会作出决定后才报送，因此"阶段已到（或已过）目标阶段"
# 就是可报送的前提条件（用 StageRules.development_rank 判断，不另写一套顺序）。
UPPER_ITEMS: tuple[UpperItem, ...] = (
    UpperItem(
        key="activist_record",
        kind="record",
        stage=MemberStage.ACTIVIST.value,
        label="确定入党积极分子（报上级党委备案）",
        basis=(
            "《中国共产党发展党员工作细则》第八条：在入党申请人中确定入党积极分子，"
            "由党支部委员会会议研究决定后，报上级党委备案。"
        ),
        report_to="上级党委",
    ),
    UpperItem(
        key="candidate_record",
        kind="record",
        stage=MemberStage.CANDIDATE.value,
        label="列为发展对象（报上级党委备案）",
        basis=(
            "《中国共产党发展党员工作细则》第十三条：对经过一年以上培养教育和考察、"
            "基本具备党员条件的入党积极分子，支部委员会讨论同意并报上级党委备案后，"
            "可列为发展对象。"
        ),
        report_to="上级党委",
    ),
    UpperItem(
        key="probationary_approval",
        kind="approval",
        stage=MemberStage.PROBATIONARY.value,
        label="接收预备党员（报上级党委审批）",
        basis=(
            "《中国共产党发展党员工作细则》第二十一条、第二十二条：党支部应当及时将党员"
            "大会决议写入《中国共产党入党志愿书》，连同本人入党申请书、《入党积极分子培养"
            "考察登记表》、政治审查材料等，一并报上级党委审批；预备党员必须由党委审批。"
        ),
        report_to="具有审批权限的党委（工委）",
    ),
    UpperItem(
        key="member_approval",
        kind="approval",
        stage=MemberStage.MEMBER.value,
        label="预备党员转正（报上级党委审批）",
        basis=(
            "《中国共产党发展党员工作细则》第五章（预备党员的教育、考察和转正）："
            "预备党员转正由党支部党员大会讨论通过后报上级党委审批，审批结果及时通知党支部。"
        ),
        report_to="具有审批权限的党委（工委）",
    ),
)
UPPER_ITEM_MAP: dict[str, UpperItem] = {item.key: item for item in UPPER_ITEMS}


def item_spec(key: str) -> UpperItem:
    spec = UPPER_ITEM_MAP.get(key)
    if spec is None:
        raise HTTPException(422, "报送事项无效")
    return spec


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def load_rules() -> dict[str, Any]:
    """读取审批 / 备案配置；文件缺失或字段非法时回落默认，不阻断业务。"""
    try:
        data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    entry = data.get("upper_report") or {}

    def positive(value: Any, fallback: int) -> int:
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
            else fallback
        )

    raw_extra = entry.get("extra_materials") or {}
    extra: dict[str, tuple[str, ...]] = {}
    if isinstance(raw_extra, dict):
        for key, names in raw_extra.items():
            if not isinstance(names, list):
                continue
            cleaned = tuple(str(name).strip() for name in names if str(name).strip())
            if cleaned:
                extra[str(key)] = cleaned
    return {
        "approval_days": positive(entry.get("approval_days"), DEFAULT_APPROVAL_DAYS),
        "remind_advance_days": positive(
            entry.get("remind_advance_days"), DEFAULT_REMIND_ADVANCE_DAYS
        ),
        "extra_materials": extra,
    }


def report_materials(
    spec: UpperItem, stage: MemberStage, rules: StageRules, extra: Sequence[str]
) -> tuple[str, ...]:
    """随报材料 = 该阶段沿发展链累加的材料要求 + 本事项另需材料，去重保序。

    与阶段流转、组织关系转入的档案清单**同一来源**：同一份材料不允许在两处各写一遍，
    否则"清单里有没有这一项"永远对不上。
    """
    names: list[str] = list(rules.materials_for_stage(stage))
    for name in extra:
        if name not in names:
            names.append(name)
    return tuple(names)


def can_report(profile_stage: str, spec: UpperItem) -> bool:
    """阶段已到（或已过）该事项目标阶段才可报送：支部大会 / 支委会已作出决定。"""
    try:
        current = MemberStage(profile_stage)
    except ValueError:
        return False
    spec_stage = MemberStage(spec.stage)
    rules = StageRules.default()
    current_rank = rules.development_rank(current)
    spec_rank = rules.development_rank(spec_stage)
    if current_rank is None or spec_rank is None:
        return False
    return current_rank >= spec_rank


def approval_deadline(submitted_on: date, approval_days: int) -> date:
    return submitted_on + timedelta(days=approval_days)


def is_overdue(row: MemberUpperReport, approval_days: int, today: date) -> bool:
    """只有"审批类 + 待批复"才会超期；备案类细则未统一规定时限，不提示到期。"""
    if row.kind != "approval" or row.status != "submitted":
        return False
    return approval_deadline(row.submitted_on, approval_days) < today


def days_left(row: MemberUpperReport, approval_days: int, today: date) -> int | None:
    if row.kind != "approval":
        return None
    return (approval_deadline(row.submitted_on, approval_days) - today).days


def is_due_soon(row: MemberUpperReport, approval_days: int, advance_days: int, today: date) -> bool:
    """临近审批时限（到期前 `advance_days` 天内）：提前提示，而不是到期才发现。"""
    if row.kind != "approval" or row.status != "submitted":
        return False
    remaining = days_left(row, approval_days, today)
    return remaining is not None and 0 <= remaining <= advance_days


def stage_label(value: str | None) -> str:
    """阶段快照回读：历史行的阶段值可能已不在枚举内，读不出就留空而不是报错。"""
    try:
        return STAGE_LABELS.get(MemberStage(value or ""), "")
    except ValueError:
        return ""


class UpperReportService:
    """在请求事务内完成报送 / 回填业务，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []
        self.rules: StageRules = load_stage_rules()
        self.can_manage = has_permission(user.role, Permission.STAGE_TRANSITION)

    async def initialize(self) -> "UpperReportService":
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
        if profile.org_unit_id and profile.org_unit_id not in self.org_ids:
            raise HTTPException(404, "党员档案不存在或不在授权组织范围")
        return profile

    async def report_row(self, report_id: str, *, lock: bool = False) -> MemberUpperReport:
        stmt = select(MemberUpperReport).where(
            *self._scope(MemberUpperReport), MemberUpperReport.id == report_id
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "报送记录不存在或不在授权组织范围")
        return row

    async def _open_row(self, profile_id: str, item: str) -> MemberUpperReport | None:
        """同一党员同一事项同时只能有一次未办结的报送，否则"批复到哪一步"读不出来。"""
        return (
            await self.db.execute(
                select(MemberUpperReport).where(
                    *self._scope(MemberUpperReport),
                    MemberUpperReport.profile_id == profile_id,
                    MemberUpperReport.item == item,
                    MemberUpperReport.status == "submitted",
                )
            )
        ).scalar_one_or_none()

    async def _last_settled(self, profile_id: str, item: str) -> MemberUpperReport | None:
        """最近一次已回填的报送：用于提示"上一次批复不同意，重新报送前先落实"。"""
        return (
            await self.db.execute(
                select(MemberUpperReport)
                .where(
                    *self._scope(MemberUpperReport),
                    MemberUpperReport.profile_id == profile_id,
                    MemberUpperReport.item == item,
                    MemberUpperReport.status == "settled",
                )
                .order_by(MemberUpperReport.created_at.desc(), MemberUpperReport.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _save_revision(
        self, row: MemberUpperReport, action: str, reason: str, *, initial: bool = False
    ) -> None:
        """只追加的完整版本与真实操作人；报送不能靠"改一行"抹掉历史。"""
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type="member_upper_report",
                resource_id=str(row.id),
                revision=row.revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=row_data(row),
            )
        )
        await self.db.flush()

    def _materials_for(self, spec: UpperItem, rules_cfg: dict[str, Any]) -> tuple[str, ...]:
        stage = MemberStage(spec.stage)
        extra = rules_cfg["extra_materials"].get(spec.key, ())
        return report_materials(spec, stage, self.rules, extra)

    # ==================== 报送 / 回填 / 作废 ====================

    async def create(self, body: UpperReportCreate) -> dict[str, Any]:
        spec = item_spec(body.item)
        rules_cfg = load_rules()
        today = date.today()
        profile = await self.profile(str(body.profile_id), lock=True)
        self._require_org(profile.org_unit_id or "")
        if not can_report(profile.current_stage, spec):
            raise HTTPException(
                422,
                f"该党员当前阶段为「{stage_label(profile.current_stage) or profile.current_stage}」，"
                f"尚未到办理「{spec.label}」的环节：报送应在支部委员会 / 支部党员大会作出决定后登记",
            )
        existing = await self._open_row(str(profile.id), spec.key)
        if existing is not None:
            raise HTTPException(
                409,
                f"该党员已有一条未办结的「{spec.label}」报送记录"
                f"（{existing.submitted_on} 报 {existing.upper_org}），请先回填批复或作废后再报送",
            )
        row = MemberUpperReport(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            item=spec.key,
            kind=spec.kind,
            upper_org=body.upper_org,
            letter_no=body.letter_no,
            submitted_on=body.submitted_on,
            materials=list(self._materials_for(spec, rules_cfg)),
            note=body.note,
        )
        self.db.add(row)
        await self.db.flush()
        await self._save_revision(row, "submit", body.reason, initial=True)
        data = self.row_view(row, rules_cfg, today=today)
        notice = (
            "已登记报送：本记录只表示材料已报出，党员阶段不受影响；"
            "收到上级批复后在台账回填批复结果"
        )
        previous = await self._last_settled(str(profile.id), spec.key)
        if previous is not None and previous.result == "rejected":
            notice = (
                f"已登记报送。注意：上一次「{spec.label}」的批复为「不同意」"
                f"（{previous.decided_on or ''} {previous.reply_no}），重新报送前请先落实上级意见"
            )
        data.update({"notice": notice, "boundary": DECISION_BOUNDARY})
        return data

    async def settle(self, report_id: str, body: UpperReportSettle) -> dict[str, Any]:
        """回填上级批复结果；这是登记上级的结论，不是系统作出结论，也不改动党员阶段。"""
        rules_cfg = load_rules()
        row = await self.report_row(report_id, lock=True)
        if row.status == "settled":
            raise HTTPException(409, "本次报送已回填批复，无需重复回填")
        if row.status == "revoked":
            raise HTTPException(409, "本次报送已作废，不能回填批复")
        decided_on = body.decided_on or date.today()
        if decided_on < row.submitted_on:
            raise HTTPException(422, "批复日期不能早于报送日期")
        row.status = "settled"
        row.result = body.result
        row.decided_on = decided_on
        row.reply_no = body.reply_no
        row.decide_note = body.decide_note
        await self._save_revision(row, "settle", body.reason)
        data = self.row_view(row, rules_cfg, today=date.today())
        data.update({"notice": self._settle_notice(row), "boundary": DECISION_BOUNDARY})
        return data

    @staticmethod
    def _settle_notice(row: MemberUpperReport) -> str:
        if row.result == "agreed":
            return (
                "已回填批复「同意 / 批准」。党员阶段不会自动变化："
                "请按程序由授权人员在阶段流转中人工办理，并把批复件归入档案"
            )
        if row.result == "rejected":
            return (
                "已回填批复「不同意」。系统不自动回退阶段、不自动移出名册；"
                "请按上级结论与有关规定研究后续处理并人工办理阶段调整"
            )
        return "已回填「需补充材料」：补齐后重新报送，本次报送记录保留可查"

    async def revoke(self, report_id: str, body: UpperReportRevoke) -> dict[str, Any]:
        """作废本次报送（报错事项 / 重复报送 / 报送有误），记录不删除。"""
        rules_cfg = load_rules()
        row = await self.report_row(report_id, lock=True)
        if row.status == "revoked":
            raise HTTPException(409, "本次报送已作废，无需重复作废")
        row.status = "revoked"
        row.revoked_on = date.today()
        row.revoke_reason = body.reason
        await self._save_revision(row, "revoke", body.reason)
        data = self.row_view(row, rules_cfg, today=date.today())
        data.update(
            {
                "notice": "已作废：该次报送视同未发生，需重新报送时按新记录登记；原记录保留可查",
                "boundary": DECISION_BOUNDARY,
            }
        )
        return data

    # ==================== 读取 ====================

    def row_view(
        self, row: MemberUpperReport, rules_cfg: dict[str, Any], *, today: date | None = None
    ) -> dict[str, Any]:
        """一行的可读视图：事项、依据、随报材料、批复结果与审批类到期提示。"""
        current = today or date.today()
        spec = UPPER_ITEM_MAP.get(row.item)
        approval_days = rules_cfg["approval_days"]
        advance_days = rules_cfg["remind_advance_days"]
        overdue = is_overdue(row, approval_days, current)
        remaining = days_left(row, approval_days, current)
        due_soon = is_due_soon(row, approval_days, advance_days, current)
        materials = [str(name) for name in (row.materials or [])]
        return {
            "id": str(row.id),
            "item": row.item,
            "item_label": spec.label if spec else row.item,
            "kind": row.kind,
            "kind_label": KIND_LABELS.get(row.kind, row.kind),
            "basis": spec.basis if spec else "",
            "report_to": spec.report_to if spec else "",
            "status": row.status,
            "status_label": STATUS_LABELS.get(row.status, row.status),
            "profile_id": row.profile_id,
            "member_name": row.member_name,
            "stage": row.stage,
            "stage_label": stage_label(row.stage),
            "org_unit_id": row.org_unit_id,
            "org_name": row.org_name,
            "upper_org": row.upper_org,
            "letter_no": row.letter_no,
            "submitted_on": row.submitted_on,
            "materials": materials,
            "material_count": len(materials),
            "result": row.result,
            "result_label": RESULT_LABELS.get(row.result, ""),
            "decided_on": row.decided_on,
            "reply_no": row.reply_no,
            "decide_note": row.decide_note,
            "deadline": (
                approval_deadline(row.submitted_on, approval_days)
                if row.kind == "approval"
                else None
            ),
            "days_left": remaining,
            "overdue": overdue,
            "due_soon": due_soon,
            "overdue_notice": self._overdue_notice(row) if overdue else "",
            "no_deadline_note": NO_DEADLINE_NOTE if row.kind != "approval" else "",
            "note": row.note,
            "revoked_on": row.revoked_on,
            "revoke_reason": row.revoke_reason,
            "created_at": row.created_at,
        }

    @staticmethod
    def _overdue_notice(row: MemberUpperReport) -> str:
        return (
            f"已超过细则规定的审批时限（三个月内审批，特殊情况不超过六个月）仍未回填批复："
            f"请向 {row.upper_org} 核实审批进度并回填结果；系统只提示，不判定审批失效、"
            "也不改动党员阶段"
        )

    async def list_reports(
        self,
        *,
        item: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        org_unit_id: str | None = None,
        profile_id: str | None = None,
        overdue_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """报送台账：按事项 / 类别 / 状态 / 组织 / 档案筛选，附待办汇总与到期提示。"""
        rules_cfg = load_rules()
        if item is not None:
            item_spec(item)
        if kind is not None and kind not in KIND_LABELS:
            raise HTTPException(422, "报送类别只能是备案或审批")
        if status is not None and status not in STATUS_LABELS:
            raise HTTPException(422, "报送状态无效")
        if org_unit_id is not None:
            self._require_org(org_unit_id)
        conditions = list(self._scope(MemberUpperReport))
        if item is not None:
            conditions.append(MemberUpperReport.item == item)
        if kind is not None:
            conditions.append(MemberUpperReport.kind == kind)
        if status is not None:
            conditions.append(MemberUpperReport.status == status)
        if org_unit_id is not None:
            conditions.append(MemberUpperReport.org_unit_id == org_unit_id)
        if profile_id is not None:
            conditions.append(MemberUpperReport.profile_id == profile_id)
        if overdue_only:
            conditions.append(MemberUpperReport.status == "submitted")
            conditions.append(MemberUpperReport.kind == "approval")
            conditions.append(
                MemberUpperReport.submitted_on
                < date.today() - timedelta(days=rules_cfg["approval_days"])
            )
        total = (
            await self.db.execute(select(func.count(MemberUpperReport.id)).where(*conditions))
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(MemberUpperReport)
                    .where(*conditions)
                    .order_by(MemberUpperReport.submitted_on.desc(), MemberUpperReport.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        today = date.today()
        return {
            "items": [self.row_view(row, rules_cfg, today=today) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "summary": await self.summary(rules_cfg),
            "items_catalog": [self._catalog_entry(spec) for spec in UPPER_ITEMS],
            "notice": REPORT_NOTICE,
            "boundary": DECISION_BOUNDARY,
        }

    def _catalog_entry(self, spec: UpperItem) -> dict[str, Any]:
        """事项目录：界面据此给出依据与默认随报材料，而不是自己编一套文案。"""
        return {
            "item": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "kind_label": KIND_LABELS.get(spec.kind, spec.kind),
            "stage": spec.stage,
            "stage_label": stage_label(spec.stage),
            "basis": spec.basis,
            "report_to": spec.report_to,
            "materials": list(self._materials_for(spec, load_rules())),
        }

    async def summary(self, rules_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        """待办汇总：待批复（其中审批类）、审批超期未回填、需补充材料、已回填、本年度报送。"""
        config = rules_cfg or load_rules()
        rows = (
            await self.db.execute(
                select(
                    MemberUpperReport.status,
                    MemberUpperReport.kind,
                    MemberUpperReport.result,
                    MemberUpperReport.submitted_on,
                ).where(*self._scope(MemberUpperReport))
            )
        ).all()
        today = date.today()
        summary = {
            "pending": 0,
            "pending_approval": 0,
            "overdue": 0,
            "supplement": 0,
            "settled": 0,
            "revoked": 0,
            "this_year": 0,
        }
        for status, kind, result, submitted_on in rows:
            if status == "revoked":
                summary["revoked"] += 1
                continue
            if status == "submitted":
                summary["pending"] += 1
                if kind == "approval":
                    summary["pending_approval"] += 1
                    if approval_deadline(submitted_on, config["approval_days"]) < today:
                        summary["overdue"] += 1
            else:
                summary["settled"] += 1
                if result == "supplement":
                    summary["supplement"] += 1
            if submitted_on and submitted_on.year == today.year:
                summary["this_year"] += 1
        return summary

    async def detail(self, report_id: str) -> dict[str, Any]:
        rules_cfg = load_rules()
        row = await self.report_row(report_id)
        data = self.row_view(row, rules_cfg)
        data.update(
            {
                "history": await self.history(report_id),
                "notice": REPORT_NOTICE,
                "boundary": DECISION_BOUNDARY,
            }
        )
        return data

    async def history(self, report_id: str) -> list[dict[str, Any]]:
        """只追加操作留痕：报送、回填、作废各留一条，能看到谁在何时做了什么。"""
        await self.report_row(report_id)
        rows = (
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == "member_upper_report",
                        ContentRevision.resource_id == str(report_id),
                        ContentRevision.is_deleted.is_(False),
                    )
                    .order_by(ContentRevision.created_at, ContentRevision.id)
                )
            )
            .scalars()
            .all()
        )
        return [row_data(item) for item in rows]

    async def export_rows(self, *, limit: int) -> tuple[list[dict[str, Any]], int]:
        """导出用行：按报送日期倒序，超过上限时由 API 层给 413 而不是静默截断。"""
        rules_cfg = load_rules()
        conditions = list(self._scope(MemberUpperReport))
        total = (
            await self.db.execute(select(func.count(MemberUpperReport.id)).where(*conditions))
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(MemberUpperReport)
                    .where(*conditions)
                    .order_by(MemberUpperReport.submitted_on.desc(), MemberUpperReport.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        today = date.today()
        views = [self.row_view(row, rules_cfg, today=today) for row in rows]
        return views, total
