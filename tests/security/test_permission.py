"""权限与数据范围安全测试（对应框架文档 8.3 / 9.1）"""
import pytest

from app.core.constants import DataLevel
from app.core.security import (
    Permission,
    can_access_business_scope,
    can_access_knowledge_scope,
    get_role_profile,
    has_permission,
    resolve_data_level,
)
from app.models.user import UserRole

pytestmark = pytest.mark.security


class TestInterfacePermissions:
    """接口权限矩阵"""

    def test_qa_allowed_for_all_roles(self):
        for role in UserRole:
            assert has_permission(role, Permission.QA_ASK)

    def test_knowledge_manage_requires_department_or_above(self):
        assert has_permission(UserRole.SYSTEM_ADMIN, Permission.KNOWLEDGE_MANAGE)
        assert has_permission(UserRole.SCHOOL_ADMIN, Permission.KNOWLEDGE_MANAGE)
        assert has_permission(UserRole.DEPARTMENT_ADMIN, Permission.KNOWLEDGE_MANAGE)
        assert not has_permission(UserRole.BRANCH_SECRETARY, Permission.KNOWLEDGE_MANAGE)
        assert not has_permission(UserRole.MEMBER, Permission.KNOWLEDGE_MANAGE)

    def test_stage_transition_requires_branch_or_above(self):
        assert has_permission(UserRole.BRANCH_SECRETARY, Permission.STAGE_TRANSITION)
        assert has_permission(UserRole.ORGANIZER, Permission.STAGE_TRANSITION)
        assert not has_permission(UserRole.MEMBER, Permission.STAGE_TRANSITION)
        assert not has_permission(UserRole.APPLICANT, Permission.STAGE_TRANSITION)

    def test_config_and_audit_are_system_admin_only(self):
        for permission in (Permission.CONFIG_MANAGE, Permission.AUDIT_QUERY):
            assert has_permission(UserRole.SYSTEM_ADMIN, permission)
            assert not has_permission(UserRole.SCHOOL_ADMIN, permission)
            assert not has_permission(UserRole.DEPARTMENT_ADMIN, permission)


class TestDataScope:
    """角色 + 数据范围双层模型"""

    def test_knowledge_visibility(self):
        assert can_access_knowledge_scope(UserRole.APPLICANT, "public")
        assert not can_access_knowledge_scope(UserRole.APPLICANT, "school")
        assert can_access_knowledge_scope(UserRole.MEMBER, "school")
        assert not can_access_knowledge_scope(UserRole.MEMBER, "department")
        assert can_access_knowledge_scope(UserRole.BRANCH_SECRETARY, "branch")

    def test_business_scope_hierarchy(self):
        assert can_access_business_scope(UserRole.MEMBER, "self")
        assert not can_access_business_scope(UserRole.MEMBER, "branch")
        assert can_access_business_scope(UserRole.BRANCH_SECRETARY, "branch")
        assert not can_access_business_scope(UserRole.BRANCH_SECRETARY, "department")
        assert can_access_business_scope(UserRole.DEPARTMENT_ADMIN, "branch")
        assert not can_access_business_scope(UserRole.DEPARTMENT_ADMIN, "school")
        assert can_access_business_scope(UserRole.SCHOOL_ADMIN, "department")
        assert can_access_business_scope(UserRole.SYSTEM_ADMIN, "school")


class TestDataLevel:
    """数据级别由角色推导"""

    def test_levels_derived_from_role(self):
        assert resolve_data_level(UserRole.APPLICANT) == DataLevel.PUBLIC
        assert resolve_data_level(UserRole.MEMBER) == DataLevel.INTERNAL
        assert resolve_data_level(UserRole.BRANCH_SECRETARY) == DataLevel.SENSITIVE
        assert resolve_data_level(UserRole.SYSTEM_ADMIN) == DataLevel.SENSITIVE

    def test_unknown_role_defaults_to_minimal(self):
        profile = get_role_profile("unknown-role")  # type: ignore[arg-type]
        assert profile.role == UserRole.APPLICANT
