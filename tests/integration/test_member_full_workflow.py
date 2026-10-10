"""真实 HTTP 与隔离 PostgreSQL 验证模块2（发展党员全流程）；不调用云模型、不写开发业务库。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import date

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
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def member_url(storage_url):
    async def prepare():
        engine = create_async_engine(storage_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:

                def migrate(sync):
                    cfg = Config()
                    cfg.set_main_option("script_location", "migrations")
                    cfg.attributes["connection"] = sync
                    command.upgrade(cfg, "009_member_workflow")

                await connection.run_sync(migrate)
            async with AsyncSession(engine, expire_on_commit=False) as db:
                for tenant_id in ("member-a", "member-b"):
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
                    ("school-a", "member-a", "school", None),
                    ("department-a", "member-a", "department", "school-a"),
                    ("branch-a", "member-a", "branch", "department-a"),
                    ("branch-b", "member-a", "branch", "department-a"),
                    ("school-b", "member-b", "school", None),
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
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    return storage_url


def actor(
    user_id="member-author", role=UserRole.DEPARTMENT_ADMIN, org="department-a", tenant="member-a"
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
    user.knowledge_org_ids = [org, "school-a"] if tenant == "member-a" else [org, "school-b"]
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


async def new_profile(client, name, org="branch-a", stage="applicant", year=None):
    return await ok(
        client,
        "POST",
        "/member/roster",
        {
            "name": name,
            "org_unit_id": org,
            "current_stage": stage,
            "materials": [],
            "pending": 0,
        },
    )


@pytest.mark.asyncio
async def test_batch_roster_material_and_transition_lifecycle(member_url):
    today = date.today().isoformat()
    async with client_for(member_url, actor()) as (client, _):
        batch = await ok(
            client,
            "POST",
            "/member-full/batches",
            {"year": 2026, "batch_no": "B1", "label": "2026年第一批发展对象", "org_unit_id": "branch-a", "reason": "建立年度批次"},
        )
        assert batch["batch_no"] == "B1"
        profile = await new_profile(client, "合成学员甲")
        profile = await ok(
            client,
            "PATCH",
            f"/member-full/profiles/{profile['id']}",
            {"batch_no": "B1", "year": 2026, "reason": "归入年度批次"},
        )
        assert profile["batch_no"] == "B1"
        # 材料记录上传与审核
        for material_type in ("入党申请书", "党组织谈话记录"):
            await ok(
                client,
                "POST",
                f"/member-full/profiles/{profile['id']}/materials",
                {"material_type": material_type, "submit_date": today, "reason": "登记材料"},
            )
        listed = await ok(client, "GET", f"/member-full/profiles/{profile['id']}/materials")
        assert listed["items"] and all(item["review_status"] == "pending" for item in listed["items"])
        for item in listed["items"]:
            if not item.get("legacy_material"):
                await ok(
                    client,
                    "POST",
                    f"/member-full/materials/{item['id']}/review",
                    {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
                )
        # 非法流转被拒（未满足合法顺序）
        response = await client.post(
            "/api/v1" + f"/member-full/profiles/{profile['id']}/transition",
            json={"target_stage": "member", "decision_date": today, "basis": "越权一步到位", "opinion": ""},
        )
        assert response.status_code == 422
        # 材料未齐时流转被拒
        await ok(client, "POST", f"/member-full/profiles/{profile['id']}/materials", {"material_type": "思想汇报", "submit_date": today, "reason": "登记材料"})
        response = await client.post(
            "/api/v1" + f"/member-full/profiles/{profile['id']}/transition",
            json={"target_stage": "candidate", "decision_date": today, "basis": "材料未齐越级", "opinion": ""},
        )
        assert response.status_code == 422
        # 具备全部积极分子材料后流转成功
        profile = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/transition",
            {"target_stage": "activist", "decision_date": today, "basis": "支委会研究确定，培养联系人形成结论", "opinion": "同意列为入党积极分子"},
        )
        assert profile["current_stage"] == "activist"
        detail = await ok(client, "GET", f"/member-full/profiles/{profile['id']}")
        assert detail["stage_history"][-1]["to_stage"] == "activist"
        stats = await ok(client, "GET", "/member-full/stats?year=2026&batch_no=B1")
        assert stats["total"] == 1
        batches = await ok(client, "GET", "/member-full/batches?year=2026")
        assert batches["items"][0]["member_count"] == 1


@pytest.mark.asyncio
async def test_scoring_requires_evidence_and_flags_risks(member_url):
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "合成学员乙")
        for category, score in (("theory_test", 80), ("volunteer_service", 90), ("public_review", 70)):
            record = await ok(
                client,
                "POST",
                f"/member-full/profiles/{profile['id']}/cultivation",
                {
                    "profile_id": profile["id"],
                    "category": category,
                    "score": score,
                    "period": "2026",
                    "source_note": "合成成绩单",
                },
            )
            assert record["category"] == category
        await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/cultivation",
            {
                "profile_id": profile["id"],
                "category": "other",
                "is_risk": True,
                "risk_note": "挂科",
                "period": "2026",
                "source_note": "合成教务记录",
            },
        )
        result = await ok(
            client,
            "POST",
            "/member-full/scoring",
            {"profile_id": profile["id"], "year": 2026},
        )
        assert result["dimensions"]["theory_test"]["value"] == 80.0
        assert result["dimensions"]["party_review"]["status"] == "no_evidence"
        assert "party_review" in result["missing"] and "academic" in result["missing"]
        assert any(row["risk_note"] == "挂科" for row in result["risks"])
        assert result["weighted_score"] is not None
        assert result["dimensions"]["theory_test"]["evidence"][0]["source_id"].startswith("member_cultivation:")


@pytest.mark.asyncio
async def test_votes_deduplicate_and_summarize(member_url):
    async with client_for(member_url, actor()) as (client, _):
        first = await new_profile(client, "投票对象甲")
        second = await new_profile(client, "投票对象乙")
        body = {
            "batch_no": "B1",
            "round_no": 1,
            "votes": [
                {"profile_id": first["id"], "vote": "agree", "comment": "表现积极"},
                {"profile_id": second["id"], "vote": "disagree", "comment": "考察不足"},
            ],
        }
        result = await ok(client, "POST", "/member-full/votes", body)
        assert result["recorded"] == 2
        # 同一投票人重复提交被拒绝
        response = await client.post("/api/v1/member-full/votes", json=body)
        assert response.status_code == 409
    async with client_for(member_url, actor("member-voter2", UserRole.BRANCH_SECRETARY, "branch-a")) as (client, _):
        await ok(
            client,
            "POST",
            "/member-full/votes",
            {
                "batch_no": "B1",
                "round_no": 1,
                "votes": [{"profile_id": first["id"], "vote": "agree", "comment": "同意"}],
            },
        )
        summary = await ok(client, "GET", "/member-full/votes/summary?batch_no=B1&round_no=1")
        assert summary["voter_count"] == 2
        assert summary["tally"][first["id"]]["agree"] == 2


@pytest.mark.asyncio
async def test_reminders_sync_deduplicate_and_resolve(member_url):
    today = date.today().isoformat()
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "提醒对象甲")
        await ok(client, "POST", f"/member-full/profiles/{profile['id']}/materials", {"material_type": "入党申请书", "submit_date": today, "reason": "登记材料"})
        await ok(client, "POST", f"/member-full/profiles/{profile['id']}/materials", {"material_type": "党组织谈话记录", "submit_date": today, "reason": "登记材料"})
        listed = await ok(client, "GET", f"/member-full/profiles/{profile['id']}/materials")
        for item in listed["items"]:
            await ok(
                client,
                "POST",
                f"/member-full/materials/{item['id']}/review",
                {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
            )
        await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/transition",
            {"target_stage": "activist", "decision_date": today, "basis": "支委会研究确定", "opinion": "同意"},
        )
        first = await ok(client, "POST", f"/member-full/profiles/{profile['id']}/sync-reminders")
        assert first["created"] >= 3
        # 重复同步不重复写入
        second = await ok(client, "POST", f"/member-full/profiles/{profile['id']}/sync-reminders")
        assert second["created"] == 0
        listed = await ok(client, "GET", "/member-full/reminders?status=open&page_size=50")
        assert listed["total"] >= first["created"]
        reminder = listed["items"][0]
        resolved = await ok(
            client,
            "POST",
            f"/member-full/reminders/{reminder['id']}/resolve",
            {"status": "closed", "note": "已通知培养联系人"},
        )
        assert resolved["status"] == "closed" and resolved["processed_at"]
        # 已处理的提醒不能重复处理
        response = await client.post(
            "/api/v1" + f"/member-full/reminders/{reminder['id']}/resolve",
            json={"status": "closed", "note": "重复处理"},
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_archive_check_lists_missing_and_risk(member_url):
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "档案检查对象")
        result = await ok(
            client,
            "POST",
            "/member-full/archive-check",
            {
                "profile_id": profile["id"],
                "materials_note": {"入党申请书": "2026年1月1日提交，有本人签字"},
            },
        )
        assert "党组织谈话记录" in result["result"]["missing"]
        assert result["result"]["missing"]
        # 无法识别签字/盖章/日期标记时给出风险提示
        result2 = await ok(
            client,
            "POST",
            "/member-full/archive-check",
            {
                "profile_id": profile["id"],
                "materials_note": {"入党申请书": "只写了几个字", "党组织谈话记录": "无"},
            },
        )
        assert any("风险" in item or "人工核验" in item or "未提供" in item for item in result2["result"]["risks"])


@pytest.mark.asyncio
async def test_org_tenant_scope_and_minimal_role(member_url):
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "范围对象")
        # 跨租户不可访问
    async with client_for(member_url, actor(tenant="member-b", org="school-b")) as (client, _):
        response = await client.get("/api/v1/member-full/profiles/" + profile["id"])
        assert response.status_code == 404
        assert (await client.get("/api/v1/member-full/batches")).status_code == 200
    # 无权限角色被拒绝
    async with client_for(member_url, actor(role=UserRole.MEMBER, org="branch-a")) as (client, _):
        assert (await client.get("/api/v1/member-full/batches")).status_code == 403
        assert (
            await client.post(
                "/api/v1/member-full/scoring",
                json={"profile_id": profile["id"]},
            )
        ).status_code == 403
