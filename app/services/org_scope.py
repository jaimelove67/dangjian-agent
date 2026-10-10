"""从登录角色和同租户组织树确定业务范围，不信任客户端组织名称。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import BS_ALL, BS_BRANCH, BS_DEPARTMENT, BS_SCHOOL, get_role_profile
from app.models.org import OrgUnit
from app.models.user import User


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
