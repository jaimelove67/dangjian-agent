"""角色与权限上下文的单元测试（不连库）。"""

from app.models.user import User, UserRole
from app.services.qa_role_context import build_role_context


def _user(role: UserRole, name: str = "测试用户") -> User:
    return User(
        id=f"user-{role.value}",
        username=f"user-{role.value}",
        name=name,
        tenant_id="qa-tenant",
        role=role,
        is_active=True,
    )


def test_member_context_carries_role_scope_and_boundaries():
    context = build_role_context(_user(UserRole.MEMBER, "张三"))

    assert context.role == "member"
    assert context.role_label == "普通党员"
    assert context.business_scope == "self"
    assert context.business_scope_label == "本人"
    assert context.knowledge_scope_labels == ("公开制度", "学校制度")
    assert "角色：普通党员" in context.text
    assert "不查看其他党员档案" in context.text
    # 角色上下文不能夹带姓名等个人信息
    assert "张三" not in context.text
    assert context.as_dict()["knowledge_scopes"] == ["public", "school"]


def test_applicant_context_keeps_public_knowledge_only():
    context = build_role_context(_user(UserRole.APPLICANT))

    assert context.knowledge_scope_labels == ("公开制度",)
    assert context.business_scope == "self"
    assert "不查看学校、院系、支部内部制度" in context.text
    assert "主题党日报名不向申请人开放" in context.text


def test_organizer_cannot_replace_branch_secretary():
    context = build_role_context(_user(UserRole.ORGANIZER))

    assert context.role_label == "组织员"
    assert "创建和维护会议草稿" in context.text
    assert "不能代替支部书记提交、审核或归档会议" in context.text


def test_school_admin_context_is_school_scoped_and_keeps_business_boundaries():
    context = build_role_context(_user(UserRole.SCHOOL_ADMIN))

    assert context.business_scope == "school"
    assert context.business_scope_label == "本校"
    assert context.knowledge_scope_labels == ("公开制度", "学校制度")
    assert "审核、退回、督办和归档" in context.text
    assert "不直接创建支部会议" in context.text


def test_platform_admin_stays_out_of_school_business_decisions():
    context = build_role_context(_user(UserRole.SYSTEM_ADMIN))

    assert context.business_scope == "all"
    assert context.business_scope_label == "平台范围"
    assert "不办理学校三会一课、党员发展、材料审核和学校公示发布" in context.text
