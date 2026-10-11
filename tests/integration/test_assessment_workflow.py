"""随机独立PostgreSQL库中的真实HTTP闭环；合成样本不代替学校人工验收。"""

import asyncio
import io
import json
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import date

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_user
from app.main import app
from app.models.assessment import (
    AssessmentArchive,
    AssessmentIndicator,
    AssessmentReminder,
    AssessmentRun,
)
from app.models.audit import AuditLog
from app.models.knowledge import KnowledgeDoc
from app.models.meeting import MeetingRecord
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.study import StudyPlan, StudyPlanItem
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.meeting_service import extract_minutes
from app.services.study_materials import selected_sources
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

YEAR = date.today().year
TODAY = date.today().isoformat()


@pytest.fixture(scope="module")
def assessment_url(storage_url):
    async def migrate():
        engine = create_async_engine(storage_url, poolclass=NullPool, hide_parameters=True)
        try:
            async with engine.begin() as connection:

                def upgrade(sync_connection):
                    config = Config()
                    config.set_main_option("script_location", "migrations")
                    config.attributes["connection"] = sync_connection
                    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
                    command.upgrade(config, "006")
                    sync_connection.execute(
                        KnowledgeDoc.__table__.insert().values(
                            id="assessment-upgrade-document",
                            tenant_id="assessment-upgrade-tenant",
                            doc_id="ASSESSMENT-UPGRADE-PRESERVE",
                            title="合成迁移保留文档",
                            file_name="synthetic.txt",
                            issuer="合成机构",
                            level="school",
                            visibility="school",
                            security_level="public",
                            effective_date=date(2000, 1, 1),
                            status="effective",
                        )
                    )
                    query = text("SELECT * FROM knowledge_docs ORDER BY id")
                    before = sync_connection.execute(query).mappings().all()
                    command.upgrade(config, "head")
                    assert sync_connection.execute(query).mappings().all() == before
                    command.downgrade(config, "006")
                    assert sync_connection.execute(query).mappings().all() == before
                    assert sync_connection.scalar(
                        text("SELECT to_regclass('assessment_runs') IS NULL")
                    )
                    command.upgrade(config, "head")
                    assert sync_connection.execute(query).mappings().all() == before

                await connection.run_sync(upgrade)
                assert await connection.scalar(
                    text("SELECT to_regclass('assessment_runs') IS NOT NULL")
                )
        finally:
            await engine.dispose()

    asyncio.run(migrate())
    return storage_url


@pytest.fixture
async def case(assessment_url):
    tenant = str(uuid.uuid4())
    school, dept, branch, other = [str(uuid.uuid4()) for _ in range(4)]
    actors = {}
    engine = create_async_engine(assessment_url, poolclass=NullPool, hide_parameters=True)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(
            Tenant(
                id=tenant,
                tenant_id=tenant,
                name="合成学校",
                tenant_type="school",
                path=tenant,
                config={},
            )
        )
        for org_id, kind, parent in [
            (school, "school", None),
            (dept, "department", school),
            (branch, "branch", dept),
            (other, "branch", dept),
        ]:
            db.add(
                OrgUnit(
                    id=org_id,
                    tenant_id=tenant,
                    name="合成组织" + kind,
                    org_type=kind,
                    parent_id=parent,
                    path=org_id,
                )
            )
        for name, role, org in [
            ("school", UserRole.SCHOOL_ADMIN, school),
            ("reviewer", UserRole.SCHOOL_ADMIN, school),
            ("department", UserRole.DEPARTMENT_ADMIN, dept),
            ("branch", UserRole.BRANCH_SECRETARY, branch),
            ("organizer", UserRole.ORGANIZER, branch),
            ("member", UserRole.MEMBER, branch),
        ]:
            actor = User(
                id=str(uuid.uuid4()),
                tenant_id=tenant,
                username=name + uuid.uuid4().hex[:12],
                name="合成" + name,
                password_hash="synthetic-password-hash",
                role=role,
                org_unit_id=org,
            )
            actor.knowledge_org_ids = [org, dept, school]
            db.add(actor)
            actors[name] = actor
        db.add(
            MemberProfile(
                id=str(uuid.uuid4()),
                tenant_id=tenant,
                name="合成人员",
                org_name="合成支部",
                org_unit_id=branch,
                current_stage="activist",
                stage_joined_on=date(YEAR, 1, 1),
                materials=["材料名称"],
            )
        )
        document = KnowledgeDoc(
            id=str(uuid.uuid4()),
            tenant_id=tenant,
            doc_id="synthetic-doc-" + uuid.uuid4().hex,
            title="合成制度",
            file_name="fixture.txt",
            issuer="合成单位",
            level="school",
            visibility="school",
            security_level="public",
            effective_date=date(YEAR, 1, 1),
            status="effective",
            doc_metadata={"content_revision": 1},
        )
        db.add(document)
        await db.commit()
    await engine.dispose()
    return {
        "url": assessment_url,
        "tenant": tenant,
        "school": school,
        "department": dept,
        "branch": branch,
        "other": other,
        "actors": actors,
        "doc_id": document.doc_id,
        "doc_pk": document.id,
    }


@asynccontextmanager
async def client(case, actor="school"):
    engine = create_async_engine(case["url"], poolclass=NullPool, hide_parameters=True)
    current = case["actors"][actor]
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:

            async def database():
                yield db

            app.dependency_overrides[get_db] = database
            app.dependency_overrides[get_current_user] = lambda: current
            with tenant_context(current.tenant_id, user_id=current.id):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as http:
                    yield http, db
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def indicator_body(case, **changes):
    return {
        "org_unit_id": case["school"],
        "year": YEAR,
        "code": "COUNT",
        "name": "合成组织数",
        "requirement": "统计当前授权组织",
        "source": "organizations",
        "target": 1,
        "period_start": f"{YEAR}-01-01",
        "period_end": f"{YEAR}-12-31",
        "confirmed": True,
        "confirmation_note": "仅为合成自动化样本，非学校真实指标",
        **changes,
    }


def scope_body(case, org="branch"):
    return {"org_unit_id": case[org], "year": YEAR}


async def add_rule(case, **changes):
    async with client(case) as (http, _):
        response = await http.post(
            "/api/v1/assessment/indicators", json=indicator_body(case, **changes)
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]


async def recalculate(case, actor="branch", org="branch"):
    async with client(case, actor) as (http, _):
        response = await http.post("/api/v1/assessment/recalculate", json=scope_body(case, org))
        assert response.status_code == 200, response.text
        return response.json()["data"]


async def workspace(http, case, org="branch"):
    response = await http.get("/api/v1/assessment/workspace", params=scope_body(case, org))
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def mutate_document(case, **changes):
    async with client(case) as (_, db):
        document = await db.get(KnowledgeDoc, case["doc_pk"])
        for key, value in changes.items():
            setattr(document, key, value)
        await db.commit()


async def test_rule_versions_are_school_owned_immutable_and_concurrent_checked(case):
    first = await add_rule(case)
    async with client(case, "department") as (http, _):
        assert (
            await http.post("/api/v1/assessment/indicators", json=indicator_body(case))
        ).status_code == 403
    second = await add_rule(case, expected_version=1, target=2)
    assert first["version"] == 1 and second["version"] == 2
    async with client(case) as (http, db):
        conflict = await http.post(
            "/api/v1/assessment/indicators", json=indicator_body(case, expected_version=1)
        )
        assert conflict.status_code == 409
        stored = (
            (await db.execute(select(AssessmentIndicator).order_by(AssessmentIndicator.version)))
            .scalars()
            .all()
        )
        assert [(rule.version, rule.target) for rule in stored] == [(1, "1.0"), (2, "2.0")]
        assert (
            await db.scalar(select(func.count(AuditLog.id)).where(AuditLog.result == "failed")) >= 1
        )


async def test_repeat_calculation_is_idempotent_and_drilldown_is_authorized(case):
    await add_rule(case)
    first, second = await recalculate(case), await recalculate(case)
    assert first["id"] == second["id"] and first["fingerprint"] == second["fingerprint"]
    assert first["results"][0]["actual"] == 1
    assert first["results"][0]["sources"][0]["record_id"] == case["branch"]
    async with client(case, "branch") as (http, db):
        assert await db.scalar(select(func.count(AssessmentRun.id))) == 1
        data = await workspace(http, case)
        assert not data["needs_recalculation"]
        source = await http.get(
            f"/api/v1/assessment/sources/organizations/{case['branch']}", params=scope_body(case)
        )
        assert source.status_code == 200
        denied = await http.get(
            f"/api/v1/assessment/sources/organizations/{case['other']}", params=scope_body(case)
        )
        assert denied.status_code == 404


async def test_ordinary_user_and_other_organization_cannot_use_workbench(case):
    async with client(case, "member") as (http, _):
        assert (await http.get("/api/v1/assessment/org-units")).status_code == 403
        assert (
            await http.get("/api/v1/assessment/workspace", params=scope_body(case))
        ).status_code == 403
    async with client(case, "branch") as (http, _):
        assert (
            await http.get("/api/v1/assessment/workspace", params=scope_body(case, "other"))
        ).status_code == 403
        assert (
            await http.get(
                "/api/v1/assessment/workspace",
                params={"org_unit_id": str(uuid.uuid4()), "year": YEAR},
            )
        ).status_code == 403


async def test_school_total_does_not_complete_child_task_and_updates_invalidate_snapshot(case):
    await add_rule(case, source="members", target=1)
    async with client(case) as (http, _):
        body = {
            **scope_body(case, "other"),
            "indicator_code": "COUNT",
            "title": "合成子支部任务",
            "owner_id": case["actors"]["school"].id,
            "due_date": TODAY,
            "declared_progress": 100,
        }
        created = await http.post("/api/v1/assessment/tasks", json=body)
        assert created.status_code == 200, created.text
        data = await workspace(http, case, "school")
        assert data["results"][0]["actual"] == 1
        assert data["tasks"][0]["complete"] is False
        assert data["tasks"][0]["missing"]
    run = await recalculate(case, "school", "school")
    async with client(case) as (http, db):
        member = (await db.execute(select(MemberProfile))).scalar_one()
        member.org_unit_id = case["other"]
        await db.commit()
        data = await workspace(http, case, "school")
        assert data["needs_recalculation"] and data["tasks"][0]["complete"]
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/export")).status_code == 409


@pytest.mark.parametrize("change", ["content", "deleted", "classified", "abolished"])
async def test_evidence_source_changes_are_missing_and_old_export_is_blocked(case, change):
    await add_rule(case, required_evidence=["制度佐证"])
    async with client(case, "branch") as (http, _):
        response = await http.post(
            "/api/v1/assessment/evidence",
            json={
                **scope_body(case),
                "indicator_code": "COUNT",
                "requirement_key": "制度佐证",
                "doc_id": case["doc_id"],
            },
        )
        assert response.status_code == 200, response.text
        evidence = response.json()["data"]
        own = await http.post(
            f"/api/v1/assessment/evidence/{evidence['id']}/review",
            json={"status": "approved", "opinion": "合成核查", "expected_revision": 1},
        )
        assert own.status_code == 403
    async with client(case, "reviewer") as (http, _):
        review = await http.post(
            f"/api/v1/assessment/evidence/{evidence['id']}/review",
            json={"status": "approved", "opinion": "已核查合成源文件", "expected_revision": 1},
        )
        assert review.status_code == 200, review.text
    run = await recalculate(case)
    assert run["results"][0]["satisfied"] is True
    changes = {
        "content": {"doc_metadata": {"content_revision": 2}},
        "deleted": {"is_deleted": True},
        "classified": {"security_level": "classified"},
        "abolished": {"status": "abolished"},
    }[change]
    await mutate_document(case, **changes)
    async with client(case, "branch") as (http, _):
        data = await workspace(http, case)
        assert data["needs_recalculation"] and data["results"][0]["satisfied"] is None
        assert data["results"][0]["missing"]
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/export")).status_code == 409
        if change in {"deleted", "classified"}:
            view = data["evidence"][0]
            assert "doc_id" not in view and "title" not in view
            assert case["doc_id"] not in json.dumps(data["results"], ensure_ascii=False)
            historical = await http.get(f"/api/v1/assessment/runs/{run['id']}")
            assert historical.status_code == 200
            old = historical.json()["data"]
            assert old["stale"] and old["results"][0]["actual"] is None
            assert case["doc_id"] not in json.dumps(old, ensure_ascii=False)


async def test_manual_value_requires_basis_other_reviewer_and_resets_on_edit(case):
    await add_rule(
        case, source="manual", formula="sum", source_options={"measure": "sum"}, target=2
    )
    body = {
        **scope_body(case),
        "indicator_code": "COUNT",
        "title": "合成创新项",
        "owner_id": case["actors"]["branch"].id,
        "due_date": TODAY,
        "completed_on": TODAY,
        "declared_progress": 100,
        "manual_value": 2,
        "basis": "合成原始项目记录编号M-1",
    }
    async with client(case, "branch") as (http, _):
        response = await http.post("/api/v1/assessment/tasks", json=body)
        assert response.status_code == 200, response.text
        task = response.json()["data"]
        pending = await workspace(http, case)
        assert pending["results"][0]["actual"] is None and not pending["tasks"][0]["complete"]
    async with client(case, "reviewer") as (http, _):
        reviewed = await http.post(
            f"/api/v1/assessment/tasks/{task['id']}/review",
            json={"status": "approved", "opinion": "已核查合成项目", "expected_revision": 1},
        )
        assert reviewed.status_code == 200
    async with client(case, "branch") as (http, _):
        formal = await workspace(http, case)
        assert formal["results"][0]["actual"] == 2 and formal["tasks"][0]["complete"]
        assert (
            await http.put(
                f"/api/v1/assessment/tasks/{task['id']}", json={**body, "expected_revision": 1}
            )
        ).status_code == 409
        edited = await http.put(
            f"/api/v1/assessment/tasks/{task['id']}",
            json={**body, "manual_value": 3, "expected_revision": 2},
        )
        assert edited.status_code == 200
        assert edited.json()["data"]["review_status"] == "pending"
        assert (await workspace(http, case))["results"][0]["actual"] is None


async def test_plan_versions_reminder_processing_and_csv_export_are_audited(case):
    await add_rule(case, name="=HYPERLINK(合成)", target=2)
    async with client(case, "branch") as (http, _):
        response = await http.post(
            "/api/v1/assessment/tasks",
            json={
                **scope_body(case),
                "indicator_code": "COUNT",
                "title": "合成任务",
                "owner_id": case["actors"]["branch"].id,
                "due_date": TODAY,
            },
        )
        assert response.status_code == 200
    run = await recalculate(case)
    async with client(case, "branch") as (http, db):
        data = await workspace(http, case)
        reminder = next(item for item in data["reminders"] if item["status"] == "open")
        before = await db.scalar(select(func.count(AssessmentReminder.id)))
        await http.post("/api/v1/assessment/reminders/sync", json=scope_body(case))
        assert await db.scalar(select(func.count(AssessmentReminder.id))) == before
        handled = await http.post(
            f"/api/v1/assessment/reminders/{reminder['id']}/handle", json={"note": "合成处理结果"}
        )
        assert handled.status_code == 200 and handled.json()["data"]["status"] == "handled"
        plan1 = await http.post("/api/v1/assessment/plans", json={"run_id": run["id"]})
        assert plan1.status_code == 200, plan1.text
        assert "参考草案" in plan1.json()["data"]["content"]
        plan2 = await http.post(
            "/api/v1/assessment/plans",
            json={
                "run_id": run["id"],
                "expected_version": 1,
                "content": "人工修订：时间安排待组织研究",
            },
        )
        assert plan2.status_code == 200 and plan2.json()["data"]["version"] == 2
        assert plan2.json()["data"]["review_status"] == "pending"
        exported = await http.post(f"/api/v1/assessment/runs/{run['id']}/export")
        assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert {
                "indicators.csv",
                "tasks.csv",
                "evidence.json",
                "assessment.json",
                "plan.txt",
            } <= set(archive.namelist())
            assert "'=HYPERLINK" in archive.read("indicators.csv").decode("utf-8-sig")
            assert "待人工审核" in archive.read("assessment.json").decode()
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "assessment_export_manifest"
                )
            )
            == 1
        )


async def test_archiving_requires_shared_school_confirmation_and_human_review(case):
    await add_rule(case)
    run = await recalculate(case)
    async with client(case, "branch") as (http, _):
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/archive")).status_code == 403
    async with client(case, "reviewer") as (http, _):
        reviewed = await http.post(
            f"/api/v1/assessment/runs/{run['id']}/review",
            json={
                "status": "approved",
                "opinion": "核查合成来源与指标规则",
                "expected_revision": 1,
            },
        )
        assert reviewed.status_code == 200, reviewed.text
    async with client(case) as (http, _):
        policy = await http.put(
            "/api/v1/assessment/policy",
            json={
                "org_unit_id": case["school"],
                "archive_enabled": True,
                "confirmation_note": "仅为合成测试组织确认，不是正式学校准入",
            },
        )
        assert policy.status_code == 200, policy.text
    async with client(case, "branch") as (http, db):
        archived = await http.post(f"/api/v1/assessment/runs/{run['id']}/archive")
        assert archived.status_code == 200, archived.text
        assert archived.json()["data"]["policy_version"] == 1
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/archive")).json()["data"][
            "id"
        ] == archived.json()["data"]["id"]
        assert await db.scalar(select(func.count(AssessmentArchive.id))) == 1
    async with client(case) as (http, _):
        revoke = await http.put(
            "/api/v1/assessment/policy",
            json={
                "org_unit_id": case["school"],
                "archive_enabled": False,
                "expected_version": 1,
                "expected_archive_version": 1,
                "confirmation_note": "合成撤销",
            },
        )
        assert revoke.status_code == 200
    async with client(case, "branch") as (http, _):
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/archive")).status_code == 403


async def test_source_deletion_cross_year_and_member_materials_remain_explicitly_unknown(case):
    await add_rule(case, source="members")
    first = await recalculate(case)
    assert first["results"][0]["actual"] == 1
    async with client(case) as (_, db):
        member = (await db.execute(select(MemberProfile))).scalar_one()
        member.stage_joined_on = date(YEAR - 1, 12, 31)
        await db.commit()
    async with client(case, "branch") as (http, _):
        result = (await workspace(http, case))["results"][0]
        assert result["actual"] is None and result["missing"]
    await add_rule(
        case,
        expected_version=1,
        source="member_materials",
        formula="percentage",
        source_options={"measure": "material_rate"},
    )
    async with client(case, "branch") as (http, _):
        result = (await workspace(http, case))["results"][0]
        assert result["actual"] is None and result["satisfied"] is None


async def test_cross_tenant_run_is_inaccessible(case):
    await add_rule(case)
    run = await recalculate(case)
    foreign = User(
        id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        username="foreign-synthetic",
        role=UserRole.SYSTEM_ADMIN,
    )
    case["actors"]["foreign"] = foreign
    async with client(case, "foreign") as (http, _):
        assert (await http.get(f"/api/v1/assessment/runs/{run['id']}")).status_code == 404
        assert (await http.post(f"/api/v1/assessment/runs/{run['id']}/export")).status_code == 404


async def test_learning_reuses_real_shared_records_and_source_permission_changes(case):
    activity_id, plan_id, item_id = [str(uuid.uuid4()) for _ in range(3)]
    transcript = "学习要点：合成政策学习。\n讨论共识：合成共识。\n工作要求：合成任务。"
    async with client(case) as (_, db):
        sources = await selected_sources(
            db, case["actors"]["school"], case["department"], [case["doc_id"]]
        )
        db.add(
            StudyPlan(
                id=plan_id,
                tenant_id=case["tenant"],
                org_unit_id=case["department"],
                year=YEAR,
                title="合成年度学习计划",
                priorities=["合成重点"],
                responsible="合成负责人",
                source_doc_ids=[case["doc_id"]],
                sources=sources,
                review_status="approved",
                revision=1,
            )
        )
        db.add(
            MeetingRecord(
                id=activity_id,
                tenant_id=case["tenant"],
                org_unit_id=case["department"],
                activity_type="center_group",
                title="合成学习活动",
                scheduled_on=date.today(),
                held_on=date.today(),
                host="合成主持人",
                participants=[
                    {"participant_id": "p-1", "name": "合成甲", "attended": True},
                    {"participant_id": "p-2", "name": "合成乙", "attended": False},
                ],
                transcript=transcript,
                minutes=extract_minutes(transcript),
                sources=sources,
                source_doc_ids=[case["doc_id"]],
                review_status="approved",
                revision=1,
                context={"plan_id": plan_id, "item_id": item_id, "plan_revision": 1},
            )
        )
        await db.flush()
        db.add(
            StudyPlanItem(
                id=item_id,
                tenant_id=case["tenant"],
                plan_id=plan_id,
                topic="合成主题",
                scheduled_on=date.today(),
                responsible="合成负责人",
                sources=sources,
                source_doc_ids=[case["doc_id"]],
                meeting_record_id=activity_id,
            )
        )
        await db.commit()
    await add_rule(case, code="STUDY_COUNT", source="studies", target=1)
    await add_rule(
        case,
        code="STUDY_RATE",
        source="studies",
        formula="percentage",
        source_options={"measure": "attendance_rate"},
        target=50,
    )
    first = await recalculate(case, "school", "department")
    values = {result["code"]: result for result in first["results"]}
    assert values["STUDY_COUNT"]["actual"] == 1
    assert values["STUDY_RATE"]["actual"] == 50
    assert values["STUDY_COUNT"]["sources"][0]["record_id"] == activity_id
    assert values["STUDY_COUNT"]["satisfied"] is True
    assert (await recalculate(case, "school", "department"))["id"] == first["id"]
    async with client(case) as (_, db):
        assert await db.scalar(select(func.count(MeetingRecord.id))) == 1
    await mutate_document(case, security_level="classified")
    async with client(case) as (http, _):
        data = await workspace(http, case, "department")
        assert data["needs_recalculation"]
        assert all(result["actual"] is None and result["missing"] for result in data["results"])
        assert (await http.post(f"/api/v1/assessment/runs/{first['id']}/export")).status_code == 409


async def test_shared_meeting_records_are_counted_once_and_review_reset_invalidates(case):
    activity_id = str(uuid.uuid4())
    async with client(case, "branch") as (_, db):
        sources = await selected_sources(
            db, case["actors"]["branch"], case["branch"], [case["doc_id"]]
        )
        transcript = "学习要点：合成记录。\n讨论共识：合成共识。\n工作要求：合成要求。"
        db.add(
            MeetingRecord(
                id=activity_id,
                tenant_id=case["tenant"],
                org_unit_id=case["branch"],
                activity_type="branch_meeting",
                title="合成支部活动",
                scheduled_on=date.today(),
                held_on=date.today(),
                host="合成主持",
                participants=[{"participant_id": "m-1", "name": "合成参加者", "attended": True}],
                transcript=transcript,
                minutes=extract_minutes(transcript),
                sources=sources,
                source_doc_ids=[case["doc_id"]],
                review_status="approved",
            )
        )
        await db.commit()
    await add_rule(case, source="meetings")
    first = await recalculate(case)
    assert first["results"][0]["actual"] == 1 and first["results"][0]["satisfied"] is True
    assert (await recalculate(case))["id"] == first["id"]
    async with client(case, "branch") as (_, db):
        record = await db.get(MeetingRecord, activity_id)
        record.review_status = "draft"
        record.revision += 1
        await db.commit()
    async with client(case, "branch") as (http, _):
        data = await workspace(http, case)
        assert data["needs_recalculation"] and data["results"][0]["satisfied"] is None


async def test_learning_custom_period_ignores_unreviewed_activities_outside_period(case):
    today = date.today()
    outside = date(YEAR, 1, 1) if today != date(YEAR, 1, 1) else date(YEAR, 12, 31)
    approved_id = str(uuid.uuid4())
    async with client(case) as (_, db):
        sources = await selected_sources(
            db, case["actors"]["school"], case["department"], [case["doc_id"]]
        )
        transcript = "学习要点：合成学习。\n讨论共识：合成共识。\n工作要求：合成要求。"
        for held, status, record_id in [
            (today, "approved", approved_id),
            (outside, "draft", str(uuid.uuid4())),
        ]:
            db.add(
                MeetingRecord(
                    id=record_id,
                    tenant_id=case["tenant"],
                    org_unit_id=case["department"],
                    activity_type="center_group",
                    title="合成期间验证",
                    scheduled_on=held,
                    held_on=held,
                    host="合成主持",
                    participants=[{"participant_id": "period-user", "attended": True}],
                    transcript=transcript,
                    minutes=extract_minutes(transcript),
                    sources=sources,
                    review_status=status,
                )
            )
        await db.commit()
    await add_rule(case, source="studies", period_start=TODAY, period_end=TODAY)
    run = await recalculate(case, "school", "department")
    result = run["results"][0]
    assert result["actual"] == 1 and result["satisfied"] is True
    assert result["missing"] == []
    assert [item["record_id"] for item in result["sources"]] == [approved_id]


async def test_system_admin_cannot_bind_another_branchs_private_evidence(case):
    await add_rule(case, required_evidence=["合成佐证"])
    actor = User(
        id=str(uuid.uuid4()),
        tenant_id=case["tenant"],
        username="assessment-system-" + uuid.uuid4().hex,
        name="合成系统管理员",
        password_hash="synthetic-hash",
        role=UserRole.SYSTEM_ADMIN,
        org_unit_id=case["school"],
    )
    case["actors"]["system"] = actor
    async with client(case) as (_, db):
        db.add(actor)
        document = await db.get(KnowledgeDoc, case["doc_pk"])
        document.visibility = "branch"
        document.doc_metadata = {"org_unit_id": case["other"], "content_revision": 1}
        await db.commit()
    async with client(case, "system") as (http, _):
        response = await http.post(
            "/api/v1/assessment/evidence",
            json={
                **scope_body(case),
                "indicator_code": "COUNT",
                "requirement_key": "合成佐证",
                "doc_id": case["doc_id"],
            },
        )
        assert response.status_code == 404


async def test_background_scan_retries_deduplicates_and_records_handling(case, monkeypatch):
    from app.services import assessment_scheduler

    await add_rule(case, target=2)
    async with client(case, "branch") as (http, _):
        created = await http.post(
            "/api/v1/assessment/tasks",
            json={
                **scope_body(case),
                "indicator_code": "COUNT",
                "title": "合成扫描任务",
                "owner_id": case["actors"]["branch"].id,
                "due_date": TODAY,
            },
        )
        assert created.status_code == 200
    engine = create_async_engine(case["url"], poolclass=NullPool, hide_parameters=True)
    try:
        monkeypatch.setattr(
            assessment_scheduler,
            "async_session_maker",
            lambda: AsyncSession(engine, expire_on_commit=False),
        )
        assert await assessment_scheduler.scan_assessment_reminders() >= 1
        assert await assessment_scheduler.scan_assessment_reminders() >= 1
        async with client(case, "branch") as (http, db):
            assert await db.scalar(select(func.count(AssessmentReminder.id))) == 1
            assert (await workspace(http, case))["reminders"][0]["status"] == "open"
    finally:
        await engine.dispose()
