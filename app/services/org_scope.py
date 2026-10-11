"""从登录角色和同租户组织树确定业务范围，不信任客户端组织名称。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import BS_ALL, BS_BRANCH, BS_DEPARTMENT, BS_SCHOOL, get_role_profile
from app.models.org import OrgUnit
from app.models.user import User


async def knowledge_org_ids(db: AsyncSession, user: User) -> list[str]:
    """登录请求和后台任务共用同租户的有效祖先资料范围。"""
    ids, seen = [], set()
    current = user.org_unit_id
    while current and current not in seen and len(seen) < 20:
        seen.add(current)
        org = (
            await db.execute(
                select(OrgUnit).where(
                    OrgUnit.id == current,
                    OrgUnit.tenant_id == str(user.tenant_id),
                    OrgUnit.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            break
        ids.append(str(org.id))
        current = org.parent_id
    return ids


def can_access_org_unit(user: User, org_id: str, organizations: dict[str, OrgUnit]) -> bool:
    """批量候选用户共用有效组织树，按同一业务范围检查目标组织。"""

    def valid(org: OrgUnit | None) -> bool:
        return org is not None and str(org.tenant_id) == str(user.tenant_id) and not org.is_deleted

    current = organizations.get(org_id)
    if not valid(current):
        return False
    scope = get_role_profile(user.role).business_scope
    if scope == BS_ALL:
        return True
    root = organizations.get(user.org_unit_id)
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
        current = organizations.get(current.parent_id)
        if not valid(current):
            return False
    return False


async def accessible_org_units(db: AsyncSession, user: User) -> list[OrgUnit]:
    """支部只含本支部；院系和学校包含本组织及有效后代，系统管理员限本租户。"""
    conditions = (OrgUnit.tenant_id == str(user.tenant_id), OrgUnit.is_deleted.is_(False))
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
