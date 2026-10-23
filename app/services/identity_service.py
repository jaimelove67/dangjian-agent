"""租户和身份管理。平台管理员跨校授权必须由真实平台租户验证。"""

import re
import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.desensitization import mask_id_card
from app.core.security import hash_password
from app.core.tenant import bypass_tenant_filter
from app.models.org import OrgLeaderTerm, OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole

TENANT_PARENTS = {"school": "platform", "department": "school", "branch": "department"}
ORG_PARENTS = {"school": set(), "department": {"school"}, "branch": {"school", "department"}}
# 角色可绑定的组织类型：开户（admin.py）与编辑（save_user）共用一份口径，
# 避免同一个人"新建能过、编辑报错"这类两端口径漂移。
ROLE_ORG_TYPES: dict[UserRole, set[str]] = {
    UserRole.SCHOOL_ADMIN: {"school"},
    UserRole.DEPARTMENT_ADMIN: {"department"},
    UserRole.BRANCH_SECRETARY: {"branch"},
    UserRole.ORGANIZER: {"branch", "department"},
    UserRole.MEMBER: {"branch"},
    UserRole.APPLICANT: {"branch"},
}


_ID_CARD_PATTERN = re.compile(r"^\d{17}[\dXx]$")


def masked_username(value: str) -> str:
    """登录名是身份证号时按 6+4 脱敏；其余账号（工号、英文名）原样返回。"""
    return mask_id_card(value) if _ID_CARD_PATTERN.fullmatch(value) else value


def public_record(row: Any) -> dict[str, Any]:
    # 任职记录有自己的对外形状（日期 ISO、is_current 推导），不走字段白名单
    if isinstance(row, OrgLeaderTerm):
        return leader_payload(row)
    fields = {
        Tenant: ("id", "name", "tenant_type", "parent_id", "is_active", "config_version"),
        OrgUnit: (
            "id",
            "name",
            "org_type",
            "parent_id",
            "is_active",
            "path",
            "leader_name",
            "leader_title",
            "leader_phone",
        ),
        User: ("id", "username", "name", "role", "org_unit_id", "is_active"),
    }[type(row)]
    data = {key: getattr(row, key) for key in fields}
    # 身份证号不出网：列表、审计、编辑回显统一用脱敏值，登录匹配仍用库里完整号。
    if isinstance(row, User) and data.get("username"):
        data["username"] = masked_username(str(data["username"]))
    return data


def leader_payload(row: OrgLeaderTerm) -> dict[str, Any]:
    """任职记录的对外形状：日期转 ISO 字符串，``is_current`` 由离任日期推导"""
    return {
        "id": row.id,
        "org_unit_id": row.org_unit_id,
        "name": row.name,
        "title": row.title,
        "phone": row.phone,
        "started_on": row.started_on.isoformat() if row.started_on else None,
        "ended_on": row.ended_on.isoformat() if row.ended_on else None,
        "is_primary": row.is_primary,
        "is_current": row.ended_on is None,
        "remark": row.remark,
    }


async def is_platform_admin(db: AsyncSession, user: User) -> bool:
    if user.role != UserRole.SYSTEM_ADMIN:
        return False
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(Tenant).where(
                    Tenant.id == str(user.tenant_id),
                    Tenant.is_deleted.is_(False),
                    Tenant.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
    return row is not None and row.tenant_type == "platform"


class IdentityService:
    def __init__(self, db: AsyncSession, user: User):
        self.db, self.user = db, user

    async def tenant(self, target: str | None = None, *, lock: bool = False) -> Tenant:
        target = target or str(self.user.tenant_id)
        with bypass_tenant_filter():
            stmt = select(Tenant).where(
                Tenant.id == str(self.user.tenant_id), Tenant.is_deleted.is_(False)
            )
            actor_tenant = (await self.db.execute(stmt)).scalar_one_or_none()
            if actor_tenant is None or not actor_tenant.is_active:
                raise HTTPException(403, "当前租户未登记或已停用")
            if target != str(self.user.tenant_id):
                if (
                    self.user.role != UserRole.SYSTEM_ADMIN
                    or actor_tenant.tenant_type != "platform"
                ):
                    raise HTTPException(403, "无权管理其他租户")
            stmt = select(Tenant).where(Tenant.id == target, Tenant.is_deleted.is_(False))
            if lock:
                stmt = stmt.with_for_update().execution_options(populate_existing=True)
            row = (await self.db.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "租户不存在")
            if target != str(self.user.tenant_id):
                cursor: Tenant | None = row
                visited: set[str] = set()
                while (
                    cursor is not None
                    and cursor.parent_id
                    and cursor.id not in visited
                    and len(visited) < 20
                ):
                    visited.add(cursor.id)
                    if cursor.parent_id == actor_tenant.id:
                        return row
                    cursor = (
                        await self.db.execute(
                            select(Tenant).where(
                                Tenant.id == cursor.parent_id,
                                Tenant.is_deleted.is_(False),
                                Tenant.is_active.is_(True),
                            )
                        )
                    ).scalar_one_or_none()
                    if cursor is None:
                        break
                raise HTTPException(403, "租户不属于当前平台")
            return row

    async def list_tenants(self) -> list[dict[str, Any]]:
        actor = await self.tenant()
        if actor.tenant_type != "platform" or self.user.role != UserRole.SYSTEM_ADMIN:
            return [public_record(actor)]
        with bypass_tenant_filter():
            rows = (
                (
                    await self.db.execute(
                        select(Tenant).where(Tenant.is_deleted.is_(False)).order_by(Tenant.path)
                    )
                )
                .scalars()
                .all()
            )
        permitted = {str(actor.id)}
        for _ in range(20):
            permitted.update(str(row.id) for row in rows if str(row.parent_id) in permitted)
        return [public_record(row) for row in rows if str(row.id) in permitted]

    async def create_tenant(self, values: dict[str, Any]) -> Tenant:
        actor = await self.tenant()
        if actor.tenant_type != "platform" or self.user.role != UserRole.SYSTEM_ADMIN:
            raise HTTPException(403, "只有平台系统管理员可以登记租户")
        parent = await self.tenant(values["parent_id"], lock=True)
        if not parent.is_active or parent.tenant_type != TENANT_PARENTS[values["tenant_type"]]:
            raise HTTPException(422, "父租户类型或状态不符合要求")
        row_id = str(uuid.uuid4())
        row = Tenant(
            id=row_id,
            tenant_id=row_id,
            name=values["name"],
            tenant_type=values["tenant_type"],
            parent_id=parent.id,
            path=f"{parent.path.rstrip('/')}/{row_id}",
            is_active=True,
            config={"registration": {"status": "pending"}},
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def update_tenant(self, target: str, values: dict[str, Any]) -> Tenant:
        row = await self.tenant(target, lock=True)
        if values.get("is_active") is False and row.id == self.user.tenant_id:
            raise HTTPException(409, "不能停用当前登录租户")
        for key, value in values.items():
            if value is None:
                raise HTTPException(422, "配置值不能为空")
            setattr(row, key, value)
        await self.db.flush()
        return row

    async def orgs(self, target: str | None = None) -> list[OrgUnit]:
        tenant = await self.tenant(target)
        with bypass_tenant_filter():
            return list(
                (
                    await self.db.execute(
                        select(OrgUnit)
                        .where(OrgUnit.tenant_id == tenant.id, OrgUnit.is_deleted.is_(False))
                        .order_by(OrgUnit.path)
                    )
                )
                .scalars()
                .all()
            )

    @staticmethod
    def validate_tree(rows: list[OrgUnit]) -> None:
        by_id = {str(row.id): row for row in rows}
        roots = [row for row in rows if row.org_type == "school"]
        if len(roots) > 1:
            raise HTTPException(422, "同租户只能有一个学校根组织")
        for row in rows:
            parent = by_id.get(str(row.parent_id)) if row.parent_id else None
            if row.org_type not in ORG_PARENTS:
                raise HTTPException(422, "不支持的组织类型")
            if row.org_type == "school":
                if row.parent_id:
                    raise HTTPException(422, "学校根组织不能有父级")
            elif parent is None or parent.org_type not in ORG_PARENTS[row.org_type]:
                raise HTTPException(422, "父组织必须同租户且类型正确")
            if row.is_active and parent and not parent.is_active:
                raise HTTPException(422, "有效组织不能绑定停用父级；请先停用下级")
            current: OrgUnit | None = row
            visited: set[str] = set()
            path: list[str] = []
            while current:
                if str(current.id) in visited or len(visited) >= 20:
                    raise HTTPException(422, "组织关系存在循环或层级过深")
                visited.add(str(current.id))
                path.append(str(current.id))
                current = by_id.get(str(current.parent_id)) if current.parent_id else None
            row.path = "/" + "/".join(reversed(path))

    async def save_org(
        self, target: str | None, values: dict[str, Any], record_id: str | None = None
    ) -> OrgUnit:
        tenant = await self.tenant(target, lock=True)
        if not tenant.is_active:
            raise HTTPException(409, "停用租户不能修改组织")
        rows = await self.orgs(str(tenant.id))
        row = next((item for item in rows if item.id == record_id), None)
        if record_id and row is None:
            raise HTTPException(404, "组织不存在")
        if row is None:
            row = OrgUnit(id=str(uuid.uuid4()), tenant_id=tenant.id, path="/", is_active=True)
            rows.append(row)
            self.db.add(row)
        if values.get("is_active") is False and row.id == self.user.org_unit_id:
            raise HTTPException(409, "不能停用当前管理员所在组织")
        for key, value in values.items():
            # 上级组织可空（学校是根）；负责人姓名/职务/电话是选填联络信息，允许清空。
            if key not in {"parent_id", "leader_name", "leader_title", "leader_phone"} and value is None:
                raise HTTPException(422, "字段不能为空")
            setattr(row, key, value)
        self.validate_tree(rows)
        await self.db.flush()
        # 组织表单直接填的现任负责人，也要落到任职履历里，否则两个入口各写一套、互相打架
        await self.ensure_primary_term(str(tenant.id), row)
        await self.db.flush()
        return row

    async def ensure_primary_term(self, tenant_id: str, org: OrgUnit) -> None:
        """组织入口改写现任负责人时同步任职记录；没有在任记录就补一条"""
        if not org.leader_name:
            return
        with bypass_tenant_filter():
            current = await self.db.scalar(
                select(OrgLeaderTerm).where(
                    OrgLeaderTerm.tenant_id == tenant_id,
                    OrgLeaderTerm.org_unit_id == org.id,
                    OrgLeaderTerm.is_deleted.is_(False),
                    OrgLeaderTerm.is_primary.is_(True),
                    OrgLeaderTerm.ended_on.is_(None),
                )
            )
        if current:
            if (current.name, current.title, current.phone) != (
                org.leader_name,
                org.leader_title,
                org.leader_phone,
            ):
                current.name = org.leader_name
                current.title = org.leader_title or current.title
                current.phone = org.leader_phone
            return
        self.db.add(
            OrgLeaderTerm(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                org_unit_id=str(org.id),
                name=org.leader_name,
                title=org.leader_title or "负责人",
                phone=org.leader_phone,
                is_primary=True,
            )
        )

    async def org_leaders(
        self, target: str | None = None, org_unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        """任职记录：默认返回本租户全部，按组织、在任优先、任职时间倒序"""
        tenant = await self.tenant(target)
        conditions = [
            OrgLeaderTerm.tenant_id == tenant.id,
            OrgLeaderTerm.is_deleted.is_(False),
        ]
        if org_unit_id:
            conditions.append(OrgLeaderTerm.org_unit_id == org_unit_id)
        # 跨租户管理（平台管理员管下级学校）时，ORM 的自动租户过滤按"操作者租户"生效，
        # 会把目标租户的数据全部滤掉。租户隔离已由 where tenant_id == X 保证，这里显式绕过。
        with bypass_tenant_filter():
            rows = (
                await self.db.execute(
                    select(OrgLeaderTerm)
                    .where(*conditions)
                    .order_by(
                        OrgLeaderTerm.org_unit_id,
                        OrgLeaderTerm.ended_on.is_(None).desc(),
                        OrgLeaderTerm.is_primary.desc(),
                        OrgLeaderTerm.started_on.desc().nullslast(),
                        OrgLeaderTerm.created_at.desc(),
                    )
                )
            ).scalars()
            return [leader_payload(row) for row in rows]

    async def save_org_leader(
        self, target: str | None, values: dict[str, Any], record_id: str | None = None
    ) -> OrgLeaderTerm:
        """新增或修改一段任职。

        离任不删记录，只写 ``ended_on``；同一组织同时只能有一位在任主要负责人，
        新设主要负责人会把同组织其他人的 ``is_primary`` 置否，避免出现"两个书记"。
        """
        tenant = await self.tenant(target, lock=True)
        if not tenant.is_active:
            raise HTTPException(409, "停用租户不能修改任职记录")
        org_ids = {str(org.id) for org in await self.orgs(str(tenant.id))}
        row: OrgLeaderTerm | None = None
        if record_id:
            with bypass_tenant_filter():
                row = await self.db.scalar(
                    select(OrgLeaderTerm).where(
                        OrgLeaderTerm.id == record_id,
                        OrgLeaderTerm.tenant_id == tenant.id,
                        OrgLeaderTerm.is_deleted.is_(False),
                    )
                )
            if row is None:
                raise HTTPException(404, "任职记录不存在")
        org_unit_id = values.get("org_unit_id") or (row.org_unit_id if row else None)
        if org_unit_id not in org_ids:
            raise HTTPException(422, "任职组织不在当前租户内")
        if row is None:
            row = OrgLeaderTerm(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                org_unit_id=str(org_unit_id),
                is_primary=False,
            )
            self.db.add(row)
        optional = {"org_unit_id", "phone", "started_on", "ended_on", "is_primary", "remark"}
        for key, value in values.items():
            if key not in optional and value is None:
                raise HTTPException(422, "姓名与职务不能为空")
            setattr(row, key, value)
        if row.started_on and row.ended_on and row.ended_on < row.started_on:
            raise HTTPException(422, "离任日期不能早于任职日期")
        row.org_unit_id = str(org_unit_id)
        if row.is_primary and row.ended_on is None:
            with bypass_tenant_filter():
                others = (
                    await self.db.execute(
                        select(OrgLeaderTerm).where(
                            OrgLeaderTerm.tenant_id == tenant.id,
                            OrgLeaderTerm.org_unit_id == row.org_unit_id,
                            OrgLeaderTerm.is_deleted.is_(False),
                            OrgLeaderTerm.id != row.id,
                            OrgLeaderTerm.is_primary.is_(True),
                            OrgLeaderTerm.ended_on.is_(None),
                        )
                    )
                ).scalars()
                for other in others:
                    other.is_primary = False
        await self.db.flush()
        await self.sync_primary_leader(str(tenant.id), str(row.org_unit_id))
        await self.db.flush()
        return row

    async def replace_primary(self, target: str | None, values: dict[str, Any]) -> dict[str, Any]:
        """一键换人：现任主要负责人离任 + 新任一届，一个事务内完成。

        履历仍落两条记录（谁干到哪天、谁从哪天接），只是省掉"先离任再新增"两次提交，
        避免组织在两次提交之间短暂显示"无负责人"。
        """
        tenant = await self.tenant(target, lock=True)
        if not tenant.is_active:
            raise HTTPException(409, "停用租户不能修改任职记录")
        org_ids = {str(org.id) for org in await self.orgs(str(tenant.id))}
        org_unit_id = values.get("org_unit_id")
        if org_unit_id not in org_ids:
            raise HTTPException(422, "任职组织不在当前租户内")
        today = date.today()
        ended_on = values.get("ended_on_prev") or today
        with bypass_tenant_filter():
            current = await self.db.scalar(
                select(OrgLeaderTerm).where(
                    OrgLeaderTerm.tenant_id == tenant.id,
                    OrgLeaderTerm.org_unit_id == str(org_unit_id),
                    OrgLeaderTerm.is_deleted.is_(False),
                    OrgLeaderTerm.is_primary.is_(True),
                    OrgLeaderTerm.ended_on.is_(None),
                )
            )
        departed = None
        if current is not None:
            if current.started_on and ended_on < current.started_on:
                raise HTTPException(422, "离任日期不能早于原负责人任职日期")
            current.ended_on = ended_on
            departed = leader_payload(current)
            await self.db.flush()
        row = await self.save_org_leader(
            str(tenant.id),
            {
                "org_unit_id": str(org_unit_id),
                "name": values["name"],
                "title": values["title"],
                "phone": values.get("phone"),
                "started_on": values.get("started_on") or today,
                "is_primary": True,
                "remark": values.get("remark"),
            },
        )
        return {"departed": departed, "current": leader_payload(row)}

    async def sync_primary_leader(self, tenant_id: str, org_unit_id: str) -> None:
        """把该组织在任的主要负责人回写到 org_units 的现任快照；无人任则清空"""
        with bypass_tenant_filter():
            current = await self.db.scalar(
                select(OrgLeaderTerm)
                .where(
                    OrgLeaderTerm.tenant_id == tenant_id,
                    OrgLeaderTerm.org_unit_id == org_unit_id,
                    OrgLeaderTerm.is_deleted.is_(False),
                    OrgLeaderTerm.is_primary.is_(True),
                    OrgLeaderTerm.ended_on.is_(None),
                )
                .order_by(OrgLeaderTerm.started_on.desc().nullslast())
            )
            org = await self.db.scalar(
                select(OrgUnit).where(OrgUnit.id == org_unit_id, OrgUnit.tenant_id == tenant_id)
            )
        if org is None:
            return
        if current:
            org.leader_name = current.name
            org.leader_title = current.title
            org.leader_phone = current.phone
        else:
            org.leader_name = None
            org.leader_title = None
            org.leader_phone = None

    async def users(self, target: str | None = None) -> list[User]:
        tenant = await self.tenant(target)
        with bypass_tenant_filter():
            return list(
                (
                    await self.db.execute(
                        select(User)
                        .where(User.tenant_id == tenant.id, User.is_deleted.is_(False))
                        .order_by(User.username)
                    )
                )
                .scalars()
                .all()
            )

    async def save_user(
        self, target: str | None, values: dict[str, Any], record_id: str | None = None
    ) -> User:
        tenant = await self.tenant(target, lock=True)
        if not tenant.is_active:
            raise HTTPException(409, "停用租户不能修改用户")
        users = await self.users(str(tenant.id))
        row = next((item for item in users if item.id == record_id), None)
        if record_id and row is None:
            raise HTTPException(404, "用户不存在")
        if row is not None and row.role == UserRole.SYSTEM_ADMIN:
            actor = await self.tenant()
            if self.user.role != UserRole.SYSTEM_ADMIN or actor.tenant_type != "platform":
                raise HTTPException(403, "只有平台系统管理员能维护既有系统管理员")
        if row is None:
            row = User(id=str(uuid.uuid4()), tenant_id=tenant.id, is_active=True)
            self.db.add(row)
        if record_id == str(self.user.id) and (
            values.get("is_active") is False
            or ("role" in values and values["role"] != self.user.role)
        ):
            raise HTTPException(409, "不能停用或撤销自己的管理角色")
        values = dict(values)
        password = values.pop("password", None)
        for key, value in values.items():
            if key != "org_unit_id" and value is None:
                raise HTTPException(422, "字段不能为空")
            setattr(row, key, value)
        if password:
            row.password_hash = hash_password(password)
        if row.role == UserRole.SYSTEM_ADMIN:
            actor = await self.tenant()
            if self.user.role != UserRole.SYSTEM_ADMIN or actor.tenant_type != "platform":
                raise HTTPException(403, "不能授予或维护系统管理员角色")
        orgs = {str(item.id): item for item in await self.orgs(str(tenant.id))}
        org = orgs.get(str(row.org_unit_id))
        required_types = ROLE_ORG_TYPES.get(row.role)
        if row.role != UserRole.SYSTEM_ADMIN:
            if org is None or not org.is_active:
                raise HTTPException(422, "请选择当前租户内的有效组织")
            if required_types and org.org_type not in required_types:
                raise HTTPException(422, "所选角色与组织类型不匹配")
        admin_roles = {UserRole.SYSTEM_ADMIN, UserRole.SCHOOL_ADMIN}
        if record_id and any(item.role in admin_roles and item.is_active for item in users):
            remaining = [
                item
                for item in users
                if item.id != row.id and item.is_active and item.role in admin_roles
            ]
            if not remaining and (not row.is_active or row.role not in admin_roles):
                raise HTTPException(409, "不能移除租户最后一个管理员")
        await self.db.flush()
        return row
