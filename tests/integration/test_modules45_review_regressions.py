"""审查反例：真实 HTTP/独立库验证权限、历史、提醒和查询规模。"""

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.assessment import AssessmentReminder
from app.models.audit import AuditLog
from app.models.meeting import ContentRevision
from app.models.user import User, UserRole
from app.services.assessment_service import AssessmentService
from tests.integration import test_assessment_workflow as fixtures

storage_url = fixtures.storage_url
assessment_url = fixtures.assessment_url
case = fixtures.case


async def create_task(case, *, manual=False):
    """通过真实接口登记本支部责任任务。"""
    body = {
        **fixtures.scope_body(case),
        "indicator_code": "COUNT",
        "title": "合成审查任务",
        "owner_id": case["actors"]["branch"].id,
        "due_date": fixtures.TODAY,
    }
    if manual:
        body.update(
            manual_value=2,
            completed_on=fixtures.TODAY,
            declared_progress=100,
            basis="合成人工依据原文，仅保存在业务修订中",
        )
    async with fixtures.client(case, "branch") as (http, _):
        response = await http.post("/api/v1/assessment/tasks", json=body)
        assert response.status_code == 200, response.text
        return response.json()["data"], body


async def approve_evidence(case, reviewer="reviewer"):
    """由另一位真实授权审核用户核验已登记的合成佐证。"""
    async with fixtures.client(case, "branch") as (http, _):
        response = await http.post(
            "/api/v1/assessment/evidence",
            json={
                **fixtures.scope_body(case),
                "indicator_code": "COUNT",
                "requirement_key": "制度佐证",
                "doc_id": case["doc_id"],
            },
        )
        assert response.status_code == 200, response.text
        evidence = response.json()["data"]
    async with fixtures.client(case, reviewer) as (http, _):
        response = await http.post(
            f"/api/v1/assessment/evidence/{evidence['id']}/review",
            json={
                "status": "approved",
                "opinion": "合成佐证独立核查",
                "expected_revision": evidence["revision"],
            },
        )
        assert response.status_code == 200, response.text


async def test_returned_plan_cannot_echo_now_classified_sources(case):
    await fixtures.add_rule(case, source="documents")
    run = await fixtures.recalculate(case)
    async with fixtures.client(case, "branch") as (http, _):
        response = await http.post("/api/v1/assessment/plans", json={"run_id": run["id"]})
        assert response.status_code == 200
        plan = response.json()["data"]
        assert "当前 1.0项" in plan["content"]
    await fixtures.mutate_document(case, security_level="classified")
    async with fixtures.client(case, "reviewer") as (http, _):
        assert (await fixtures.workspace(http, case))["plan"]["content"] is None
        response = await http.post(
            f"/api/v1/assessment/plans/{plan['id']}/review",
            json={"status": "returned", "opinion": "重新核查", "expected_revision": 1},
        )
        assert response.status_code == 409
        assert plan["content"] not in response.text


async def test_review_and_edit_keep_immutable_evidence_and_audit_pointers(case):
    await fixtures.add_rule(
        case, source="manual", formula="sum", source_options={"measure": "sum"}, target=2
    )
    task, body = await create_task(case, manual=True)
    async with fixtures.client(case, "reviewer") as (http, _):
        response = await http.post(
            f"/api/v1/assessment/tasks/{task['id']}/review",
            json={"status": "approved", "opinion": "保留此批准证据", "expected_revision": 1},
        )
        assert response.status_code == 200
    async with fixtures.client(case, "branch") as (http, db):
        response = await http.put(
            f"/api/v1/assessment/tasks/{task['id']}",
            json={**body, "manual_value": 3, "expected_revision": 2},
        )
        assert response.status_code == 200
        revisions = list(
            (
                await db.execute(
                    select(ContentRevision)
                    .where(ContentRevision.resource_id == task["id"])
                    .order_by(ContentRevision.revision)
                )
            ).scalars()
        )
        assert [item.revision for item in revisions] == [1, 2, 3]
        assert revisions[1].snapshot["review_status"] == "approved"
        assert revisions[1].snapshot["review_opinion"] == "保留此批准证据"
        assert revisions[1].snapshot["reviewed_by"] == case["actors"]["reviewer"].id
        assert revisions[1].snapshot["manual_value"] == "2.0"
        assert revisions[2].snapshot["manual_value"] == "3.0"
        audits = list(
            (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.resource_id == task["id"], AuditLog.result == "success"
                    )
                )
            ).scalars()
        )
        assert any(item.action == "assessment_task_create" for item in audits)
        update = next(item for item in audits if item.action == "assessment_task_update")
        assert update.old_value["revision"] == 2 and update.new_value["revision"] == 3
        assert body["basis"] not in json.dumps(
            [item.dict() for item in audits], ensure_ascii=False, default=str
        )


async def test_handled_missing_reminder_reopens_after_condition_returns(case):
    await fixtures.add_rule(case, required_evidence=["制度佐证"])
    await create_task(case)
    async with fixtures.client(case, "branch") as (http, _):
        data = await fixtures.workspace(http, case)
        reminder = next(item for item in data["reminders"] if item["kind"] == "missing_evidence")
        response = await http.post(
            f"/api/v1/assessment/reminders/{reminder['id']}/handle",
            json={"note": "合成已处理，等待资料核验"},
        )
        assert response.status_code == 200
    await approve_evidence(case)
    await fixtures.recalculate(case)
    await fixtures.mutate_document(case, is_deleted=True)
    await fixtures.recalculate(case)
    async with fixtures.client(case, "branch") as (http, db):
        data = await fixtures.workspace(http, case)
        reopened = next(item for item in data["reminders"] if item["id"] == reminder["id"])
        assert reopened["status"] == "open" and reopened["handled_by"] is None
        revisions = list(
            (
                await db.execute(
                    select(ContentRevision).where(ContentRevision.resource_id == reminder["id"])
                )
            ).scalars()
        )
        assert any(
            item.snapshot["status"] == "handled"
            and item.snapshot["handling_note"] == "合成已处理，等待资料核验"
            for item in revisions
        )


async def test_changed_rule_retains_authorized_historical_sources(case):
    await fixtures.add_rule(case, source="documents")
    run = await fixtures.recalculate(case)
    await fixtures.add_rule(case, expected_version=1, source="organizations")
    async with fixtures.client(case, "branch") as (http, _):
        response = await http.get(f"/api/v1/assessment/runs/{run['id']}")
        assert response.status_code == 200
        old = response.json()["data"]
        assert old["stale"] and old["results"][0]["actual"] == 1
        assert old["results"][0]["sources"][0]["record_id"] == case["doc_id"]
    await fixtures.mutate_document(case, security_level="classified")
    async with fixtures.client(case, "branch") as (http, _):
        response = await http.get(f"/api/v1/assessment/runs/{run['id']}")
        assert response.json()["data"]["results"][0]["actual"] is None
        assert case["doc_id"] not in response.text


async def test_school_history_retains_authorized_department_documents(case):
    case["actors"]["school"].role = UserRole.SYSTEM_ADMIN
    await fixtures.mutate_document(
        case,
        visibility="department",
        doc_metadata={"content_revision": 1, "org_unit_id": case["department"]},
    )
    await fixtures.add_rule(case, source="documents")
    run = await fixtures.recalculate(case, actor="school", org="school")
    assert run["results"][0]["actual"] == 1
    async with fixtures.client(case, "school") as (http, _):
        response = await http.get(f"/api/v1/assessment/runs/{run['id']}")
        assert response.status_code == 200
        assert response.json()["data"]["results"][0]["actual"] == 1
    await fixtures.add_rule(case, expected_version=1, source="organizations")
    async with fixtures.client(case, "school") as (http, _):
        response = await http.get(f"/api/v1/assessment/runs/{run['id']}")
        old = response.json()["data"]
        assert old["stale"] and old["results"][0]["actual"] == 1
        assert old["results"][0]["sources"][0]["record_id"] == case["doc_id"]
    await fixtures.mutate_document(case, security_level="classified")
    async with fixtures.client(case, "school") as (http, _):
        response = await http.get(f"/api/v1/assessment/runs/{run['id']}")
        assert response.json()["data"]["results"][0]["actual"] is None
        assert case["doc_id"] not in response.text


async def test_scheduler_honors_same_department_evidence_permissions(case, monkeypatch):
    from app.services import assessment_scheduler

    await fixtures.mutate_document(
        case,
        visibility="department",
        doc_metadata={"content_revision": 1, "org_unit_id": case["department"]},
    )
    await fixtures.add_rule(case, required_evidence=["制度佐证"])
    await create_task(case)
    await approve_evidence(case, reviewer="department")
    await fixtures.recalculate(case)
    engine = create_async_engine(case["url"], poolclass=NullPool, hide_parameters=True)
    try:
        monkeypatch.setattr(
            assessment_scheduler,
            "async_session_maker",
            lambda: AsyncSession(engine, expire_on_commit=False),
        )
        assert await assessment_scheduler.scan_assessment_reminders() >= 1
        async with fixtures.client(case, "branch") as (http, db):
            assert (await fixtures.workspace(http, case))["tasks"][0]["complete"]
            assert (
                await db.scalar(
                    select(func.count(AssessmentReminder.id)).where(
                        AssessmentReminder.kind == "missing_evidence",
                        AssessmentReminder.status == "open",
                    )
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_owner_query_count_does_not_grow_with_user_count(case, monkeypatch):
    async with fixtures.client(case, "branch") as (_, db):
        for _ in range(20):
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    tenant_id=case["tenant"],
                    username=uuid.uuid4().hex,
                    name="合成批量责任人",
                    password_hash="synthetic-hash",
                    role=UserRole.BRANCH_SECRETARY,
                    org_unit_id=case["branch"],
                )
            )
        await db.commit()
        execute, calls = db.execute, []

        async def counted(statement, *args, **kwargs):
            calls.append(statement)
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", counted)
        owners = await AssessmentService(db, case["actors"]["branch"])._owners(case["branch"])
        assert len(owners) >= 20
        assert len(calls) <= 3
