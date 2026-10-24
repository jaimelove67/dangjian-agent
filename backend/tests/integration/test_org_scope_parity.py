"""可见范围两条路径一致性：``visible_org_units`` 必须与 ``accessible_org_units`` 同口径。

A2 只把三个业务服务的范围计算切到 ``visible_org_ids`` 快照口径，其余调用点仍走
递归 CTE。为防止两条路径漂移，这里用真实 PostgreSQL 组织树逐角色对比。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.tenant import TenantIsolationError
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.org_scope import (
    accessible_org_units,
    load_org_tree,
    visible_org_ids,
    visible_org_units,
)

pytestmark = pytest.mark.integration

TENANT = "org-scope-tenant"
OTHER_TENANT = "org-scope-other"
TREE = [
    ("school-1", "school", None),
    ("dept-1", "department", "school-1"),
    ("branch-1", "branch", "dept-1"),
    ("branch-2", "branch", "dept-1"),
    ("dept-2", "department", "school-1"),
    ("school-2", "school", None),
    ("dept-3", "department", "school-2"),
]
EXCLUDED = {"branch-off", "other-school"}


@pytest.fixture(scope="module")
def org_scope_url():
    name = "party_org_scope_" + uuid.uuid4().hex[:12]
    admin = make_url(settings.DATABASE_URL).set(database="postgres")
    target = admin.set(database=name)

    async def provision(create: bool) -> None:
        engine = create_async_engine(admin, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'{"CREATE" if create else "DROP"} DATABASE "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(provision(True))

    async def migrate() -> None:
        engine = create_async_engine(target, poolclass=NullPool)
        try:
            async with engine.begin() as conn:

                def upgrade(sync):
                    config = Config("alembic.ini")
                    config.attributes["connection"] = sync
                    command.upgrade(config, "head")

                await conn.run_sync(upgrade)
        finally:
            await engine.dispose()

    async def seed() -> None:
        """一棵含停用节点与他租户节点的组织树，全模块只建一次。"""
        engine = create_async_engine(target, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                db.add(
                    Tenant(
                        id=TENANT,
                        tenant_id=TENANT,
                        name="范围一致性",
                        tenant_type="school",
                        path=TENANT,
                        config={},
                    )
                )
                for org_id, kind, parent in TREE:
                    db.add(
                        OrgUnit(
                            id=org_id,
                            tenant_id=TENANT,
                            name=org_id,
                            org_type=kind,
                            parent_id=parent,
                            path=org_id,
                            is_active=True,
                        )
                    )
                # 停用支部：两条路径都必须排除。
                db.add(
                    OrgUnit(
                        id="branch-off",
                        tenant_id=TENANT,
                        name="停用支部",
                        org_type="branch",
                        parent_id="dept-1",
                        path="branch-off",
                        is_active=False,
                    )
                )
                # 他租户节点：即便挂在本租户父节点下也不得进入范围。
                db.add(
                    OrgUnit(
                        id="other-school",
                        tenant_id=OTHER_TENANT,
                        name="他租户学校",
                        org_type="school",
                        parent_id="school-1",
                        path="other-school",
                        is_active=True,
                    )
                )
                await db.commit()
        finally:
            await engine.dispose()

    try:
        asyncio.run(migrate())
        asyncio.run(seed())
        yield target
    finally:
        asyncio.run(provision(False))


@pytest.fixture
async def org_db(org_scope_url):
    """每个用例独立会话读取同一份已建好的组织树。"""
    engine = create_async_engine(org_scope_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db
    finally:
        await engine.dispose()


def _user(role: UserRole, org_unit_id: str | None, tenant_id: str = TENANT) -> User:
    return User(
        username="parity-" + role.value,
        name="范围一致性用户",
        password_hash="x",
        role=role,
        tenant_id=tenant_id,
        org_unit_id=org_unit_id,
    )


CASES = [
    (UserRole.SYSTEM_ADMIN, None),
    (UserRole.SYSTEM_ADMIN, "dept-1"),
    (UserRole.SCHOOL_ADMIN, "school-1"),
    (UserRole.DEPARTMENT_ADMIN, "dept-1"),
    (UserRole.BRANCH_SECRETARY, "branch-1"),
    (UserRole.MEMBER, "branch-1"),
    # 根组织类型与角色范围不匹配：两条路径都必须 fail-closed 为空。
    (UserRole.SCHOOL_ADMIN, "branch-1"),
]


@pytest.mark.parametrize(("role", "org_unit_id"), CASES)
async def test_snapshot_and_cte_scope_agree(org_db, role, org_unit_id):
    user = _user(role, org_unit_id)
    legacy = {str(org.id) for org in await accessible_org_units(org_db, user)}
    snapshot = {str(org.id) for org in await visible_org_units(org_db, user)}
    assert snapshot == legacy
    assert not (snapshot & EXCLUDED)
    # 纯函数与数据库入口也必须同口径。
    tree = await load_org_tree(org_db, TENANT)
    assert visible_org_ids(user, tree) == snapshot


async def test_scope_order_matches_cte(org_db):
    """列表顺序保持 ``path, id`` 稳定，避免调用方依赖顺序时行为变化。"""
    user = _user(UserRole.SYSTEM_ADMIN, None)
    legacy = [org.id for org in await accessible_org_units(org_db, user)]
    snapshot = [org.id for org in await visible_org_units(org_db, user)]
    assert snapshot == legacy


async def test_missing_tenant_fails_closed(org_db):
    user = _user(UserRole.BRANCH_SECRETARY, "branch-1", tenant_id="")
    with pytest.raises(TenantIsolationError):
        await visible_org_units(org_db, user)
    with pytest.raises(TenantIsolationError):
        await load_org_tree(org_db, "")
    # 报错不得污染会话：同一会话随后仍能正常读取组织树。
    assert "school-1" in await load_org_tree(org_db, TENANT)
