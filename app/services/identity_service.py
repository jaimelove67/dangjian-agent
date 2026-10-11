"""租户和身份管理。平台管理员跨校授权必须由真实平台租户验证。"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.tenant import bypass_tenant_filter
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole

TENANT_PARENTS = {"school": "platform", "department": "school", "branch": "department"}
ORG_PARENTS = {"school": set(), "department": {"school"}, "branch": {"school", "department"}}


def public_record(row: Any) -> dict[str, Any]:
    fields = {
        Tenant: ("id", "name", "tenant_type", "parent_id", "is_active", "config_version"),
        OrgUnit: ("id", "name", "org_type", "parent_id", "is_active", "path"),
        User: ("id", "username", "name", "role", "org_unit_id", "is_active"),
    }[type(row)]
    return {key: getattr(row, key) for key in fields}


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
            if key != "parent_id" and value is None:
                raise HTTPException(422, "字段不能为空")
            setattr(row, key, value)
        self.validate_tree(rows)
        await self.db.flush()
        return row

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
        required_type = {
            UserRole.SCHOOL_ADMIN: {"school"},
            UserRole.DEPARTMENT_ADMIN: {"department"},
            UserRole.BRANCH_SECRETARY: {"branch"},
            UserRole.ORGANIZER: {"branch", "department"},
        }.get(row.role)
        if row.role != UserRole.SYSTEM_ADMIN and (
            org is None
            or not org.is_active
            or (required_type is not None and org.org_type not in required_type)
        ):
            raise HTTPException(422, "用户必须绑定有效组织，管理角色须匹配组织类型")
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
