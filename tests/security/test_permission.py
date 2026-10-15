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

    def test_member_has_base_view_and_self_service_permissions(self):
        assert get_role_profile(UserRole.MEMBER).permissions == frozenset(
            {
                Permission.QA_ASK,
                Permission.KNOWLEDGE_QUERY,
                Permission.SELF_QUERY,
                Permission.MATERIAL_SUBMIT,
            }
        )

    def test_applicant_permissions_are_subset_of_member(self):
        """不变式：基层角色必须单调包含，不允许出现"低角色看得到、高角色看不到"。"""
        applicant = get_role_profile(UserRole.APPLICANT).permissions
        member = get_role_profile(UserRole.MEMBER).permissions
        assert applicant <= member
        assert applicant == frozenset(
            {
                Permission.QA_ASK,
                Permission.KNOWLEDGE_QUERY,
                Permission.SELF_QUERY,
                Permission.MATERIAL_SUBMIT,
            }
        )

    def test_base_roles_can_read_knowledge_directory(self):
        for role in (UserRole.MEMBER, UserRole.APPLICANT):
            assert has_permission(role, Permission.KNOWLEDGE_QUERY)

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

    def test_config_and_audit_are_tenant_administrator_permissions(self):
        for permission in (Permission.CONFIG_MANAGE, Permission.AUDIT_QUERY):
            assert has_permission(UserRole.SYSTEM_ADMIN, permission)
            assert has_permission(UserRole.SCHOOL_ADMIN, permission)
            assert not has_permission(UserRole.DEPARTMENT_ADMIN, permission)
            assert not has_permission(UserRole.MEMBER, permission)


class TestDataScope:
    """角色 + 数据范围双层模型"""

    def test_knowledge_visibility(self):
        assert can_access_knowledge_scope(UserRole.APPLICANT, "public")
        # 需求文档 §4.1：申请人仅公开制度问答。该边界比党员更窄是规定动作，
        # 不是遗漏；不要为了"菜单与权限一致"而放宽。
        assert not can_access_knowledge_scope(UserRole.APPLICANT, "school")
        assert can_access_knowledge_scope(UserRole.MEMBER, "school")
        assert not can_access_knowledge_scope(UserRole.MEMBER, "department")
        assert can_access_knowledge_scope(UserRole.BRANCH_SECRETARY, "branch")

    def test_applicant_knowledge_scope_stays_public_only(self):
        """申请人可见范围必须严格窄于党员：这是需求 §4.1 的保密边界，不能被'同权'改写。"""
        applicant = get_role_profile(UserRole.APPLICANT)
        member = get_role_profile(UserRole.MEMBER)
        assert applicant.knowledge_scopes == frozenset({"public"})
        assert applicant.knowledge_scopes < member.knowledge_scopes
        assert resolve_data_level(UserRole.APPLICANT) == DataLevel.PUBLIC

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
