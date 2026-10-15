"""从登录角色和同租户组织树确定业务范围，不信任客户端组织名称。"""

import logging
from collections.abc import Mapping
from typing import TypeGuard

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import BS_ALL, BS_BRANCH, BS_DEPARTMENT, BS_SCHOOL, get_role_profile
from app.core.tenant import TenantIsolationError
from app.models.org import OrgUnit
from app.models.user import User

logger = logging.getLogger(__name__)


async def knowledge_org_ids(db: AsyncSession, user: User) -> list[str]:
    """登录请求和后台任务共用同租户的有效祖先资料范围。"""
    ids: list[str] = []
    seen: set[str] = set()
    current = user.org_unit_id
    while current and current not in seen and len(seen) < 20:
        seen.add(current)
        org = (
            await db.execute(
                select(OrgUnit).where(
                    OrgUnit.id == current,
                    OrgUnit.tenant_id == str(user.tenant_id),
                    OrgUnit.is_deleted.is_(False),
                    OrgUnit.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            return []
        ids.append(str(org.id))
        current = org.parent_id
    return [] if current else ids


def can_access_org_unit(user: User, org_id: str, organizations: dict[str, OrgUnit]) -> bool:
    """批量候选用户共用有效组织树，按同一业务范围检查目标组织。"""

    def valid(org: OrgUnit | None) -> TypeGuard[OrgUnit]:
        return (
            org is not None
            and str(org.tenant_id) == str(user.tenant_id)
            and not org.is_deleted
            and org.is_active is not False
        )

    current = organizations.get(org_id)
    if not valid(current):
        return False
    scope = get_role_profile(user.role).business_scope
    if scope == BS_ALL:
        return True
    root = organizations.get(user.org_unit_id or "")
    expected_type = {BS_BRANCH: "branch", BS_DEPARTMENT: "department", BS_SCHOOL: "school"}.get(
        scope
    )
    if not valid(root) or not expected_type or root.org_type != expected_type:
        return False
    seen: set[str] = set()
    while current.id not in seen:
        if current.id == root.id:
            return True
        if scope == BS_BRANCH:
            return False
        seen.add(current.id)
        current = organizations.get(current.parent_id or "")
        if not valid(current):
            return False
    return False


def visible_org_ids(user: User, organizations: Mapping[str, OrgUnit]) -> set[str]:
    """在组织树快照中计算登录用户可见的组织 ID 集合。

    复用与 ``accessible_org_units`` 相同的业务范围语义，但只读入一棵已加载的
    组织树（键为组织 ID），不访问数据库，便于批量场景复用同一份快照。
    范围规则：系统管理员覆盖本租户全部有效组织；学校/院系管理员覆盖其根组织的
    有效后代；支部只含本支部；其余范围（如 self）没有组织级可见范围。

    Args:
        user: 登录用户，``role`` 与 ``org_unit_id`` 决定业务范围。
        organizations: 组织树快照，键为组织 ID，值为 ``OrgUnit``。

    Returns:
        可见组织 ID 字符串集合；无有效根组织时为空集。

    Raises:
        TenantIsolationError: 用户缺少租户 ID、无法安全限定范围时（fail-closed）。

    Note:
        - 只纳入同租户、未删除且启用的节点，跨租户节点静默排除。
        - 环状或异常父子关系由 ``visible`` 去重终止，不会死循环。

    Example:
        >>> tree = {str(org.id): org for org in orgs}
        >>> visible_org_ids(user, tree)
        {'org_001', 'org_002'}
    """
    tenant_id = str(user.tenant_id) if user.tenant_id else ""
    if not tenant_id:
        raise TenantIsolationError("缺少租户 ID，无法计算可见组织范围")

    def _valid(org: OrgUnit | None) -> TypeGuard[OrgUnit]:
        """节点必须同租户、未删除且启用，才可进入可见范围。"""
        return (
            org is not None
            and str(org.tenant_id) == tenant_id
            and not org.is_deleted
            and org.is_active is not False
        )

    scope = get_role_profile(user.role).business_scope

    if scope == BS_ALL:
        return {str(org.id) for org in organizations.values() if _valid(org)}

    expected_type = {BS_BRANCH: "branch", BS_DEPARTMENT: "department", BS_SCHOOL: "school"}.get(
        scope
    )
    if expected_type is None:
        return set()

    root = organizations.get(user.org_unit_id or "")
    if not _valid(root) or root.org_type != expected_type:
        logger.warning("visible_org_ids_invalid_root user_id=%s", user.id)
        return set()

    visible: set[str] = {str(root.id)}
    if scope == BS_BRANCH:
        return visible

    children: dict[str, list[str]] = {}
    for org_id, org in organizations.items():
        parent_id = org.parent_id
        if _valid(org) and parent_id:
            children.setdefault(parent_id, []).append(org_id)

    frontier = [str(root.id)]
    while frontier:
        for child_id in children.get(frontier.pop(), []):
            if child_id not in visible:
                visible.add(child_id)
                frontier.append(child_id)
    return visible


async def load_org_tree(db: AsyncSession, tenant_id: str) -> dict[str, OrgUnit]:
    """读取本租户全部有效组织节点，作为内存范围计算的同一份快照。

    按 ``path``、``id`` 排序后写入字典，调用方按插入顺序得到与原
    ``accessible_org_units`` 一致的稳定顺序。

    Args:
        db: 当前请求或后台任务的数据库会话。
        tenant_id: 租户 ID，只能来自登录态；为空时 fail-closed。

    Returns:
        组织树快照，键为组织 ID 字符串，值为 ``OrgUnit``。

    Raises:
        TenantIsolationError: 缺少租户 ID 时（fail-closed）。
    """
    if not tenant_id:
        raise TenantIsolationError("缺少租户 ID，无法读取组织树")
    rows = (
        (
            await db.execute(
                select(OrgUnit)
                .where(
                    OrgUnit.tenant_id == str(tenant_id),
                    OrgUnit.is_deleted.is_(False),
                    OrgUnit.is_active.is_(True),
                )
                .order_by(OrgUnit.path, OrgUnit.id)
            )
        )
        .scalars()
        .all()
    )
    return {str(org.id): org for org in rows}


async def visible_org_units(db: AsyncSession, user: User) -> list[OrgUnit]:
    """数据库入口：取一次组织树快照后交给 ``visible_org_ids`` 计算可见范围。

    与 ``accessible_org_units`` 结果等价，但范围规则只在 ``visible_org_ids``
    一处维护，便于单测守住口径。缺租户 ID 时同样 fail-closed。

    Args:
        db: 当前请求或后台任务的数据库会话。
        user: 登录用户，``role`` 与 ``org_unit_id`` 决定业务范围。

    Returns:
        可见组织列表，顺序与 ``load_org_tree`` 快照一致。

    Raises:
        TenantIsolationError: 用户缺少租户 ID、无法安全限定范围时（fail-closed）。
    """
    tree = await load_org_tree(db, str(user.tenant_id) if user.tenant_id else "")
    visible = visible_org_ids(user, tree)
    return [org for org in tree.values() if str(org.id) in visible]


async def accessible_org_units(db: AsyncSession, user: User) -> list[OrgUnit]:
    """支部只含本支部；院系和学校包含本组织及有效后代，系统管理员限本租户。"""
    conditions = (
        OrgUnit.tenant_id == str(user.tenant_id),
        OrgUnit.is_deleted.is_(False),
        OrgUnit.is_active.is_(True),
    )
    scope = get_role_profile(user.role).business_scope
    statement = select(OrgUnit).where(*conditions)
    if scope != BS_ALL:
        org_type = {BS_BRANCH: "branch", BS_DEPARTMENT: "department", BS_SCHOOL: "school"}.get(
            scope
        )
        if not org_type or not user.org_unit_id:
            return []
        root = select(OrgUnit.id).where(
            *conditions, OrgUnit.id == user.org_unit_id, OrgUnit.org_type == org_type
        )
        if scope == BS_BRANCH:
            statement = statement.where(OrgUnit.id.in_(root))
        else:
            tree = root.cte("business_org_tree", recursive=True)
            # UNION 去重使异常环状关系也能终止；不通过已删除或其他租户的节点。
            tree = tree.union(
                select(OrgUnit.id).join(tree, OrgUnit.parent_id == tree.c.id).where(*conditions)
            )
            statement = statement.where(OrgUnit.id.in_(select(tree.c.id)))
    return list((await db.execute(statement.order_by(OrgUnit.path, OrgUnit.id))).scalars().all())
