"""真实 HTTP 与隔离 PostgreSQL 验证模块3（组织生活三会一课）；不调用云模型、不写开发业务库。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_user
from app.main import app
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def life_url(storage_url):
    async def prepare():
        engine = create_async_engine(storage_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:

                def migrate(sync):
                    cfg = Config()
                    cfg.set_main_option("script_location", "migrations")
                    cfg.attributes["connection"] = sync
                    command.upgrade(cfg, "008_org_life_tasks")

                await connection.run_sync(migrate)
            async with AsyncSession(engine, expire_on_commit=False) as db:
                for tenant_id in ("life-a", "life-b"):
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
                    ("school-a", "life-a", "school", None),
                    ("department-a", "life-a", "department", "school-a"),
                    ("department-b", "life-a", "department", "school-a"),
                    ("branch-a", "life-a", "branch", "department-a"),
                    ("branch-b", "life-a", "branch", "department-b"),
                    ("school-b", "life-b", "school", None),
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
                for doc_id, tenant, visibility, level, security, org, expired in [
                    ("LIFE-VALID", "life-a", "school", "school", "internal", None, False),
                    (
                        "LIFE-BRANCH",
                        "life-a",
                        "branch",
                        "branch",
                        "internal",
                        "branch-a",
                        False,
                    ),
                    ("LIFE-OTHER-DEPT", "life-a", "department", "department", "internal", "department-b", False),
                    ("LIFE-EXPIRED", "life-a", "school", "school", "internal", None, True),
                    ("LIFE-CLASSIFIED", "life-a", "school", "school", "classified", None, False),
                    ("LIFE-PRIVATE", "life-b", "school", "school", "internal", None, False),
                ]:
                    doc = KnowledgeDoc(
                        tenant_id=tenant,
                        doc_id=doc_id,
                        title="合成组织生活制度-" + doc_id,
                        file_name="synthetic.txt",
                        issuer="合成单位",
                        level=level,
                        visibility=visibility,
                        security_level=security,
                        effective_date=date(2000, 1, 1),
                        expiration_date=date.today() - timedelta(days=1) if expired else None,
                        status="effective",
                        tags=["组织生活"],
                        summary="合成组织生活材料",
                        doc_metadata={"org_unit_id": org, "content_revision": 1},
                    )
                    db.add(doc)
                    await db.flush()
                    db.add(
                        EmbeddingChunk(
                            tenant_id=tenant,
                            doc_id=doc.id,
                            chunk_id=doc_id + "-1",
                            content="第一条 合成组织生活真实原文，仅用于回归。",
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
    user_id="life-author", role=UserRole.DEPARTMENT_ADMIN, org="department-a", tenant="life-a"
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
    user.knowledge_org_ids = [org, "school-a"] if tenant == "life-a" else [org, "school-b"]
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


async def ok(client, method, path, body=None, params=None):
    response = await client.request(method, "/api/v1" + path, json=body, params=params)
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    return response.json()["data"]


TRANSCRIPT = (
    "会议原文起始\n学习要点：研读合成组织生活制度第一条。\n"
    "讨论共识：共同核对引用依据。\n工作要求：由组织人员落实工作。\n"
)


async def new_record(client, year=None, source="LIFE-VALID", org="branch-a"):
    year = year or date.today().year
    return await ok(
        client,
        "POST",
        "/meeting/records",
        {
            "org_unit_id": org,
            "activity_type": "branch_member_meeting",
            "title": f"{year}第一季度支部大会",
            "scheduled_on": f"{year}-01-05",
            "host": "合成主持人",
            "source_doc_ids": [source] if source else [],
            "reason": "合成一次组织生活",
        },
    )


async def confirm_archive(url, tenant="life-a"):
    async with client_for(url, actor("life-school", UserRole.SCHOOL_ADMIN, "school-a", tenant)) as (
        client,
        _,
    ):
        return await ok(
            client,
            "PATCH",
            "/admin/electronic-archive",
            {"enabled": True, "expected_revision": 0, "evidence": "学校组织部门确认电子记录效力"},
        )


@pytest.mark.asyncio
async def test_full_record_lifecycle_review_archive_and_stats(life_url):
    year = date.today().year
    async with client_for(life_url, actor()) as (client, _):
        record = await new_record(client, year)
        assert record["execution_status"] == "planned"
        assert "待补" in record["missing"][0]

        recommended = await ok(
            client, "GET", f"/meeting/records/{record['id']}/recommendations", params={"q": "组织生活"}
        )
        assert recommended["sources"] and recommended["sources"][0]["doc_id"] == "LIFE-VALID"

        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/generate-agenda",
            {"expected_revision": record["revision"], "reason": "生成议程草稿"},
        )
        assert "会议议程（草稿）" in record["context"]["agenda"]
        assert "供支部委员会研究确定" in record["context"]["notice"]

        record = await ok(
            client,
            "PATCH",
            f"/meeting/records/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记实际召开情况",
                "held_on": f"{year}-01-06",
                "host": "合成主持人",
                "participants": [
                    {"participant_id": "p1", "name": "合成人员甲", "attended": True},
                    {"participant_id": "p2", "name": "合成人员乙", "attended": False},
                ],
                "transcript": TRANSCRIPT,
            },
        )
        assert record["execution_status"] == "held"

        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/generate-minutes",
            {"expected_revision": record["revision"], "reason": "逐项提取原文"},
        )
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/submit",
            {"expected_revision": record["revision"], "reason": "提交人工审核"},
        )
        assert record["review_status"] == "pending"
    async with client_for(life_url, actor("life-reviewer")) as (client, _):
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/review",
            {
                "expected_revision": record["revision"],
                "reason": "核对原文与参学后通过",
                "decision": "approved",
            },
        )
        assert record["execution_status"] == "completed"
    # 未确认电子归档效力时，归档与历史访问被拒绝
    async with client_for(life_url, actor()) as (client, _):
        response = await client.post(
            "/api/v1" + f"/meeting/records/{record['id']}/archive",
            json={"expected_revision": record["revision"], "reason": "申请归档"},
        )
        assert response.status_code == 403
        assert (await client.get("/api/v1/meeting/history")).status_code == 403
    await confirm_archive(life_url)
    async with client_for(life_url, actor()) as (client, _):
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/archive",
            {"expected_revision": record["revision"], "reason": "档案部门备案"},
        )
        assert record["execution_status"] == "archived"
        history = await ok(client, "GET", "/meeting/history?page_size=50")
        assert history["total"] >= 1 and history["items"][0]["id"] == record["id"]
        exported = await ok(client, "GET", f"/meeting/records/{record['id']}/export")
        assert exported["record"]["id"] == record["id"]
        assert exported["archive_confirmation"]["enabled"] is True
        revisions = await ok(client, "GET", f"/meeting/records/{record['id']}/revisions")
        assert any(item["action"] == "archive" for item in revisions["items"])
        stats = await ok(client, "GET", f"/meeting/stats?year={year}")
        assert stats["counts"]["archived"] >= 1
        assert stats["attendance_rate"]["numerator"] == 1
        assert stats["attendance_rate"]["denominator"] == 2
        assert stats["by_type"]["branch_member_meeting"]["performed"] >= 1


@pytest.mark.asyncio
async def test_task_workflow_requires_exact_excerpt_and_manual_confirm(life_url):
    async with client_for(life_url, actor()) as (client, _):
        record = await new_record(client)
        record = await ok(
            client,
            "PATCH",
            f"/meeting/records/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记会议文本",
                "transcript": TRANSCRIPT,
            },
        )
        # 摘录必须与原文逐字一致：位置错位直接拒绝
        response = await client.post(
            "/api/v1" + f"/meeting/records/{record['id']}/tasks",
            json={
                "task_text": "错位摘录",
                "source_start": 0,
                "source_end": 4,
                "reason": "错误定位",
            },
        )
        assert response.status_code == 422
        position = TRANSCRIPT.index("工作要求：由组织人员落实工作。")
        quote = TRANSCRIPT[position : position + 6]
        task = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/tasks",
            {
                "task_text": quote,
                "source_start": position,
                "source_end": position + len(quote),
                "reason": "摘录任务",
            },
        )
        task = task["task"]
        assert task["status"] == "pending"
        # 原文未明确责任人：确认被拒，必须人工补齐
        response = await client.patch(
            "/api/v1" + f"/meeting/tasks/{task['id']}",
            json={"owner_name": "", "reason": "补齐责任人"},
        )
        assert response.status_code == 422
        task = await ok(
            client,
            "PATCH",
            f"/meeting/tasks/{task['id']}",
            {"owner_name": "合成责任人", "due_on": f"{date.today().year}-12-31", "reason": "人工补齐"},
        )
        task = task["task"]
        assert task["status"] == "active" and task["confirmed_by"] == "life-author"
        task = await ok(
            client,
            "POST",
            f"/meeting/tasks/{task['id']}/handle",
            {"status": "done", "handle_note": "已落实", "reason": "完成任务"},
        )
        assert task["task"]["status"] == "done" and task["task"]["handled_at"]
        listed = await ok(client, "GET", "/meeting/tasks?status=done")
        assert listed["total"] == 1 and listed["items"][0]["id"] == task["task"]["id"]


@pytest.mark.asyncio
async def test_org_scope_tenant_isolation_and_minimal_role(life_url):
    # 支部范围角色查询本支部活动；跨支部（另一部门下）不可达
    async with client_for(life_url, actor(role=UserRole.BRANCH_SECRETARY, org="branch-a")) as (
        client,
        _,
    ):
        created = await ok(
            client,
            "POST",
            "/meeting/records",
            {
                "org_unit_id": "branch-a",
                "activity_type": "party_group_meeting",
                "title": "支部范围活动-唯一标记",
                "scheduled_on": f"{date.today().year}-02-01",
                "reason": "支部登记",
            },
        )
        listed = await ok(client, "GET", "/meeting/records?page_size=50")
        assert any(item["id"] == created["id"] for item in listed["items"])
    # 另一个部门下的支部看不到 branch-a 的活动
    async with client_for(
        life_url, actor("life-branch2", UserRole.BRANCH_SECRETARY, "branch-b")
    ) as (client, _):
        listed = await ok(client, "GET", "/meeting/records?page_size=50")
        assert all(item["org_unit_id"] != "branch-a" for item in listed["items"])
    # 跨租户不可见（life-b 看不到 life-a 的任何记录）
    async with client_for(life_url, actor(tenant="life-b", org="school-b")) as (client, _):
        listed = await ok(client, "GET", "/meeting/records?page_size=50")
        assert listed["total"] == 0
    # 无权限角色被拒绝
    async with client_for(life_url, actor(role=UserRole.MEMBER, org="branch-a")) as (client, _):
        assert (await client.get("/api/v1/meeting/records")).status_code == 403
        assert (
            await client.post(
                "/api/v1/meeting/records",
                json={
                    "org_unit_id": "branch-a",
                    "activity_type": "party_lecture",
                    "title": "无权限登记",
                    "scheduled_on": f"{date.today().year}-03-01",
                    "reason": "越权",
                },
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_missing_evidence_and_review_gates(life_url):
    async with client_for(life_url, actor()) as (client, _):
        # 无依据材料不得虚构推荐
        record = await new_record(client, source=None)
        recommended = await ok(
            client, "GET", f"/meeting/records/{record['id']}/recommendations"
        )
        assert recommended["sources"] == []
        assert any("待补" in item for item in recommended["missing"])
        # 未登记原文/参学不能提交
        response = await client.post(
            "/api/v1" + f"/meeting/records/{record['id']}/submit",
            json={"expected_revision": record["revision"], "reason": "提前提交"},
        )
        assert response.status_code == 422
        # 草稿内容不完整时审核被校验拦截（不进入待审核状态机）
        response = await client.post(
            "/api/v1" + f"/meeting/records/{record['id']}/review",
            json={"expected_revision": record["revision"], "decision": "approved", "reason": "越权审核"},
        )
        assert response.status_code == 422
        # 补全内容后提交，提交人不能自审
        record = await ok(
            client,
            "PATCH",
            f"/meeting/records/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记会议文本与参学",
                "held_on": f"{date.today().year}-04-01",
                "host": "合成主持人",
                "participants": [{"participant_id": "p1", "name": "合成人员甲", "attended": True}],
                "transcript": TRANSCRIPT,
            },
        )
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/generate-minutes",
            {"expected_revision": record["revision"], "reason": "提取原文"},
        )
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/submit",
            {"expected_revision": record["revision"], "reason": "提交审核"},
        )
        assert record["review_status"] == "pending"
        response = await client.post(
            "/api/v1" + f"/meeting/records/{record['id']}/review",
            json={"expected_revision": record["revision"], "decision": "approved", "reason": "自审"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_revision_conflict_reads_prior_evidence(life_url):
    async with client_for(life_url, actor()) as (client, _):
        record = await new_record(client)
        response = await client.patch(
            "/api/v1" + f"/meeting/records/{record['id']}",
            json={
                "expected_revision": record["revision"] + 1,
                "reason": "过期版本修订",
                "host": "新主持人",
            },
        )
        assert response.status_code == 409
        record = await ok(
            client,
            "PATCH",
            f"/meeting/records/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记会议文本",
                "transcript": TRANSCRIPT,
            },
        )
        revisions = await ok(client, "GET", f"/meeting/records/{record['id']}/revisions")
        assert any(item["action"] == "create" for item in revisions["items"])
        assert any(item["action"] == "revise" for item in revisions["items"])


@pytest.mark.asyncio
async def test_records_filter_by_type_year_and_status(life_url):
    year = date.today().year
    async with client_for(life_url, actor()) as (client, _):
        for index, activity_type in enumerate(
            ["branch_committee_meeting", "party_lecture", "branch_member_meeting"]
        ):
            await ok(
                client,
                "POST",
                "/meeting/records",
                {
                    "org_unit_id": "branch-a",
                    "activity_type": activity_type,
                    "title": f"筛选用例-{index}",
                    "scheduled_on": f"{year}-0{index + 1}-10",
                    "reason": "筛选测试",
                },
            )
        by_type = await ok(client, "GET", f"/meeting/records?activity_type=party_lecture&year={year}")
        assert by_type["total"] >= 1 and all(
            item["activity_type"] == "party_lecture" for item in by_type["items"]
        )
        planned = await ok(
            client, "GET", f"/meeting/records?execution_status=planned&year={year}&page_size=50"
        )
        assert planned["total"] >= 3 and all(
            item["execution_status"] == "planned" for item in planned["items"]
        )
        # 未知类型/状态被拒绝
        assert (
            await client.get("/api/v1/meeting/records?activity_type=center_group")
        ).status_code == 422
        assert (
            await client.get("/api/v1/meeting/records?execution_status=whatever")
        ).status_code == 422
