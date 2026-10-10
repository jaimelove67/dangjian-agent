"""真实 HTTP 与隔离 PostgreSQL 验证模块4；不调用云模型、不写开发业务库。"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_user
from app.main import app
from app.models.audit import AuditLog
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.meeting import ContentRevision, MeetingRecord
from app.models.org import OrgUnit
from app.models.study import StudyPlan, StudyPlanItem
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def study_url(storage_url):
    async def prepare():
        engine = create_async_engine(storage_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:

                def migrate(sync):
                    cfg = Config()
                    cfg.set_main_option("script_location", "migrations")
                    cfg.attributes["connection"] = sync
                    command.upgrade(cfg, "005")
                    sync.execute(
                        text(
                            "INSERT INTO knowledge_docs "
                            "(id, tenant_id, doc_id, title, file_name, issuer, level, visibility, "
                            "security_level, effective_date, status, is_deleted) VALUES "
                            "('pre-study-document', 'study-a', 'M4-UPGRADE-PRESERVE', "
                            "'迁移前保留文档', 'existing.txt', '合成组织', 'school', 'school', "
                            "'public', '2000-01-01', 'effective', false)"
                        )
                    )
                    before = (
                        sync.execute(text("SELECT * FROM knowledge_docs ORDER BY id"))
                        .mappings()
                        .all()
                    )
                    command.upgrade(cfg, "006")
                    assert (
                        sync.execute(text("SELECT * FROM knowledge_docs ORDER BY id"))
                        .mappings()
                        .all()
                        == before
                    )
                    command.downgrade(cfg, "005")
                    assert (
                        sync.execute(text("SELECT * FROM knowledge_docs ORDER BY id"))
                        .mappings()
                        .all()
                        == before
                    )
                    command.upgrade(cfg, "006")
                    assert (
                        sync.execute(text("SELECT version_num FROM alembic_version")).scalar()
                        == "006"
                    )

                await connection.run_sync(migrate)
            async with AsyncSession(engine, expire_on_commit=False) as db:
                for tenant_id in ("study-a", "study-b"):
                    db.add(
                        Tenant(
                            id=tenant_id,
                            tenant_id=tenant_id,
                            name="合成学校",
                            tenant_type="school",
                            path=tenant_id,
                            config={},
                        )
                    )
                for org_id, tenant, kind, parent in [
                    ("school-a", "study-a", "school", None),
                    ("department-a", "study-a", "department", "school-a"),
                    ("department-b", "study-a", "department", "school-a"),
                    ("branch-a", "study-a", "branch", "department-a"),
                    ("school-b", "study-b", "school", None),
                    ("foreign", "study-b", "department", "school-b"),
                ]:
                    db.add(
                        OrgUnit(
                            id=org_id,
                            tenant_id=tenant,
                            name="合成组织-" + org_id,
                            org_type=kind,
                            parent_id=parent,
                            path=org_id,
                        )
                    )
                for doc_id, tenant, visibility, level, security, org, expired, future in [
                    ("STUDY-VALID", "study-a", "school", "school", "internal", None, False, False),
                    (
                        "STUDY-DEPT",
                        "study-a",
                        "department",
                        "department",
                        "internal",
                        "department-a",
                        False,
                        False,
                    ),
                    (
                        "STUDY-OTHER-DEPT",
                        "study-a",
                        "department",
                        "department",
                        "internal",
                        "department-b",
                        False,
                        False,
                    ),
                    ("STUDY-EXPIRED", "study-a", "school", "school", "internal", None, True, False),
                    ("STUDY-FUTURE", "study-a", "school", "school", "internal", None, False, True),
                    (
                        "STUDY-CLASSIFIED",
                        "study-a",
                        "school",
                        "school",
                        "classified",
                        None,
                        False,
                        False,
                    ),
                    (
                        "STUDY-PRIVATE",
                        "study-b",
                        "school",
                        "school",
                        "internal",
                        None,
                        False,
                        False,
                    ),
                    ("STUDY-PUBLIC", "study-b", "public", "central", "public", None, False, False),
                ]:
                    doc = KnowledgeDoc(
                        tenant_id=tenant,
                        doc_id=doc_id,
                        title="合成学习重点制度-" + doc_id,
                        file_name="synthetic.txt",
                        issuer="合成单位",
                        level=level,
                        visibility=visibility,
                        security_level=security,
                        effective_date=(
                            date.today() + timedelta(days=10) if future else date(2000, 1, 1)
                        ),
                        expiration_date=date.today() - timedelta(days=1) if expired else None,
                        status="effective",
                        tags=["学习重点"],
                        summary="合成学习材料",
                        doc_metadata={"org_unit_id": org, "content_revision": 1},
                    )
                    db.add(doc)
                    await db.flush()
                    db.add(
                        EmbeddingChunk(
                            tenant_id=tenant,
                            doc_id=doc.id,
                            chunk_id=doc_id + "-1",
                            content="第一条 合成学习重点真实原文，仅用于回归。",
                            sequence=1,
                            article="第一条",
                        )
                    )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    return storage_url


def actor(
    user_id="study-author", role=UserRole.DEPARTMENT_ADMIN, org="department-a", tenant="study-a"
):
    user = User(
        id=user_id,
        tenant_id=tenant,
        username=user_id,
        name="合成组织人员",
        role=role,
        org_unit_id=org,
        is_active=True,
        is_deleted=False,
    )
    user.knowledge_org_ids = [org, "school-a"] if tenant == "study-a" else [org, "school-b"]
    return user


@asynccontextmanager
async def client_for(url, current_user):
    engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True)

    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with tenant_context(current_user.tenant_id, user_id=current_user.id):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, engine
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def ok(client, method, path, body=None):
    response = await client.request(method, "/api/v1" + path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    return response.json()["data"]


async def new_plan(client, year=None, source="STUDY-VALID"):
    year = year or date.today().year
    # 每个用例使用独立年度，避免共享 fixture 中的计划互相污染。
    return await ok(
        client,
        "POST",
        "/study/plans",
        {
            "org_unit_id": "department-a",
            "year": year,
            "title": f"{year}学习计划",
            "priorities": ["学习重点"],
            "responsible": "合成负责人",
            "source_doc_ids": [source] if source else [],
            "reason": "合成年度依据",
            "items": [
                {
                    "topic": "学习重点",
                    "scheduled_on": f"{year}-01-01",
                    "responsible": "合成负责人",
                    "source_doc_ids": [source] if source else [],
                }
            ],
        },
    )


async def approve_plan(url, plan):
    async with client_for(url, actor()) as (client, _):
        plan = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/submit",
            {"expected_revision": plan["revision"], "reason": "组织人员研究后提交"},
        )
    async with client_for(url, actor("study-reviewer")) as (client, _):
        return await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/review",
            {
                "expected_revision": plan["revision"],
                "reason": "核对计划与真实来源后通过",
                "decision": "approved",
            },
        )


async def completed_activity(url, year):
    async with client_for(url, actor()) as (client, _):
        plan = await new_plan(client, year)
    plan = await approve_plan(url, plan)
    async with client_for(url, actor()) as (client, _):
        record = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{plan['items'][0]['id']}/activity",
            {"expected_revision": plan["revision"], "reason": "登记一次活动"},
        )
        transcript = "原文起始\n学习要点：研读合成制度第一条。\n讨论共识：共同核对引用依据。\n工作要求：由组织人员落实工作。\n"
        record = await ok(
            client,
            "PATCH",
            f"/study/activities/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记实际召开情况",
                "held_on": f"{year}-01-02",
                "host": "合成主持人",
                "participants": [
                    {"participant_id": "p1", "name": "合成人员甲", "attended": True},
                    {"participant_id": "p2", "name": "合成人员乙", "attended": False},
                ],
                "transcript": transcript,
            },
        )
        record = await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/generate-minutes",
            {"expected_revision": record["revision"], "reason": "逐项提取原文"},
        )
        record = await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/submit",
            {"expected_revision": record["revision"], "reason": "提交人工审核"},
        )
    async with client_for(url, actor("study-reviewer")) as (client, _):
        record = await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/review",
            {
                "expected_revision": record["revision"],
                "reason": "核对原文和参学后通过",
                "decision": "approved",
            },
        )
    return plan, record


@pytest.mark.parametrize(
    "role", [UserRole.MEMBER, UserRole.APPLICANT, UserRole.BRANCH_SECRETARY, UserRole.ORGANIZER]
)
async def test_unauthorized_role_cannot_use_learning_endpoints(study_url, role):
    async with client_for(study_url, actor(role=role, org="branch-a")) as (client, _):
        for path in (
            "/study/plans",
            "/study/org-units",
            "/study/history",
            "/study/metrics?year=2026",
        ):
            assert (await client.get("/api/v1" + path)).status_code == 403


async def test_recommendations_enforce_org_tenant_classification_and_dates(study_url):
    async with client_for(study_url, actor()) as (client, _):
        data = await ok(client, "GET", "/study/materials?org_unit_id=department-a&q=学习重点")
        assert {source["doc_id"] for source in data["sources"]} == {
            "STUDY-VALID",
            "STUDY-DEPT",
            "STUDY-PUBLIC",
        }
        assert all(
            source["chunk_id"] and source["sha256"] and source["effective_date"]
            for source in data["sources"]
        )
        empty = await ok(
            client, "GET", "/study/materials?org_unit_id=department-a&q=完全没有资料的主题"
        )
        assert not empty["sources"] and empty["missing"]
        assert (
            await client.get("/api/v1/study/materials?org_unit_id=department-b&q=学习重点")
        ).status_code == 403
    # 系统管理员有资料权限，但不能把其他院系文件当作本院系适用政策推荐。
    async with client_for(study_url, actor("sys", UserRole.SYSTEM_ADMIN, "school-a")) as (
        client,
        _,
    ):
        data = await ok(client, "GET", "/study/materials?org_unit_id=department-a&q=学习重点")
        assert "STUDY-OTHER-DEPT" not in {source["doc_id"] for source in data["sources"]}


@pytest.mark.parametrize(
    "source",
    [
        "STUDY-EXPIRED",
        "STUDY-FUTURE",
        "STUDY-OTHER-DEPT",
        "STUDY-CLASSIFIED",
        "STUDY-PRIVATE",
        "invented-file",
    ],
)
async def test_invalid_policy_cannot_be_bound_to_plan(study_url, source):
    async with client_for(study_url, actor()) as (client, _):
        response = await client.post(
            "/api/v1/study/plans",
            json={
                "org_unit_id": "department-a",
                "year": 2040,
                "title": "计划",
                "priorities": ["学习重点"],
                "responsible": "组织人员",
                "source_doc_ids": [source],
                "reason": "测试",
            },
        )
        assert response.status_code == 422


async def test_plan_versions_period_queries_and_review_return(study_url):
    async with client_for(study_url, actor()) as (client, engine):
        plan = await new_plan(client, 2024)
        item = plan["items"][0]
        plan = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{item['id']}/generate-drafts",
            {"expected_revision": plan["revision"], "reason": "生成有依据提纲"},
        )
        assert "第一条 合成学习重点真实原文" in plan["items"][0]["outline"]
        assert plan["items"][0]["template_version"] == "study-1"
        assert plan["items"][0]["agenda"].endswith("供党委研究确定")
        assert (
            await client.post(
                f"/api/v1/study/plans/{plan['id']}/submit",
                json={"expected_revision": 1, "reason": "过期版本"},
            )
        ).status_code == 409
        plan = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/submit",
            {"expected_revision": plan["revision"], "reason": "送审"},
        )
        assert (
            await client.post(
                f"/api/v1/study/plans/{plan['id']}/review",
                json={
                    "expected_revision": plan["revision"],
                    "reason": "自己通过",
                    "decision": "approved",
                },
            )
        ).status_code == 403
        listing = await ok(client, "GET", "/study/plans?year=2024&start=2024-01-01&end=2024-03-31")
        assert any(row["id"] == plan["id"] for row in listing["items"])
        assert not (await ok(client, "GET", "/study/plans?year=2024&start=2024-02-01"))["items"]
        assert (
            await client.get("/api/v1/study/plans?start=2024-02-01&end=2024-01-01")
        ).status_code == 422
    async with client_for(study_url, actor("study-reviewer")) as (client, _):
        plan = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/review",
            {"expected_revision": plan["revision"], "reason": "请补充安排", "decision": "rejected"},
        )
    async with client_for(study_url, actor()) as (client, _):
        plan = await ok(
            client,
            "PATCH",
            f"/study/plans/{plan['id']}",
            {
                "expected_revision": plan["revision"],
                "reason": "按审核意见修订",
                "title": "修订后的年度计划",
                "priorities": ["学习重点"],
                "responsible": "合成负责人",
                "source_doc_ids": ["STUDY-VALID"],
            },
        )
        assert plan["review_status"] == "draft" and plan["reviewed_by"] is None
        history = await ok(client, "GET", f"/study/plans/{plan['id']}/revisions")
        assert any(row["snapshot"]["review_status"] == "rejected" for row in history["items"])
        assert history["items"][-1]["snapshot"]["title"] == "2024学习计划"
    plan = await approve_plan(study_url, plan)
    assert plan["review_status"] == "approved"


async def test_missing_materials_remain_draft(study_url):
    async with client_for(study_url, actor()) as (client, _):
        plan = await new_plan(client, 2031, source=None)
        item = plan["items"][0]
        plan = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{item['id']}/generate-drafts",
            {"expected_revision": plan["revision"], "reason": "缺材料草案"},
        )
        assert "政策依据待补" in plan["items"][0]["outline"]
        assert (
            await client.post(
                f"/api/v1/study/plans/{plan['id']}/submit",
                json={"expected_revision": plan["revision"], "reason": "缺依据送审"},
            )
        ).status_code == 422
        assert (
            await client.post(
                f"/api/v1/study/plans/{plan['id']}/items/{item['id']}/activity",
                json={"expected_revision": plan["revision"], "reason": "越过审核"},
            )
        ).status_code == 409


async def test_full_activity_archive_export_and_metrics_are_reusable(study_url):
    plan, record = await completed_activity(study_url, 2023)
    activity_path = f"/study/activities/{record['id']}"
    async with client_for(study_url, actor()) as (client, engine):
        repeat = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{plan['items'][0]['id']}/activity",
            {"expected_revision": 1, "reason": "失败重试"},
        )
        assert repeat["id"] == record["id"]
        metrics = await ok(client, "GET", "/study/metrics?year=2023")
        assert metrics["learning_count"]["value"] == 1
        assert metrics["plan_completion_rate"]["value"] == 1
        assert metrics["attendance_rate"]["value"] == 0.5
        assert metrics["minutes_completeness"]["value"] == 1
        assert metrics["evidence"][0]["participants"][0]["source_id"].startswith(record["id"])
        repeated_metrics = await ok(client, "GET", "/study/metrics?year=2023")
        assert repeated_metrics == metrics
        async with AsyncSession(engine) as db:
            assert (
                await db.scalar(
                    select(func.count(MeetingRecord.id)).where(
                        MeetingRecord.context["plan_id"].as_string() == plan["id"]
                    )
                )
                == 1
            )
        assert (
            await client.post(
                "/api/v1" + activity_path + "/archive",
                json={"expected_revision": record["revision"], "reason": "尚未确认电子效力"},
            )
        ).status_code == 403
        assert (await client.get("/api/v1/study/history?year=2023")).status_code == 403
        assert (await client.get("/api/v1" + activity_path + "/export")).status_code == 403
        assert (
            await client.patch(
                "/api/v1/admin/electronic-archive",
                json={"enabled": True, "expected_revision": 0, "evidence": "院系不能确认学校效力"},
            )
        ).status_code == 403
    async with client_for(
        study_url, actor("school-confirm", UserRole.SCHOOL_ADMIN, "school-a")
    ) as (client, _):
        policy = await ok(
            client,
            "PATCH",
            "/admin/electronic-archive",
            {
                "enabled": True,
                "expected_revision": 0,
                "evidence": "合成回归效力确认，不是实际学校批准",
            },
        )
        assert policy["confirmed_by"] == "school-confirm"
    async with client_for(study_url, actor()) as (client, engine):
        record = await ok(
            client,
            "POST",
            activity_path + "/archive",
            {"expected_revision": record["revision"], "reason": "归档审核版本"},
        )
        archive_repeat = await ok(
            client,
            "POST",
            activity_path + "/archive",
            {"expected_revision": 1, "reason": "重复归档"},
        )
        assert archive_repeat["revision"] == record["revision"]
        exported = await ok(client, "GET", activity_path + "/export")
        assert exported["record"]["reviewed_by"] == "study-reviewer"
        assert exported["archive_confirmation"]["revision"] == policy["revision"]
        assert exported["plan_version"]["revision"] == plan["revision"]
        assert any(
            row["snapshot"]["transcript"].startswith("原文起始") for row in exported["revisions"]
        )
        history = await ok(client, "GET", "/study/history?year=2023&topic=学习重点")
        assert {row["id"] for row in history["items"]} == {record["id"]}
        assert not (await ok(client, "GET", "/study/history?year=2022"))["items"]
        assert (
            await client.patch(
                "/api/v1" + activity_path,
                json={"expected_revision": record["revision"], "reason": "覆盖正式档案"},
            )
        ).status_code == 409
        async with AsyncSession(engine) as db:
            logs = (
                (await db.execute(select(AuditLog).where(AuditLog.resource_id == record["id"])))
                .scalars()
                .all()
            )
            assert any(row.action == "export" for row in logs)
            assert "合成人员甲" not in json.dumps(
                [row.new_value for row in logs], ensure_ascii=False
            )
    async with client_for(
        study_url, actor("school-confirm", UserRole.SCHOOL_ADMIN, "school-a")
    ) as (client, _):
        await ok(
            client,
            "PATCH",
            "/admin/electronic-archive",
            {"enabled": False, "expected_revision": policy["revision"], "evidence": "合成撤销确认"},
        )
    async with client_for(study_url, actor()) as (client, _):
        assert (await client.get("/api/v1" + activity_path)).status_code == 403
        assert (await client.get("/api/v1" + activity_path + "/export")).status_code == 403
        assert (await client.get("/api/v1/study/history")).status_code == 403


async def test_cross_org_tenant_and_missing_org_cannot_access_records(study_url):
    async with client_for(study_url, actor()) as (client, _):
        plan = await new_plan(client, 2032)
    for current in (
        actor("other-dept", org="department-b"),
        actor("foreign", org="foreign", tenant="study-b"),
        actor("unbound", org=None),
    ):
        async with client_for(study_url, current) as (client, _):
            assert (await client.get(f"/api/v1/study/plans/{plan['id']}")).status_code == 404
            assert (
                await client.get(f"/api/v1/study/plans/{plan['id']}/revisions")
            ).status_code == 404
            assert (
                await client.patch(
                    f"/api/v1/study/plans/{plan['id']}",
                    json={
                        "expected_revision": 1,
                        "reason": "越权",
                        "title": "伪造",
                        "priorities": ["伪造"],
                        "responsible": "伪造",
                    },
                )
            ).status_code == 404
            assert (await ok(client, "GET", "/study/plans"))["items"] == []


async def test_policy_permission_change_redacts_existing_snapshots_and_versions(study_url):
    async with client_for(study_url, actor()) as (client, engine):
        plan = await new_plan(client, 2033, source="STUDY-DEPT")
        async with AsyncSession(engine, expire_on_commit=False) as db:
            doc = (
                await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.doc_id == "STUDY-DEPT"))
            ).scalar_one()
            doc.security_level = "classified"
            await db.commit()
        data = await ok(client, "GET", f"/study/plans/{plan['id']}")
        assert data["restricted"] and not data["sources"] and not data["priorities"]
        revisions = await ok(client, "GET", f"/study/plans/{plan['id']}/revisions")
        assert all(row["snapshot"] is None and row["restricted"] for row in revisions["items"])
        assert "真实原文" not in json.dumps(data, ensure_ascii=False)


async def test_cross_year_activity_counts_actual_year_and_plan_year_separately(study_url):
    async with client_for(study_url, actor()) as (client, _):
        plan = await new_plan(client, 2020)
    plan = await approve_plan(study_url, plan)
    async with client_for(study_url, actor()) as (client, _):
        record = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{plan['items'][0]['id']}/activity",
            {"expected_revision": plan["revision"], "reason": "跨年学习"},
        )
        record = await ok(
            client,
            "PATCH",
            f"/study/activities/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "实际次年召开",
                "held_on": "2021-01-02",
                "host": "合成主持人",
                "participants": [{"participant_id": "p", "name": "合成人员", "attended": True}],
                "transcript": "学习要点：原文。\n讨论共识：原文。\n工作要求：原文。",
            },
        )
        record = await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/generate-minutes",
            {"expected_revision": record["revision"], "reason": "提取"},
        )
        record = await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/submit",
            {"expected_revision": record["revision"], "reason": "送审"},
        )
    async with client_for(study_url, actor("study-reviewer")) as (client, _):
        await ok(
            client,
            "POST",
            f"/study/activities/{record['id']}/review",
            {"expected_revision": record["revision"], "reason": "跨年审核", "decision": "approved"},
        )
        old = await ok(client, "GET", "/study/metrics?year=2020")
        actual = await ok(client, "GET", "/study/metrics?year=2021")
        assert old["plan_completion_rate"]["value"] == 1 and old["learning_count"]["value"] is None
        assert (
            actual["learning_count"]["value"] == 1
            and actual["plan_completion_rate"]["value"] is None
        )


async def add_policy(engine, *, expiration=None):
    """每个异常资料用例独立登记文件，避免更改其他用例的有效依据。"""
    doc_id = "STUDY-ADVERSARIAL-" + uuid.uuid4().hex
    async with AsyncSession(engine, expire_on_commit=False) as db:
        doc = KnowledgeDoc(
            tenant_id="study-a",
            doc_id=doc_id,
            title="学习重点反向检查制度",
            file_name="synthetic.txt",
            issuer="合成组织",
            level="school",
            visibility="school",
            security_level="internal",
            effective_date=date(2000, 1, 1),
            expiration_date=expiration,
            status="effective",
            tags=["学习重点"],
            doc_metadata={"content_revision": 1},
        )
        db.add(doc)
        await db.flush()
        db.add(
            EmbeddingChunk(
                tenant_id="study-a",
                doc_id=doc.id,
                chunk_id=doc_id + "-1",
                content="仅用于反向检查的年度依据原文。",
                sequence=1,
            )
        )
        await db.commit()
    return doc_id


async def test_annual_basis_permission_change_also_redacts_linked_activity(study_url):
    async with client_for(study_url, actor()) as (client, engine):
        doc_id = await add_policy(engine)
        plan = await new_plan(client, 2017, source=doc_id)
        item = plan["items"][0]
        plan = await ok(
            client,
            "PATCH",
            f"/study/plans/{plan['id']}/items/{item['id']}",
            {
                "expected_revision": plan["revision"],
                "reason": "本期资料与年度依据不同",
                "topic": item["topic"],
                "scheduled_on": item["scheduled_on"],
                "responsible": item["responsible"],
                "source_doc_ids": ["STUDY-VALID"],
            },
        )
    plan = await approve_plan(study_url, plan)
    async with client_for(study_url, actor()) as (client, engine):
        record = await ok(
            client,
            "POST",
            f"/study/plans/{plan['id']}/items/{item['id']}/activity",
            {"expected_revision": plan["revision"], "reason": "复用年度依据"},
        )
        assert {source["doc_id"] for source in record["sources"]} == {doc_id, "STUDY-VALID"}
        record = await ok(
            client,
            "PATCH",
            f"/study/activities/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "本期材料选择不能移除年度依据保护",
                "source_doc_ids": ["STUDY-VALID"],
            },
        )
        assert {source["doc_id"] for source in record["sources"]} == {doc_id, "STUDY-VALID"}
        async with AsyncSession(engine) as db:
            doc = (
                await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.doc_id == doc_id))
            ).scalar_one()
            doc.security_level = "classified"
            await db.commit()
        data = await ok(client, "GET", f"/study/activities/{record['id']}")
        assert data["restricted"] and not data["sources"] and not data["context"].get("agenda")
        response = await client.patch(
            f"/api/v1/study/activities/{record['id']}",
            json={
                "expected_revision": record["revision"],
                "reason": "不能通过替换本期资料绕过年度依据权限",
                "source_doc_ids": ["STUDY-VALID"],
            },
        )
        assert response.status_code == 422
        unchanged = await ok(client, "GET", f"/study/activities/{record['id']}")
        assert unchanged["revision"] == record["revision"] and unchanged["restricted"]
        versions = await ok(client, "GET", f"/study/activities/{record['id']}/revisions")
        assert all(version["snapshot"] is None for version in versions["items"])


async def test_material_expiring_before_scheduled_date_is_not_recommended(study_url):
    async with client_for(study_url, actor()) as (client, engine):
        doc_id = await add_policy(engine, expiration=date.today() + timedelta(days=1))
        sources = await ok(client, "GET", "/study/materials?org_unit_id=department-a&q=学习重点")
        assert doc_id in {source["doc_id"] for source in sources["sources"]}
        future = date.today() + timedelta(days=2)
        sources = await ok(
            client,
            "GET",
            f"/study/materials?org_unit_id=department-a&q=学习重点&on={future.isoformat()}",
        )
        assert doc_id not in {source["doc_id"] for source in sources["sources"]}


async def test_concurrent_plan_revision_has_one_winner_and_keeps_both_versions(study_url):
    async with client_for(study_url, actor()) as (client, engine):
        plan = await new_plan(client, 2044)
        payload = {
            "expected_revision": plan["revision"],
            "priorities": ["学习重点"],
            "responsible": "组织人员",
            "source_doc_ids": ["STUDY-VALID"],
        }
        results = await asyncio.gather(
            *(
                client.patch(
                    f"/api/v1/study/plans/{plan['id']}",
                    json={**payload, "title": title, "reason": title},
                )
                for title in ("并发修订甲", "并发修订乙")
            )
        )
        assert sorted(response.status_code for response in results) == [200, 409]
        final = await ok(client, "GET", f"/study/plans/{plan['id']}")
        assert final["revision"] == 2
        async with AsyncSession(engine) as db:
            assert (
                await db.scalar(
                    select(func.count(ContentRevision.id)).where(
                        ContentRevision.resource_id == plan["id"]
                    )
                )
                == 2
            )
            assert (
                await db.scalar(select(func.count(StudyPlan.id)).where(StudyPlan.id == plan["id"]))
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count(StudyPlanItem.id)).where(StudyPlanItem.plan_id == plan["id"])
                )
                == 1
            )


async def test_activity_edit_requires_reapproval_and_return_keeps_prior_evidence(study_url):
    _, record = await completed_activity(study_url, 2016)
    path = f"/study/activities/{record['id']}"
    async with client_for(study_url, actor()) as (client, _):
        record = await ok(
            client,
            "PATCH",
            path,
            {
                "expected_revision": record["revision"],
                "reason": "纠正主持人记录",
                "held_on": record["held_on"],
                "host": "校正后的主持人",
                "participants": record["participants"],
                "transcript": record["transcript"],
                "minutes": record["minutes"],
            },
        )
        assert record["review_status"] == "draft" and record["reviewed_by"] is None
        stats = await ok(client, "GET", "/study/metrics?year=2016")
        assert stats["learning_count"]["value"] is None and stats["missing"]
        record = await ok(
            client,
            "POST",
            path + "/submit",
            {"expected_revision": record["revision"], "reason": "送审校正版本"},
        )
    async with client_for(study_url, actor("study-reviewer")) as (client, _):
        record = await ok(
            client,
            "POST",
            path + "/review",
            {
                "expected_revision": record["revision"],
                "reason": "退回，请再次核对",
                "decision": "rejected",
            },
        )
        assert record["review_status"] == "rejected"
        revisions = await ok(client, "GET", path + "/revisions")
        assert any(
            version["snapshot"]["review_status"] == "approved" for version in revisions["items"]
        )
        assert revisions["items"][0]["snapshot"]["review_comment"] == "退回，请再次核对"
