"""组织可见范围（内存版）：角色范围、租户/状态过滤与环状关系终止。"""

import pytest

from app.core.tenant import TenantIsolationError
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.services.org_scope import visible_org_ids


def _org(
    org_id: str,
    tenant_id: str,
    org_type: str,
    parent_id: str | None = None,
    *,
    active: bool = True,
    deleted: bool = False,
) -> OrgUnit:
    return OrgUnit(
        id=org_id,
        tenant_id=tenant_id,
        org_type=org_type,
        parent_id=parent_id,
        path=org_id,
        name=org_id,
        is_active=active,
        is_deleted=deleted,
    )


def _user(role: UserRole, org_unit_id: str | None, tenant_id: str = "t1") -> User:
    return User(
        username="u",
        name="测试用户",
        password_hash="x",
        role=role,
        tenant_id=tenant_id,
        org_unit_id=org_unit_id,
    )


def _tree() -> dict[str, OrgUnit]:
    orgs = [
        _org("school-1", "t1", "school"),
        _org("dept-1", "t1", "department", "school-1"),
        _org("branch-1", "t1", "branch", "dept-1"),
        _org("branch-2", "t1", "branch", "dept-1"),
        _org("dept-2", "t1", "department", "school-1"),
        _org("school-2", "t1", "school"),
        _org("dept-3", "t1", "department", "school-2"),
        _org("school-x", "t2", "school"),
        _org("dept-deleted", "t1", "department", "school-1", deleted=True),
        _org("branch-inactive", "t1", "branch", "dept-1", active=False),
    ]
    return {org.id: org for org in orgs}


def test_system_admin_covers_tenant_valid_orgs() -> None:
    visible = visible_org_ids(_user(UserRole.SYSTEM_ADMIN, None), _tree())
    assert visible == {
        "school-1",
        "dept-1",
        "branch-1",
        "branch-2",
        "dept-2",
        "school-2",
        "dept-3",
    }


def test_school_admin_covers_root_and_descendants() -> None:
    visible = visible_org_ids(_user(UserRole.SCHOOL_ADMIN, "school-1"), _tree())
    assert visible == {"school-1", "dept-1", "branch-1", "branch-2", "dept-2"}


def test_department_admin_covers_self_and_descendants() -> None:
    visible = visible_org_ids(_user(UserRole.DEPARTMENT_ADMIN, "dept-1"), _tree())
    assert visible == {"dept-1", "branch-1", "branch-2"}


def test_branch_secretary_only_own_branch() -> None:
    visible = visible_org_ids(_user(UserRole.BRANCH_SECRETARY, "branch-1"), _tree())
    assert visible == {"branch-1"}


def test_self_scope_has_no_org_scope() -> None:
    assert visible_org_ids(_user(UserRole.MEMBER, "branch-1"), _tree()) == set()


def test_invalid_root_type_returns_empty() -> None:
    # 学校管理员的根组织必须是 school，指向 branch 视为无效，fail-closed 为空集。
    assert visible_org_ids(_user(UserRole.SCHOOL_ADMIN, "branch-1"), _tree()) == set()


def test_missing_tenant_raises() -> None:
    user = _user(UserRole.BRANCH_SECRETARY, "branch-1", tenant_id="")
    with pytest.raises(TenantIsolationError):
        visible_org_ids(user, _tree())


def test_cycle_terminates() -> None:
    tree = {
        "dept-a": _org("dept-a", "t1", "department", "dept-b"),
        "dept-b": _org("dept-b", "t1", "department", "dept-a"),
    }
    visible = visible_org_ids(_user(UserRole.DEPARTMENT_ADMIN, "dept-a"), tree)
    assert visible == {"dept-a", "dept-b"}
