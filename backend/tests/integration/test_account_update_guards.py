"""Account editing must preserve the last school admin and linked member organization."""

import pytest

from app.api.v1 import governance
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration.test_admin_accounts import workspace as account_workspace

workspace = account_workspace


def register_updates(workspace):
    workspace.client.app.include_router(governance.router, prefix="/api/v1")


@pytest.mark.parametrize("changes", [{"is_active": False}, {"role": "organizer"}])
def test_platform_cannot_remove_last_effective_school_administrator(workspace, changes):
    register_updates(workspace)
    parent = workspace.session.get(Tenant, "account-tenant-a")
    parent.tenant_type = "platform"
    workspace.session.get(Tenant, "account-tenant-b").parent_id = parent.id
    workspace.session.add(
        OrgUnit(
            id="school-b",
            tenant_id="account-tenant-b",
            name="合成学校B",
            org_type="school",
            path="/school-b",
        )
    )
    workspace.session.add(
        User(
            id="sole-admin",
            tenant_id="account-tenant-b",
            username="sole-admin",
            name="唯一学校管理员",
            password_hash="synthetic-hash",
            role=UserRole.SCHOOL_ADMIN,
            org_unit_id="school-b",
            is_active=True,
        )
    )
    workspace.session.commit()
    if "role" in changes:
        changes = {**changes, "org_unit_id": "branch-b"}
    response = workspace.client.patch(
        "/api/v1/admin/users/sole-admin?tenant_id=account-tenant-b",
        headers=workspace.headers,
        json=changes,
    )
    assert response.status_code == 409
    workspace.session.expire_all()
    saved = workspace.session.get(User, "sole-admin")
    assert saved.is_active and saved.role == UserRole.SCHOOL_ADMIN


def test_linked_account_cannot_move_ahead_of_its_personal_archive(workspace):
    register_updates(workspace)
    MemberProfile.__table__.create(workspace.session.get_bind())
    workspace.actor.role = UserRole.SCHOOL_ADMIN
    workspace.actor.org_unit_id = "school-a"
    workspace.session.add(
        OrgUnit(
            id="another-a",
            tenant_id="account-tenant-a",
            name="同校另一支部",
            org_type="branch",
            path="/another-a",
        )
    )
    workspace.session.add(
        User(
            id="linked-account",
            tenant_id="account-tenant-a",
            username="linked-account",
            name="已关联党员",
            password_hash="synthetic-hash",
            role=UserRole.MEMBER,
            org_unit_id="branch-a",
            is_active=True,
        )
    )
    workspace.session.flush()
    workspace.session.add(
        MemberProfile(
            id="linked-profile",
            tenant_id="account-tenant-a",
            user_id="linked-account",
            name="已关联党员",
            org_name="合成支部A",
            org_unit_id="branch-a",
        )
    )
    workspace.session.commit()
    endpoint = "/api/v1/admin/users/linked-account"
    changes = {"org_unit_id": "another-a"}
    response = workspace.client.patch(endpoint, headers=workspace.headers, json=changes)
    assert response.status_code == 409
    workspace.session.expire_all()
    assert workspace.session.get(User, "linked-account").org_unit_id == "branch-a"
    profile = workspace.session.get(MemberProfile, "linked-profile")
    profile.org_unit_id = "another-a"
    workspace.session.commit()
    response = workspace.client.patch(endpoint, headers=workspace.headers, json=changes)
    assert response.status_code == 200
