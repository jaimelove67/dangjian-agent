"""School notices, cross-role tasks, version guards and actual platform role decisions."""

from datetime import date, timedelta

import pytest

from app.api.v1 import school_business
from app.core.security import create_access_token
from app.models.meeting import ContentRevision
from app.models.member import MemberMaterial
from app.models.org import OrgUnit
from app.models.school_business import SchoolBusinessRecord
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.school_business_service import notice_today
from tests.integration.test_admin_accounts import workspace as account_workspace

workspace = account_workspace
BASE = "/api/v1/school/business"


def auth(user):
    return {
        "Authorization": "Bearer "
        + create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role)
    }


@pytest.fixture
def case(workspace):
    for table in [
        ContentRevision.__table__,
        SchoolBusinessRecord.__table__,
        MemberMaterial.__table__,
    ]:
        table.create(workspace.session.get_bind(), checkfirst=True)
    workspace.client.app.include_router(school_business.router, prefix="/api/v1")
    workspace.actor.role = UserRole.SCHOOL_ADMIN
    workspace.actor.org_unit_id = "school-a"
    workspace.session.get(OrgUnit, "branch-a").parent_id = "school-a"
    workspace.session.get(OrgUnit, "department-a").parent_id = "school-a"
    workspace.session.add(
        OrgUnit(
            id="outside-branch",
            tenant_id="account-tenant-a",
            name="同校无关支部",
            org_type="branch",
            parent_id="school-a",
            path="/school-a/outside",
        )
    )
    workspace.actors = {}
    for name, role, org, tenant in [
        ("organizer", UserRole.ORGANIZER, "branch-a", "account-tenant-a"),
        ("student", UserRole.MEMBER, "branch-a", "account-tenant-a"),
        ("outsider", UserRole.MEMBER, "outside-branch", "account-tenant-a"),
        ("foreign", UserRole.MEMBER, "branch-b", "account-tenant-b"),
    ]:
        user = User(
            id="school-test-" + name,
            tenant_id=tenant,
            username="school-test-" + name,
            name="合成" + name,
            role=role,
            org_unit_id=org,
            password_hash="unused",
            is_active=True,
        )
        workspace.session.add(user)
        workspace.actors[name] = user
    workspace.session.commit()
    return workspace


def post(case, path, body, actor=None):
    return case.client.post(BASE + path, json=body, headers=auth(actor or case.actor))


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def task(case, evidence=False, assignee="organizer"):
    return data(
        post(
            case,
            "/tasks",
            {
                "org_unit_id": "branch-a",
                "title": "合成学习督办任务",
                "category": "learning",
                "due_date": (date.today() - timedelta(days=1)).isoformat(),
                "requirements": "提交真实完成情况，由其他人员核验",
                "assignee_id": case.actors[assignee].id,
                "evidence_required": evidence,
            },
        )
    )


def step(case, row, action, actor=None, **body):
    return post(
        case,
        f"/records/{row['id']}/{action}",
        {"expected_revision": row["revision"], "reason": "合成联调办理依据", **body},
        actor,
    )


def test_task_submission_return_revise_review_archive_and_history(case):
    row = task(case)
    row = data(step(case, row, "publish"))
    assert row["status"] == "assigned" and row["overdue"]
    assert step(case, row, "complete", report="非指定人员提交").status_code == 403
    submitted = data(
        step(case, row, "complete", case.actors["organizer"], report="已按实际任务完成登记")
    )
    assert (
        step(case, submitted, "review", case.actors["organizer"], decision="approved").status_code
        == 403
    )
    returned = data(step(case, submitted, "review", decision="rejected"))
    assert (
        step(case, row, "complete", case.actors["organizer"], report="使用旧版本提交").status_code
        == 409
    )
    submitted = data(
        step(case, returned, "complete", case.actors["organizer"], report="已补充核验结果")
    )
    approved = data(step(case, submitted, "review", decision="approved"))
    assert step(case, approved, "archive").status_code == 403
    tenant = case.session.get(Tenant, case.actor.tenant_id)
    tenant.config = {
        "electronic_archive": {
            "enabled": True,
            "revision": 1,
            "confirmed_by": case.actor.id,
            "confirmed_at": "2026-01-01",
            "evidence": "合成学校电子效力确认",
        }
    }
    case.session.commit()
    archived = data(step(case, approved, "archive"))
    assert archived["status"] == "archived" and archived["archived_at"]
    assert (
        step(case, archived, "complete", case.actors["organizer"], report="归档后篡改").status_code
        == 409
    )
    result = data(case.client.get(BASE + f"/records/{row['id']}", headers=auth(case.actor)))
    assert len(result["history"]) == archived["revision"]
    assert (
        result["reviewed_by"] == case.actor.id
        and result["submitted_by"] == case.actors["organizer"].id
    )


@pytest.mark.parametrize("actor", ["student", "organizer", "outsider", "foreign"])
def test_school_create_and_tenant_boundaries(case, actor):
    candidate = case.actors[actor]
    assert (
        post(
            case,
            "/notices",
            {"org_unit_id": "school-a", "title": "不应创建", "content": "无权限发布"},
            candidate,
        ).status_code
        == 403
    )
    row = task(case)
    if actor in {"outsider", "foreign"}:
        assert (
            case.client.get(BASE + f"/records/{row['id']}", headers=auth(candidate)).status_code
            == 404
        )
    other_tenant = "account-tenant-a" if actor == "foreign" else "account-tenant-b"
    assert (
        case.client.get(
            BASE + "/records?kind=task&tenant_id=" + other_tenant, headers=auth(candidate)
        ).status_code
        == 403
    )


def test_notice_draft_hidden_and_published_ancestor_visible(case):
    row = data(
        post(
            case,
            "/notices",
            {"org_unit_id": "school-a", "title": "合成通知", "content": "仅供合成学校查看"},
        )
    )
    assert not data(
        case.client.get(BASE + "/records?kind=notice", headers=auth(case.actors["student"]))
    )["items"]
    row = data(step(case, row, "publish"))
    visible = data(
        case.client.get(BASE + "/records?kind=notice", headers=auth(case.actors["student"]))
    )["items"]
    assert len(visible) == 1 and visible[0]["body"]["content"] == "仅供合成学校查看"
    assert not data(
        case.client.get(BASE + "/records?kind=notice", headers=auth(case.actors["foreign"]))
    )["items"]
    assert step(case, row, "publish").status_code == 409


def test_legacy_notice_creation_retains_defaults_and_real_organization_names(case):
    row = data(
        post(
            case,
            "/notices",
            {"org_unit_id": "branch-a", "title": "兼容通知", "content": "保留原有创建方式"},
        )
    )
    assert row["body"]["category"] == "notice"
    assert row["body"]["starts_on"] is None
    assert row["body"]["evidence"] == []
    assert row["body"]["organization_name"] == case.session.get(OrgUnit, "branch-a").name
    assert row["body"]["issuer"] == case.session.get(OrgUnit, "school-a").name


@pytest.mark.parametrize("offset", [-2, 2])
def test_notice_dates_gate_both_list_and_direct_detail_but_preserve_management(case, offset):
    day = (notice_today() + timedelta(days=offset)).isoformat()
    row = data(
        post(
            case,
            "/notices",
            {
                "org_unit_id": "school-a",
                "title": "限定期限公示",
                "content": "未开始及结束后不可通过直达地址查看",
                "category": "publicity",
                "starts_on": day,
                "expires_on": day,
            },
        )
    )
    row = data(step(case, row, "publish"))
    student = auth(case.actors["student"])
    assert not data(case.client.get(BASE + "/records?kind=notice", headers=student))["items"]
    assert case.client.get(BASE + f"/records/{row['id']}", headers=student).status_code == 404
    assert data(case.client.get(BASE + "/records?kind=notice", headers=auth(case.actor)))["items"]
    assert (
        data(case.client.get(BASE + f"/records/{row['id']}", headers=auth(case.actor)))["id"]
        == row["id"]
    )


def test_publicity_dates_are_inclusive_and_organization_scope_is_preserved(case):
    day = notice_today().isoformat()
    row = data(
        post(
            case,
            "/notices",
            {
                "org_unit_id": "branch-a",
                "title": "当日支部公示",
                "content": "仅授权支部当日查看",
                "category": "publicity",
                "starts_on": day,
                "expires_on": day,
            },
        )
    )
    assert (
        case.client.get(
            BASE + f"/records/{row['id']}", headers=auth(case.actors["student"])
        ).status_code
        == 404
    )
    row = data(step(case, row, "publish"))
    assert (
        len(
            data(
                case.client.get(BASE + "/records?kind=notice", headers=auth(case.actors["student"]))
            )["items"]
        )
        == 1
    )
    for actor in ["outsider", "foreign"]:
        assert not data(
            case.client.get(BASE + "/records?kind=notice", headers=auth(case.actors[actor]))
        )["items"]
        assert (
            case.client.get(
                BASE + f"/records/{row['id']}", headers=auth(case.actors[actor])
            ).status_code
            == 404
        )
    assert case.client.get(BASE + f"/records/{row['id']}").status_code == 401


@pytest.mark.parametrize(
    "fields",
    [
        {"category": "publicity"},
        {"category": "publicity", "starts_on": "2026-10-28"},
        {"category": "publicity", "expires_on": "2026-10-30"},
        {"starts_on": "2026-10-30", "expires_on": "2026-10-28"},
        {"category": "forged-category"},
    ],
)
def test_notice_rejects_missing_or_reversed_publication_periods(case, fields):
    response = post(
        case,
        "/notices",
        {"org_unit_id": "school-a", "title": "期限校验", "content": "不得接受错误期限", **fields},
    )
    assert response.status_code == 422


def test_required_material_and_private_material_ownership(case):
    row = data(step(case, task(case, True, "student"), "publish"))
    assert step(case, row, "complete", case.actors["student"], report="缺失佐证").status_code == 422
    assert (
        step(
            case,
            row,
            "complete",
            case.actors["student"],
            report="伪造原件编号",
            material_ids=["unknown"],
        ).status_code
        == 403
    )
    case.session.add(
        MemberMaterial(
            id="private-original",
            tenant_id=case.actor.tenant_id,
            user_id=case.actors["student"].id,
            profile_id="synthetic-profile",
            org_unit_id="branch-a",
            content_sha256="a" * 64,
            title="合成原件",
            file_version="v1",
        )
    )
    case.session.commit()
    submitted = data(
        step(
            case,
            row,
            "complete",
            case.actors["student"],
            report="提交已存原件",
            material_ids=["private-original"],
        )
    )
    assert submitted["body"]["materials"][0]["sha256"] == "a" * 64


def test_rules_optimistic_version_and_read_only_for_regular_members(case):
    current = data(case.client.get(BASE + "/rules", headers=auth(case.actor)))
    payload = {
        "year": date.today().year,
        "review_days": 3,
        "reminder_days": 2,
        "development_materials": "合成制度要求",
        "archive_requirements": "单独确认归档",
        "reason": "合成制度修订",
        "expected_revision": current["revision"],
    }
    assert (
        case.client.put(
            BASE + "/rules", json=payload, headers=auth(case.actors["student"])
        ).status_code
        == 403
    )
    saved = data(case.client.put(BASE + "/rules", json=payload, headers=auth(case.actor)))
    assert saved["revision"] == current["revision"] + 1
    assert (
        case.client.put(BASE + "/rules", json=payload, headers=auth(case.actor)).status_code == 409
    )


def test_permission_application_requires_platform_and_applies_real_guarded_account_edit(case):
    tenant = case.session.get(Tenant, case.actor.tenant_id)
    tenant.parent_id = "permission-platform"
    platform = Tenant(
        id="permission-platform",
        tenant_id="permission-platform",
        name="合成平台",
        tenant_type="platform",
        path="/permission-platform",
    )
    admin = User(
        id="permission-admin",
        tenant_id=platform.id,
        username="permission-admin",
        name="合成平台管理员",
        role=UserRole.SYSTEM_ADMIN,
        password_hash="unused",
        is_active=True,
    )
    case.session.add_all([platform, admin])
    case.session.commit()
    payload = {
        "user_id": case.actors["organizer"].id,
        "role": "branch_secretary",
        "org_unit_id": "branch-a",
        "reason": "合成岗位调整审批依据",
    }
    row = data(post(case, "/permission-requests", payload))
    assert row["title"] == f"{case.actors['organizer'].name} · 业务角色申请"
    assert step(case, row, "review", decision="approved").status_code == 403
    approved = data(step(case, row, "review", admin, decision="approved"))
    case.session.expire_all()
    assert approved["status"] == "approved"
    assert case.session.get(User, payload["user_id"]).role == UserRole.BRANCH_SECRETARY
    assert step(case, row, "review", admin, decision="approved").status_code == 409
    assert (
        post(case, "/permission-requests", {**payload, "role": "system_admin"}).status_code == 403
    )
