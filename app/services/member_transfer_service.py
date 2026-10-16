"""组织关系接转（模块2 延伸 / T-MEM-14）：转入 / 转出与介绍信，人工登记、可撤销、留痕。

依据《中国共产党党员教育管理工作条例》第五章"党员组织关系管理"：党员组织关系介绍信
是党员政治身份的证明，党员转移组织关系须办理转入 / 转出。介绍信有效期按上级党组织规定，
系统只提供默认天数与到期提示，不代替上级规定。

三处最容易做成"反人类"的地方，本模块专门规避：

1. **转出 ≠ 删除，也 ≠ 阶段流转**。转出的是组织关系，人还是党员。因此接转单独记
   ``member_transfers``，不动 ``member_profiles.current_stage``，也不删档案；名册以
   "已转出"标识说明他去哪了，历史仍可查。
2. **开介绍信 ≠ 转出完成**。本人要持介绍信到新组织报到、新组织回执才算落地，中间是
   "待接收"。系统把这一真实状态记下来，并在超过有效期仍无回执时提示核实，但**不自动
   判定失败、也不自动把关系挂到新组织**。
3. **转入要核对档案**。转入时按党员所处阶段，沿既有材料要求（与阶段流转同一来源）
   累加出档案清单，缺项落 ``member_archive_checks``（档案完整性检查衔接），缺什么一次
   说清；缺项只提示，不阻断登记（宁缺勿假，真实档案往往后补）。

接收单位联系人与电话不落库：那是第三人信息，接转只需要对方组织名称与介绍信要素。
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

import yaml
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.meeting import ContentRevision
from app.models.member import MemberArchiveCheck, MemberProfile, MemberTransfer
from app.models.user import User
from app.rules.member_stages import STAGE_LABELS, MemberStage, StageRules, load_stage_rules
from app.schemas.member_transfer import TransferCreate, TransferRevoke, TransferSettle
from app.services.org_scope import visible_org_units
from app.utils.snapshot import record_snapshot as row_data

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "business_rules.yaml"

DIRECTION_LABELS: dict[str, str] = {"in": "转入", "out": "转出"}
STATUS_LABELS: dict[str, str] = {"pending": "待接收", "settled": "已接收", "revoked": "已作废"}
# 组织关系状态只有三种：在册 / 转出待接收 / 已转出。由最新一条有效接转记录推导，不另存字段。
STATE_LABELS: dict[str, str] = {
    "in_place": "在册",
    "out_pending": "转出待接收",
    "transferred_out": "已转出",
}
# 组织关系接转适用于预备党员与正式党员；培养对象的材料转递不是"党员组织关系接转"。
TRANSFER_STAGES: tuple[str, ...] = (MemberStage.PROBATIONARY.value, MemberStage.MEMBER.value)

DEFAULT_LETTER_VALID_DAYS = 90
DEFAULT_REMIND_ADVANCE_DAYS = 15

MAX_LIST = 200
MAX_PROFILES_PER_QUERY = 2000

TRANSFER_NOTICE = (
    "接转只记录事实：转出须收到回执才算完成，转入须核对档案；"
    "系统不自动认定接收，也不因介绍信到期自动判定失败"
)
DECISION_BOUNDARY = (
    "组织关系接转由组织部门按上级规定办理，系统只登记介绍信要素与回执，不代替审批与备案"
)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def load_rules() -> dict[str, int]:
    """读取接转配置；文件缺失或字段非法时回落默认，不阻断业务。"""
    try:
        data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    entry = data.get("member_transfer") or {}
    valid = entry.get("letter_valid_days")
    advance = entry.get("remind_advance_days")
    return {
        "letter_valid_days": (
            int(valid) if isinstance(valid, int) and valid > 0 else DEFAULT_LETTER_VALID_DAYS
        ),
        "remind_advance_days": (
            int(advance)
            if isinstance(advance, int) and advance >= 0
            else DEFAULT_REMIND_ADVANCE_DAYS
        ),
    }


def letter_validity(issued_on: date, valid_days: int) -> date:
    """介绍信有效期至 = 开具日期 + 有效期天数；天数非法时按默认 90 天。"""
    days = (
        valid_days if isinstance(valid_days, int) and valid_days > 0 else DEFAULT_LETTER_VALID_DAYS
    )
    return date.fromordinal(issued_on.toordinal() + days)


def is_overdue(status: str, valid_until: date, today: date) -> bool:
    """只有"待接收"才会逾期：已回执、已作废都不再提示。"""
    return status == "pending" and valid_until < today


def days_left(valid_until: date, today: date) -> int:
    return (valid_until - today).days


def state_from_records(records: Sequence[tuple[str, str]]) -> str:
    """由"按时间升序的方向与状态"推导组织关系状态；作废记录视同未发生。

    转入总是把状态带回"在册"（人已经在本组织）；转出待接收是"转出待接收"，转出已回执
    才是"已转出"。同一档案上"转出后又转入"能正确回到在册，不会被上一次转出粘住。
    """
    state = "in_place"
    for direction, status in records:
        if status == "revoked":
            continue
        if direction == "out":
            state = "transferred_out" if status == "settled" else "out_pending"
        else:
            state = "in_place"
    return state


def stage_label(value: str | None) -> str:
    """阶段快照回读：历史行的阶段值可能已不在枚举内，读不出就留空而不是报错。"""
    try:
        return STAGE_LABELS.get(MemberStage(value or ""), "")
    except ValueError:
        return ""


async def latest_transfer_states(
    db: AsyncSession, tenant_id: str, profile_ids: Sequence[str]
) -> dict[str, str]:
    """一批档案的组织关系状态：只取未被作废的接转记录按时间推导。

    供名册标识、名册统计与"是否还算本组织在册党员"（民主评议应评议名单）复用——
    三处口径必须一致，否则会出现"名册说已转出、评议里还在评"的互相打脸。
    """
    ids = [str(item) for item in dict.fromkeys(profile_ids)][:MAX_PROFILES_PER_QUERY]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(MemberTransfer.direction, MemberTransfer.status, MemberTransfer.profile_id)
            .where(
                MemberTransfer.tenant_id == tenant_id,
                MemberTransfer.is_deleted.is_(False),
                MemberTransfer.profile_id.in_(ids),
            )
            .order_by(MemberTransfer.created_at, MemberTransfer.id)
        )
    ).all()
    records: dict[str, list[tuple[str, str]]] = {}
    for direction, status, profile_id in rows:
        records.setdefault(str(profile_id), []).append((direction, status))
    return {profile_id: state_from_records(items) for profile_id, items in records.items()}


async def transferred_out_profile_ids(
    db: AsyncSession, tenant_id: str, profile_ids: Sequence[str]
) -> set[str]:
    """组织关系已转出（最新一条接转已回执）的档案：不再算本组织在册党员。"""
    states = await latest_transfer_states(db, tenant_id, profile_ids)
    return {profile_id for profile_id, state in states.items() if state == "transferred_out"}


class TransferService:
    """在请求事务内完成接转业务，提交由 API 层统一管理。"""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
        self.tenant_id = str(user.tenant_id)
        self.orgs: list[Any] = []
        self.org_ids: list[str] = []
        self.rules: StageRules = load_stage_rules()
        self.can_manage = has_permission(user.role, Permission.STAGE_TRANSITION)

    async def initialize(self) -> "TransferService":
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

    async def transfer_row(self, transfer_id: str, *, lock: bool = False) -> MemberTransfer:
        stmt = select(MemberTransfer).where(
            *self._scope(MemberTransfer), MemberTransfer.id == transfer_id
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "接转记录不存在或不在授权组织范围")
        return row

    async def _open_transfer(self, profile_id: str) -> MemberTransfer | None:
        """同一档案同时只能有一次未办结的接转，否则"当前关系在哪"读不出来。"""
        return (
            await self.db.execute(
                select(MemberTransfer).where(
                    *self._scope(MemberTransfer),
                    MemberTransfer.profile_id == profile_id,
                    MemberTransfer.status == "pending",
                )
            )
        ).scalar_one_or_none()

    async def _save_revision(
        self, row: MemberTransfer, action: str, reason: str, *, initial: bool = False
    ) -> None:
        """只追加的完整版本与真实操作人；接转不能靠"改一行"抹掉历史。"""
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=self.tenant_id,
                resource_type="member_transfer",
                resource_id=str(row.id),
                revision=row.revision,
                action=action,
                actor_id=str(self.user.id),
                reason=reason,
                snapshot=row_data(row),
            )
        )
        await self.db.flush()

    async def _sync_relation(self, profile: MemberProfile) -> str:
        """把接转台账的最新状态推导后写进档案缓存列（本列只由本服务写）。"""
        state = await self.state_of(str(profile.id))
        profile.relation_status = state
        await self.db.flush()
        return state

    # ==================== 档案核对（转入衔接 T-MEM-09） ====================

    def archive_plan(self, profile: MemberProfile) -> dict[str, Any]:
        """转入档案清单：按阶段沿既有材料要求累加，缺项 = 清单里尚未登记的材料。"""
        try:
            stage = MemberStage(profile.current_stage)
        except ValueError:
            # 历史行的阶段值可能已不在枚举内：不猜清单、也不报错，交给人工按档案核对
            return {"required": [], "missing": []}
        required = list(self.rules.materials_for_stage(stage))
        present = {str(name).strip() for name in (profile.materials or []) if str(name).strip()}
        return {"required": required, "missing": [name for name in required if name not in present]}

    async def _record_archive_check(
        self, profile: MemberProfile, plan: dict[str, Any]
    ) -> MemberArchiveCheck:
        check = MemberArchiveCheck(
            tenant_id=self.tenant_id,
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            checked_at=utc_now(),
            checked_by=str(self.user.id),
            rule_version="business_rules:1",
            result={
                "required_for": (
                    f"组织关系转入（{stage_label(profile.current_stage) or profile.current_stage}）"
                ),
                "missing": plan["missing"],
                "irregular": [],
                "risks": [],
            },
        )
        self.db.add(check)
        await self.db.flush()
        return check

    # ==================== 登记 ====================

    async def create(self, body: TransferCreate) -> dict[str, Any]:
        rules = load_rules()
        today = date.today()
        if body.direction == "out":
            return await self._create_out(body, rules, today)
        return await self._create_in(body, rules, today)

    async def _create_out(
        self, body: TransferCreate, rules: dict[str, int], today: date
    ) -> dict[str, Any]:
        profile = await self.profile(str(body.profile_id), lock=True)
        self._require_org(profile.org_unit_id or "")
        self._check_stage(profile)
        if await self.state_of(str(profile.id)) == "transferred_out":
            # 关系已经转走，再开一封介绍信就是重复登记：要办理回转应走转入
            raise HTTPException(
                409, "该党员组织关系已转出，如需再次办理请按转入登记，不要重复开具介绍信"
            )
        existing = await self._open_transfer(str(profile.id))
        if existing is not None:
            raise HTTPException(
                409,
                f"该党员已有一次未办结的接转（{DIRECTION_LABELS.get(existing.direction, '')}"
                f"介绍信 {existing.letter_no}），请先回执或作废后再发起",
            )
        row = MemberTransfer(
            tenant_id=self.tenant_id,
            direction="out",
            profile_id=str(profile.id),
            org_unit_id=profile.org_unit_id or "",
            org_name=profile.org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            counterpart_org=body.counterpart_org,
            letter_no=body.letter_no,
            issued_on=body.issued_on,
            valid_until=body.valid_until
            or letter_validity(body.issued_on, rules["letter_valid_days"]),
            note=body.note,
        )
        self.db.add(row)
        await self.db.flush()
        await self._save_revision(row, "create", body.reason, initial=True)
        state = await self._sync_relation(profile)
        data = self.row_view(row, today=today)
        data.update(
            {
                "state": state,
                "state_label": STATE_LABELS[state],
                "notice": (
                    "介绍信已登记为待接收：本人持介绍信到对方组织报到并回执后才算转出完成；"
                    "到期未回执请核实是否已报到"
                ),
            }
        )
        return data

    async def _create_in(
        self, body: TransferCreate, rules: dict[str, int], today: date
    ) -> dict[str, Any]:
        org_unit_id = body.org_unit_id or ""
        org_name = self._require_org(org_unit_id)
        created_profile = False
        if body.profile_id:
            profile = await self.profile(body.profile_id, lock=True)
            self._check_stage(profile)
            existing = await self._open_transfer(str(profile.id))
            if existing is not None:
                raise HTTPException(
                    409,
                    f"该党员已有一次未办结的接转（{DIRECTION_LABELS.get(existing.direction, '')}"
                    f"介绍信 {existing.letter_no}），请先回执或作废后再发起",
                )
            # 同一学校内支部之间调动：档案归属改到接收组织，接转台账保留"从哪来到哪去"
            if profile.org_unit_id != org_unit_id:
                profile.org_unit_id = org_unit_id
                profile.org_name = org_name
                await self.db.flush()
        else:
            stage = body.current_stage or MemberStage.MEMBER.value
            profile = MemberProfile(
                tenant_id=self.tenant_id,
                name=body.name or "",
                org_unit_id=org_unit_id,
                org_name=org_name,
                current_stage=stage,
                stage_joined_on=body.stage_joined_on or today,
                materials=[],
                pending=0,
            )
            self.db.add(profile)
            await self.db.flush()
            created_profile = True

        plan = self.archive_plan(profile)
        check = await self._record_archive_check(profile, plan)
        row = MemberTransfer(
            tenant_id=self.tenant_id,
            direction="in",
            profile_id=str(profile.id),
            org_unit_id=org_unit_id,
            org_name=org_name,
            member_name=profile.name,
            stage=profile.current_stage,
            counterpart_org=body.counterpart_org,
            letter_no=body.letter_no,
            issued_on=body.issued_on,
            valid_until=body.valid_until
            or letter_validity(body.issued_on, rules["letter_valid_days"]),
            note=body.note,
        )
        self.db.add(row)
        await self.db.flush()
        await self._save_revision(row, "create", body.reason, initial=True)
        state = await self._sync_relation(profile)
        data = self.row_view(row, today=today)
        data.update(
            {
                "state": state,
                "state_label": STATE_LABELS[state],
                "created_profile": created_profile,
                "archive": {
                    "check_id": str(check.id),
                    "required": plan["required"],
                    "missing": plan["missing"],
                },
                "notice": (
                    "转入已登记为待核对档案：请按档案清单逐项核对本人档案并回执；"
                    "缺项不影响登记，核对完成后回执即可"
                ),
            }
        )
        return data

    def _check_stage(self, profile: MemberProfile) -> None:
        if profile.current_stage not in TRANSFER_STAGES:
            raise HTTPException(
                422,
                "组织关系接转适用于预备党员与正式党员；培养对象的材料转递请在档案中登记",
            )
        if not profile.org_unit_id:
            raise HTTPException(422, "该党员未归属有效组织，请先在档案中补齐")

    # ==================== 回执与作废 ====================

    async def settle(self, transfer_id: str, body: TransferSettle) -> dict[str, Any]:
        """转出回执 / 转入档案核对完成。已回执或已作废的不能再回执。"""
        row = await self.transfer_row(transfer_id, lock=True)
        if row.status == "revoked":
            raise HTTPException(409, "本次接转已作废，不能再回执；如需继续请重新登记")
        if row.status == "settled":
            raise HTTPException(409, "本次接转已回执，无需重复登记")
        today = date.today()
        row.status = "settled"
        row.settled_on = body.settled_on or today
        if body.receipt_no:
            row.receipt_no = body.receipt_no
        if body.note:
            row.note = f"{row.note}；{body.note}" if row.note else body.note
        await self._save_revision(row, "settle", body.reason)
        profile = await self.profile(row.profile_id, lock=True)
        state = await self._sync_relation(profile)
        data = self.row_view(row, today=today)
        data.update(
            {
                "state": state,
                "state_label": STATE_LABELS[state],
                "notice": (
                    "已登记回执：本次转出完成，该党员不再计入本组织在册名单与应评议名单"
                    if row.direction == "out"
                    else "已登记回执：转入办结，档案缺项仍可在档案面板逐项补齐"
                ),
            }
        )
        return data

    async def revoke(self, transfer_id: str, body: TransferRevoke) -> dict[str, Any]:
        """作废本次接转（介绍信开错 / 未办成 / 回执录错），记录不删除。"""
        row = await self.transfer_row(transfer_id, lock=True)
        if row.status == "revoked":
            raise HTTPException(409, "本次接转已作废，无需重复作废")
        row.status = "revoked"
        row.revoked_on = date.today()
        row.revoke_reason = body.reason
        await self._save_revision(row, "revoke", body.reason)
        profile = await self.profile(row.profile_id, lock=True)
        state = await self._sync_relation(profile)
        data = self.row_view(row, today=date.today())
        data.update(
            {
                "state": state,
                "state_label": STATE_LABELS[state],
                "notice": (
                    "已作废：该次接转视同未发生，组织关系状态按其余有效记录重新推导；"
                    "记录保留可查"
                ),
            }
        )
        return data

    # ==================== 读取 ====================

    async def state_of(self, profile_id: str) -> str:
        states = await latest_transfer_states(self.db, self.tenant_id, [profile_id])
        return states.get(profile_id, "in_place")

    def row_view(self, row: MemberTransfer, *, today: date | None = None) -> dict[str, Any]:
        """一行接转的可读视图：状态、有效期剩余天数与到期提示。"""
        current = today or date.today()
        overdue = is_overdue(row.status, row.valid_until, current)
        return {
            "id": str(row.id),
            "direction": row.direction,
            "direction_label": DIRECTION_LABELS.get(row.direction, row.direction),
            "status": row.status,
            "status_label": STATUS_LABELS.get(row.status, row.status),
            "profile_id": row.profile_id,
            "member_name": row.member_name,
            "stage": row.stage,
            "stage_label": stage_label(row.stage),
            "org_unit_id": row.org_unit_id,
            "org_name": row.org_name,
            "counterpart_org": row.counterpart_org,
            "letter_no": row.letter_no,
            "issued_on": row.issued_on,
            "valid_until": row.valid_until,
            "days_left": days_left(row.valid_until, current),
            "overdue": overdue,
            "overdue_notice": self._overdue_notice(row) if overdue else "",
            "settled_on": row.settled_on,
            "receipt_no": row.receipt_no,
            "note": row.note,
            "revoked_on": row.revoked_on,
            "revoke_reason": row.revoke_reason,
            "created_at": row.created_at,
        }

    @staticmethod
    def _overdue_notice(row: MemberTransfer) -> str:
        if row.direction == "out":
            return (
                f"介绍信已超过有效期仍未回执（{row.counterpart_org}），"
                "请核实本人是否已到新组织报到并联系接收组织确认；系统不自动判定转出失败"
            )
        return (
            f"介绍信已超过有效期仍未回执（来自 {row.counterpart_org}），"
            "请核实档案核对进度并回执；系统不自动认定转入完成"
        )

    async def list_transfers(
        self,
        *,
        direction: str | None = None,
        status: str | None = None,
        org_unit_id: str | None = None,
        profile_id: str | None = None,
        overdue_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """接转台账：按方向 / 状态 / 组织 / 档案筛选，附待办汇总与到期提示。"""
        if direction is not None and direction not in DIRECTION_LABELS:
            raise HTTPException(422, "接转方向只能是转入或转出")
        if status is not None and status not in STATUS_LABELS:
            raise HTTPException(422, "接转状态无效")
        if org_unit_id is not None:
            self._require_org(org_unit_id)
        conditions = list(self._scope(MemberTransfer))
        if direction is not None:
            conditions.append(MemberTransfer.direction == direction)
        if status is not None:
            conditions.append(MemberTransfer.status == status)
        if org_unit_id is not None:
            conditions.append(MemberTransfer.org_unit_id == org_unit_id)
        if profile_id is not None:
            conditions.append(MemberTransfer.profile_id == profile_id)
        if overdue_only:
            conditions.append(MemberTransfer.status == "pending")
            conditions.append(MemberTransfer.valid_until < date.today())
        total = (
            await self.db.execute(select(func.count(MemberTransfer.id)).where(*conditions))
        ).scalar_one()
        rows = (
            (
                await self.db.execute(
                    select(MemberTransfer)
                    .where(*conditions)
                    .order_by(MemberTransfer.created_at.desc(), MemberTransfer.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        today = date.today()
        states = await latest_transfer_states(
            self.db, self.tenant_id, [row.profile_id for row in rows]
        )
        items = []
        for row in rows:
            view = self.row_view(row, today=today)
            view["state"] = states.get(row.profile_id, "in_place")
            view["state_label"] = STATE_LABELS[view["state"]]
            items.append(view)
        summary = await self.summary()
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "summary": summary,
            "notice": TRANSFER_NOTICE,
            "boundary": DECISION_BOUNDARY,
        }

    async def summary(self) -> dict[str, Any]:
        """待办汇总：待接收（转出待回执）、待核对（转入待回执）、已逾期、本年度转入 / 转出。"""
        rows = (
            await self.db.execute(
                select(
                    MemberTransfer.direction,
                    MemberTransfer.status,
                    MemberTransfer.valid_until,
                    MemberTransfer.settled_on,
                ).where(*self._scope(MemberTransfer))
            )
        ).all()
        today = date.today()
        summary = {
            "pending_out": 0,
            "pending_in": 0,
            "overdue": 0,
            "settled_out": 0,
            "settled_in": 0,
            "revoked": 0,
            "this_year_out": 0,
            "this_year_in": 0,
            "pending_total": 0,
        }
        for direction, status, valid_until, settled_on in rows:
            if status == "revoked":
                summary["revoked"] += 1
                continue
            if status == "pending":
                summary["pending_total"] += 1
                summary["pending_out" if direction == "out" else "pending_in"] += 1
                if is_overdue(status, valid_until, today):
                    summary["overdue"] += 1
            else:
                summary["settled_out" if direction == "out" else "settled_in"] += 1
            if settled_on and settled_on.year == today.year:
                summary["this_year_out" if direction == "out" else "this_year_in"] += 1
        return summary

    async def detail(self, transfer_id: str) -> dict[str, Any]:
        row = await self.transfer_row(transfer_id)
        data = self.row_view(row)
        data.update(
            {
                "state": await self.state_of(row.profile_id),
                "history": await self.history(transfer_id),
                "notice": TRANSFER_NOTICE,
                "boundary": DECISION_BOUNDARY,
            }
        )
        return data

    async def history(self, transfer_id: str) -> list[dict[str, Any]]:
        """只追加操作留痕：登记、回执、作废各留一条，能看到谁在何时做了什么。"""
        await self.transfer_row(transfer_id)
        rows = (
            (
                await self.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == self.tenant_id,
                        ContentRevision.resource_type == "member_transfer",
                        ContentRevision.resource_id == str(transfer_id),
                        ContentRevision.is_deleted.is_(False),
                    )
                    .order_by(ContentRevision.created_at, ContentRevision.id)
                )
            )
            .scalars()
            .all()
        )
        return [row_data(item) for item in rows]
