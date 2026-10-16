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
                    command.upgrade(cfg, "head")

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
                    ("branch-c", "life-a", "branch", "department-a"),
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
                    (
                        "LIFE-OTHER-DEPT",
                        "life-a",
                        "department",
                        "department",
                        "internal",
                        "department-b",
                        False,
                    ),
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
            client,
            "GET",
            f"/meeting/records/{record['id']}/recommendations",
            params={"q": "组织生活"},
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
            {
                "owner_name": "合成责任人",
                "due_on": f"{date.today().year}-12-31",
                "reason": "人工补齐",
            },
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
        recommended = await ok(client, "GET", f"/meeting/records/{record['id']}/recommendations")
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
            json={
                "expected_revision": record["revision"],
                "decision": "approved",
                "reason": "越权审核",
            },
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
            json={
                "expected_revision": record["revision"],
                "decision": "approved",
                "reason": "自审",
            },
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
        by_type = await ok(
            client, "GET", f"/meeting/records?activity_type=party_lecture&year={year}"
        )
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


async def held_activity(client, *, org, activity_type, held_on):
    """登记一条"已召开但尚未提交审核"的活动，供频次用例使用。"""
    record = await ok(
        client,
        "POST",
        "/meeting/records",
        {
            "org_unit_id": org,
            "activity_type": activity_type,
            "title": f"{held_on} 合成{activity_type}",
            "scheduled_on": held_on,
            "host": "合成主持人",
            "reason": "合成一次组织生活",
        },
    )
    return await ok(
        client,
        "PATCH",
        f"/meeting/records/{record['id']}",
        {
            "expected_revision": record["revision"],
            "reason": "登记实际召开情况",
            "held_on": held_on,
            "participants": [{"participant_id": "p1", "name": "合成人员甲", "attended": True}],
            "transcript": TRANSCRIPT,
        },
    )


async def submit_activity(client, record):
    """提取纪要并提交审核；审核必须由另一位人员完成，不能自审。"""
    record = await ok(
        client,
        "POST",
        f"/meeting/records/{record['id']}/generate-minutes",
        {"expected_revision": record["revision"], "reason": "逐项提取原文"},
    )
    return await ok(
        client,
        "POST",
        f"/meeting/records/{record['id']}/submit",
        {"expected_revision": record["revision"], "reason": "提交人工审核"},
    )


async def review_activity(client, record, decision="approved"):
    return await ok(
        client,
        "POST",
        f"/meeting/records/{record['id']}/review",
        {
            "expected_revision": record["revision"],
            "reason": "核对原文与参学后通过",
            "decision": decision,
        },
    )


@pytest.mark.asyncio
async def test_declared_frequency_matches_the_regulation(life_url):
    """规定频次按周期口径给出：支委会/党小组会每月 1 次、支部大会/党课每季度 1 次。"""
    async with client_for(life_url, actor()) as (client, _):
        stats = await ok(client, "GET", f"/meeting/stats?year={date.today().year}")
        by_type = stats["by_type"]
        assert by_type["branch_member_meeting"]["required"] == 4
        assert by_type["branch_committee_meeting"]["required"] == 12
        assert by_type["party_group_meeting"]["required"] == 12
        assert by_type["party_lecture"]["required"] == 4
        assert by_type["branch_committee_meeting"]["period_text"] == "每月至少 1 次"
        assert by_type["party_lecture"]["period_text"] == "每季度至少 1 次"
        assert by_type["other"]["required"] == 0
        assert "每季度" in by_type["party_lecture"]["basis"]


@pytest.mark.asyncio
async def test_frequency_reminder_counts_only_approved_and_scopes_to_branches(life_url):
    # 单独的支部（branch-c）与 2026-05-10 的回顾口径：频次用例不受本模块其他用例的记录干扰
    as_of = date(2026, 5, 10)
    async with client_for(life_url, actor()) as (client, _):
        member_meeting = await held_activity(
            client, org="branch-c", activity_type="branch_member_meeting", held_on="2026-05-06"
        )
        await held_activity(
            client, org="branch-c", activity_type="branch_committee_meeting", held_on="2026-05-08"
        )
        assert member_meeting["review_status"] == "draft"
        before = await ok(client, "GET", "/meeting/frequency", params={"as_of": as_of.isoformat()})
        rows = {(row["activity_type"], row["org_unit_id"]): row for row in before["rows"]}
        # 已召开但纪要没审 ≠ 完成：状态是"待审核"，不是"已达标"也不是"没开"
        assert rows[("branch_member_meeting", "branch-c")]["state"] == "awaiting_review"
        assert rows[("branch_committee_meeting", "branch-c")]["state"] == "awaiting_review"
        assert rows[("branch_committee_meeting", "branch-c")]["performed"] == 0
        # 三会一课是支部制度：学校 / 院系节点不进入频次表，也不产生"未达标"噪声
        assert {row["org_unit_id"] for row in before["rows"]} == {"branch-a", "branch-c"}
        assert "other" not in {row["activity_type"] for row in before["rows"]}
        assert before["branch_count"] == 2
        # 已结束周期形成缺口：Q1 支部大会 / 党课，1—4 月支委会 / 党小组会
        gaps = {gap["activity_type"]: gap for gap in before["gaps"] if gap["org_unit_id"] == "branch-c"}
        assert set(gaps) == {
            "branch_member_meeting",
            "branch_committee_meeting",
            "party_group_meeting",
            "party_lecture",
        }
        assert gaps["branch_member_meeting"]["missed_periods"] == ["2026 年第 1 季度"]
        assert gaps["party_lecture"]["missed_periods"] == ["2026 年第 1 季度"]
        assert gaps["branch_committee_meeting"]["missed_periods"] == [
            "2026 年 1 月",
            "2026 年 2 月",
            "2026 年 3 月",
            "2026 年 4 月",
        ]
        assert gaps["branch_committee_meeting"]["awaiting_total"] == 0
        assert "已结束 4 个周期中 4 个未达标" in gaps["branch_committee_meeting"]["text"]

    # 支部大会审核通过后，本周期立刻从"待审核"变成"已达标"（登记人与审核人不同）
    async with client_for(life_url, actor()) as (client, _):
        member_meeting = await submit_activity(client, member_meeting)
    async with client_for(life_url, actor("life-reviewer")) as (client, _):
        await review_activity(client, member_meeting)
    async with client_for(life_url, actor()) as (client, _):
        after = await ok(client, "GET", "/meeting/frequency", params={"as_of": as_of.isoformat()})
        rows = {(row["activity_type"], row["org_unit_id"]): row for row in after["rows"]}
        row = rows[("branch_member_meeting", "branch-c")]
        assert row["state"] == "met" and row["performed"] == 1 and row["missing"] == 0
        assert row["period_label"] == "2026 年第 2 季度" and row["required"] == 1
        assert row["annual_required"] == 4 and "已达要求" in row["reminder"]
        # 审核通过只解决本周期：Q1 的缺口不会因为 5 月补开一次就消失
        member_gap = next(
            gap
            for gap in after["gaps"]
            if gap["org_unit_id"] == "branch-c" and gap["activity_type"] == "branch_member_meeting"
        )
        assert member_gap["missed_periods"] == ["2026 年第 1 季度"]
        assert member_gap["missing_total"] == 1
        # 支委会仍停在"已召开待审核"，且提醒指向去完成审核而不是重开一次
        awaiting = rows[("branch_committee_meeting", "branch-c")]
        assert awaiting["state"] == "awaiting_review" and awaiting["awaiting_review"] == 1
        assert "完成审核后即计入本周期" in awaiting["reminder"]
        pending = {
            row["activity_type"] for row in after["reminders"] if row["org_unit_id"] == "branch-c"
        }
        # branch-c 本周期只有支部大会达标；其余三类都在提醒里
        # 组织生活会按年度计（每年至少 1 次，一般排在第四季度）：截止日未到也算本周期未达标
        assert pending == {
            "branch_committee_meeting",
            "party_group_meeting",
            "party_lecture",
            "organizational_life_meeting",
        }
        # 未开的活动给出最晚期限与已安排次数
        lecture = rows[("party_lecture", "branch-c")]
        assert lecture["state"] == "open" and lecture["missing"] == 1
        assert "最晚 2026-06-30 前召开" in lecture["reminder"]
        assert "人工审核通过" in after["notice"] and "人工审核通过" in after["calculation_rule"]
        # 组织范围：本部门以外的支部不可查；非支部组织直接说明按支部计算
        assert (
            await client.get("/api/v1/meeting/frequency?org_unit_id=branch-b")
        ).status_code == 403
        response = await client.get("/api/v1/meeting/frequency?org_unit_id=department-a")
        assert response.status_code == 422
        assert "按支部计算" in response.json()["message"]

    # 无查询权限的角色看不到频次
    async with client_for(life_url, actor(role=UserRole.MEMBER, org="branch-a")) as (client, _):
        assert (await client.get("/api/v1/meeting/frequency")).status_code == 403


ORG_LIFE_TRANSCRIPT = (
    "会议原文起始\n查摆问题：班子集中学习安排不够固定，联系实际不够。\n"
    "批评意见：班子成员对年轻党员的培养关心不够。\n"
    "整改方向：每季度固定一次集中学习并逐条销号。\n"
    "学习要点：这一句属于三会一课栏目，组织生活会不提取。\n"
)


@pytest.mark.asyncio
async def test_organizational_life_meeting_uses_its_own_minutes_template(life_url):
    """组织生活会不是三会一课：纪要栏目是查摆问题 / 批评意见 / 整改方向。"""
    year = date.today().year
    async with client_for(life_url, actor()) as (client, _):
        record = await ok(
            client,
            "POST",
            "/meeting/records",
            {
                "org_unit_id": "branch-a",
                "activity_type": "organizational_life_meeting",
                "title": f"{year}年度组织生活会（合成）",
                "scheduled_on": f"{year}-09-05",
                "host": "合成主持人",
                "source_doc_ids": ["LIFE-VALID"],
                "reason": "合成一次组织生活会",
            },
        )
        listed = await ok(
            client,
            "GET",
            f"/meeting/records?activity_type=organizational_life_meeting&year={year}",
        )
        assert listed["total"] >= 1

        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/generate-agenda",
            {"expected_revision": record["revision"], "reason": "生成议程草稿"},
        )
        agenda = record["context"]["agenda"]
        assert "查摆问题" in agenda and "批评和自我批评" in agenda and "整改方向" in agenda
        assert "谈心谈话" in agenda and "谈心谈话" in record["context"]["notice"]
        assert "讨论安排" not in agenda

        # 用三会一课那三栏冒充组织生活会纪要：送审时必须被拦下
        wrong = await ok(
            client,
            "PATCH",
            f"/meeting/records/{record['id']}",
            {
                "expected_revision": record["revision"],
                "reason": "登记实际召开情况",
                "held_on": f"{year}-09-06",
                "participants": [{"participant_id": "p1", "name": "合成人员甲", "attended": True}],
                "transcript": TRANSCRIPT,
            },
        )
        wrong = await ok(
            client,
            "POST",
            f"/meeting/records/{wrong['id']}/generate-minutes",
            {"expected_revision": wrong["revision"], "reason": "提取纪要"},
        )
        # 三会一课的三栏原文进不了组织生活会纪要：三个栏目都是空的
        assert {key for key, notes in wrong["minutes"].items() if notes} == set()
        response = await client.post(
            f"/api/v1/meeting/records/{wrong['id']}/submit",
            json={"expected_revision": wrong["revision"], "reason": "缺项送审"},
        )
        assert response.status_code == 422
        assert "查摆问题待补" in response.json()["message"]

        record = await ok(
            client,
            "PATCH",
            f"/meeting/records/{wrong['id']}",
            {
                "expected_revision": wrong["revision"],
                "reason": "改按组织生活会记录",
                "transcript": ORG_LIFE_TRANSCRIPT,
            },
        )
        record = await ok(
            client,
            "POST",
            f"/meeting/records/{record['id']}/generate-minutes",
            {"expected_revision": record["revision"], "reason": "逐项提取原文"},
        )
        assert set(record["minutes"]) == {"problems", "criticisms", "rectifications"}
        assert record["missing"] == []
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
                "reason": "核对原文与参会后通过",
                "decision": "approved",
            },
        )
        assert record["execution_status"] == "completed"
    # 组织生活会按年度计频次：这一年有一场审核通过的组织生活会即达标
    async with client_for(life_url, actor()) as (client, _):
        frequency = await ok(client, "GET", "/meeting/frequency")
        row = next(
            item
            for item in frequency["rows"]
            if item["activity_type"] == "organizational_life_meeting"
            and item["org_unit_id"] == "branch-a"
        )
        assert row["period"] == "year" and row["period_label"] == f"{year} 年度"
        assert row["required"] == 1 and row["annual_required"] == 1
        assert row["state"] == "met"

