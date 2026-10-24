"""真实 HTTP 与隔离 PostgreSQL 验证选优结论与团组织推优（T-MEM-13、T-MEM-06）。

覆盖三条不可退让的口径：结论由人登记（系统不按票数自动出名单）、**必须第二位组织人员
审核**（自审被拒、未送审不能审、过期版本不能覆盖）、团组织推优只登记不判断年龄且不阻断
业务；另外验证生效结论**不自动改阶段**、跨租户不可见与依据快照里没有投票人身份。
"""

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
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def selection_url(storage_url):
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
                for tenant_id in ("sel-a", "sel-b"):
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
                    ("sel-school", "sel-a", "school", None),
                    ("sel-department", "sel-a", "department", "sel-school"),
                    ("sel-branch", "sel-a", "branch", "sel-department"),
                    ("sel-branch2", "sel-a", "branch", "sel-department"),
                    ("sel-other-school", "sel-b", "school", None),
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
    user_id="sel-author",
    role=UserRole.DEPARTMENT_ADMIN,
    org="sel-department",
    tenant="sel-a",
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
    user.knowledge_org_ids = [org, "sel-school"]
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


async def new_profile(client, name, org="sel-branch", stage="activist"):
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


def conclusion_body(candidate_ids, **overrides):
    body = {
        "batch_no": "SEL-1",
        "round_no": 1,
        "target_stage": "candidate",
        "candidate_ids": candidate_ids,
        "basis": "依据本轮选优投票汇总与培养记录，经支委会研究",
        "research_on": date.today().isoformat(),
        "research_method": "committee",
        "reason": "支委会研究登记拟推荐名单",
    }
    return {**body, **overrides}


async def assert_stage_unchanged(client, profile_id, name):
    profile = await ok(client, "GET", f"/member-full/profiles/{profile_id}")
    assert profile["current_stage"] == "activist"
    assert profile["name"] == name


@pytest.mark.asyncio
async def test_conclusion_requires_second_reviewer_and_never_auto_concludes(selection_url):
    async with client_for(selection_url, actor()) as (client, _):
        first = await new_profile(client, "选优对象甲")
        second = await new_profile(client, "选优对象乙")
        # 本轮投票（无记名）：登记结论时其无记名汇总会作为依据快照
        await ok(
            client,
            "POST",
            "/member-full/votes",
            {
                "batch_no": "SEL-1",
                "round_no": 1,
                "votes": [
                    {"profile_id": first["id"], "vote": "agree", "comment": "表现积极"},
                    {"profile_id": second["id"], "vote": "agree", "comment": "同意"},
                ],
            },
        )
        created = await ok(
            client,
            "POST",
            "/member-full/selections",
            conclusion_body([first["id"], second["id"]]),
        )
        # 登记出来的是草稿：没有被任何人审核过，不能当认定依据
        assert created["review_status"] == "draft"
        assert created["effective"] is False
        assert created["can_review"] is False
        assert created["candidate_count"] == 2
        assert created["target_stage_label"] == "发展对象"
        assert created["research_method_label"] == "支委会"
        # 名单就是人给的那两个人：服务端不按票数自动补人、也不回"自动入选/排名"结论
        assert [item["profile_id"] for item in created["candidates"]] == [
            first["id"],
            second["id"],
        ]
        assert set(created["evidence"]["tally"]) == {first["id"], second["id"]}
        # 依据快照是无记名口径：只有票数与投票人数，没有投票人身份
        assert created["evidence"]["voter_count"] == 1
        assert created["evidence"]["tally"][first["id"]]["agree"] == 1
        assert set(created["evidence"]["tally"][first["id"]]) == {
            "agree",
            "disagree",
            "abstain",
        }
        # 依据快照里没有投票人身份（操作人只出现在只追加留痕里，那是审计本来就需要的）
        assert "sel-author" not in str(created["evidence"])
        # 密级与边界标注：敏感级、不出网；不自动改阶段、不自动报送
        assert created["data_level"] == "sensitive" and created["cloud_allowed"] is False
        assert "不自动改阶段" in created["boundary"]
        assert "台账" in created["next_step_hint"]
        record_id = created["id"]

        submitted = await ok(
            client,
            "POST",
            f"/member-full/selections/{record_id}/submit",
            {"expected_revision": created["revision"], "reason": "报另一位组织人员审核"},
        )
        assert submitted["review_status"] == "pending"
        assert submitted["effective"] is False
        # 自己提交的不能自己审：界面标记与接口都拦
        assert submitted["can_review"] is False
        own = await client.post(
            "/api/v1" + f"/member-full/selections/{record_id}/review",
            json={
                "expected_revision": submitted["revision"],
                "decision": "approved",
                "reason": "我自己通过",
            },
        )
        assert own.status_code == 403
        # 名单人选阶段的快照要留下来（人员后续流转后仍读得回去）
        assert submitted["candidates"][0]["stage"] == "activist"
        await assert_stage_unchanged(client, first["id"], "选优对象甲")

    # 第二位组织人员（另一个人）审核通过
    async with client_for(selection_url, actor("sel-reviewer")) as (client, _):
        detail = await ok(client, "GET", f"/member-full/selections/{record_id}")
        assert detail["can_review"] is True
        approved = await ok(
            client,
            "POST",
            f"/member-full/selections/{record_id}/review",
            {
                "expected_revision": detail["revision"],
                "decision": "approved",
                "reason": "名单与依据核对无误",
            },
        )
        assert approved["review_status"] == "approved"
        assert approved["effective"] is True
        assert approved["can_review"] is False
        assert approved["reviewed_by"] == "sel-reviewer"
        assert approved["reviewed_at"]
        assert approved["review_comment"] == "名单与依据核对无误"
        # 只追加留痕：登记 / 送审 / 审核三次动作都能读回
        assert [item["action"] for item in approved["revisions"]] == [
            "create",
            "submit",
            "review",
        ]
        assert [item["revision"] for item in approved["revisions"]] == [1, 2, 3]
        # 结论生效不等于阶段流转：档案阶段仍是"入党积极分子"
        await assert_stage_unchanged(client, first["id"], "选优对象甲")
        # 台账按批次筛选能把这份结论读回来（同一批次只有这一份）
        listed = await ok(client, "GET", "/member-full/selections?batch_no=SEL-1")
        assert listed["total"] == 1 and listed["summary"]["approved"] == 1

    # 跨租户看不到，也无从登记
    async with client_for(
        selection_url, actor("sel-outsider", org="sel-other-school", tenant="sel-b")
    ) as (client, _):
        listed = await ok(client, "GET", "/member-full/selections?batch_no=SEL-1")
        assert listed["total"] == 0

    # 普通党员连读都不行（不返回别人的拟推荐名单）
    async with client_for(selection_url, actor("sel-member", UserRole.MEMBER)) as (client, _):
        response = await client.get("/api/v1/member-full/selections")
        assert response.status_code == 403
        response = await client.post(
            "/api/v1" + f"/member-full/selections/{record_id}/review",
            json={"expected_revision": 3, "decision": "rejected", "reason": "越权审核"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_revision_after_submit_forces_another_review_and_rejects_stale_versions(
    selection_url,
):
    async with client_for(selection_url, actor("sel-author2")) as (client, _):
        profile = await new_profile(client, "改稿对象")
        created = await ok(
            client,
            "POST",
            "/member-full/selections",
            conclusion_body([profile["id"]], batch_no="SEL-2"),
        )
        submitted = await ok(
            client,
            "POST",
            f"/member-full/selections/{created['id']}/submit",
            {"expected_revision": 1, "reason": "送审"},
        )
        pending_id = submitted["id"]
        # 未送审的草稿不能直接审核
        draft = await ok(
            client,
            "POST",
            "/member-full/selections",
            conclusion_body([profile["id"]], batch_no="SEL-2B"),
        )
        too_early = await client.post(
            "/api/v1" + f"/member-full/selections/{draft['id']}/review",
            json={"expected_revision": 1, "decision": "approved", "reason": "直接通过"},
        )
        assert too_early.status_code == 409
        # 修订已送审的版本 → 回到草稿，必须重新送审
        revised = await ok(
            client,
            "PATCH",
            f"/member-full/selections/{pending_id}",
            {
                "expected_revision": 2,
                "basis": "依据第 2 轮投票汇总（票数有变化）",
                "research_method": "member_meeting",
                "reason": "党员大会后补充依据",
            },
        )
        assert revised["review_status"] == "draft"
        assert revised["submitted_by"] is None
        assert revised["research_method_label"] == "党员大会"
        # 过期版本号被拒：不覆盖别人已经改过的内容
        stale = await client.patch(
            "/api/v1" + f"/member-full/selections/{pending_id}",
            json={"expected_revision": 2, "basis": "拿旧版本号覆盖", "reason": "过期版本"},
        )
        assert stale.status_code == 409
        # 改完不送审就审核 → 仍被拒
        skipped = await client.post(
            "/api/v1" + f"/member-full/selections/{pending_id}/review",
            json={"expected_revision": 3, "decision": "approved", "reason": "跳过送审"},
        )
        assert skipped.status_code == 409
        # 重新送审后由另一个人审核
        await ok(
            client,
            "POST",
            f"/member-full/selections/{pending_id}/submit",
            {"expected_revision": 3, "reason": "重新送审"},
        )

    async with client_for(selection_url, actor("sel-reviewer2")) as (client, _):
        detail = await ok(client, "GET", f"/member-full/selections/{pending_id}")
        assert detail["review_status"] == "pending" and detail["can_review"] is True
        approved = await ok(
            client,
            "POST",
            f"/member-full/selections/{pending_id}/review",
            {
                "expected_revision": detail["revision"],
                "decision": "approved",
                "reason": "核对通过",
            },
        )
        assert approved["effective"] is True
        # 修订留下的历史版本仍在：能被读回并标出动作
        assert [item["action"] for item in approved["revisions"]] == [
            "create",
            "submit",
            "revise",
            "submit",
            "review",
        ]


@pytest.mark.asyncio
async def test_selection_rejects_backward_stage_and_out_of_scope_candidates(selection_url):
    async with client_for(selection_url, actor("sel-author3")) as (client, _):
        candidate = await new_profile(client, "已到发展对象", stage="candidate")
        # 目标阶段必须向前：同阶段不许登记
        response = await client.post(
            "/api/v1/member-full/selections",
            json=conclusion_body([candidate["id"]], batch_no="SEL-3"),
        )
        assert response.status_code == 422
        assert "不能登记为拟推荐名单" in str(response.json())
        # 研究日期不能在未来
        activist = await new_profile(client, "未到发展对象")
        response = await client.post(
            "/api/v1/member-full/selections",
            json=conclusion_body(
                [activist["id"]],
                batch_no="SEL-3",
                research_on=(date.today() + timedelta(days=3)).isoformat(),
            ),
        )
        assert response.status_code == 422
        # 空名单与空依据不进库
        response = await client.post(
            "/api/v1/member-full/selections",
            json=conclusion_body([], batch_no="SEL-3"),
        )
        assert response.status_code == 422
        response = await client.post(
            "/api/v1/member-full/selections",
            json=conclusion_body([activist["id"]], batch_no="SEL-3", basis="   "),
        )
        assert response.status_code == 422

    async with client_for(
        selection_url, actor("sel-outsider2", org="sel-other-school", tenant="sel-b")
    ) as (client, _):
        response = await client.post(
            "/api/v1/member-full/selections",
            json=conclusion_body([candidate["id"]], batch_no="SEL-3"),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_league_recommendation_records_facts_without_judging_age(selection_url):
    async with client_for(selection_url, actor("sel-author4")) as (client, _):
        profile = await new_profile(client, "推优对象")
        other = await new_profile(client, "无推优对象")
        created = await ok(
            client,
            "POST",
            "/member-full/league-recommendations",
            {
                "profile_id": profile["id"],
                "league_org": "某某学院团委",
                "recommended_on": date.today().isoformat(),
                "note": "团支书反映该同志在校表现积极，团支部大会推荐入党",
                "reason": "登记团组织推优材料",
            },
        )
        assert created["active"] is True
        assert created["stage"] == "activist"
        # 系统判不了年龄：只提示"请组织核对"，不做任何年龄校验
        assert "系统不判断年龄" in created["age_notice"]
        assert "不阻断" in created["age_notice"]
        assert created["data_level"] == "sensitive"

        # 推荐日期不能在未来
        response = await client.post(
            "/api/v1/member-full/league-recommendations",
            json={
                "profile_id": other["id"],
                "league_org": "某某学院团委",
                "recommended_on": (date.today() + timedelta(days=1)).isoformat(),
                "note": "",
                "reason": "未来日期",
            },
        )
        assert response.status_code == 422

        # 按人查询"有没有推优记录"：只回标记，不判断年龄、不阻断
        status = await ok(
            client,
            "GET",
            f"/member-full/league-recommendations?profile_ids={profile['id']},{other['id']}",
        )
        by_profile = {item["profile_id"]: item for item in status["status"]}
        assert by_profile[profile["id"]]["has_record"] is True
        assert by_profile[profile["id"]]["latest_org"] == "某某学院团委"
        assert by_profile[other["id"]]["has_record"] is False
        assert by_profile[other["id"]]["active_count"] == 0

        # 选优结论可以照常登记：缺推优记录只提示，不阻断
        conclusion = await ok(
            client,
            "POST",
            "/member-full/selections",
            conclusion_body([profile["id"], other["id"]], batch_no="SEL-4"),
        )
        assert any("尚无团组织推优记录" in text for text in conclusion["advisories"])
        assert conclusion["missing"] == []
        await ok(
            client,
            "POST",
            f"/member-full/selections/{conclusion['id']}/submit",
            {"expected_revision": 1, "reason": "缺推优记录也允许送审"},
        )

        # 作废：记录保留、理由必填，重复作废被拒
        revoked = await ok(
            client,
            "POST",
            f"/member-full/league-recommendations/{created['id']}/revoke",
            {"reason": "推荐单位填错，重新登记"},
        )
        assert revoked["active"] is False
        assert revoked["revoked_on"] and revoked["revoke_reason"] == "推荐单位填错，重新登记"
        again = await client.post(
            "/api/v1" + f"/member-full/league-recommendations/{created['id']}/revoke",
            json={"reason": "再作废一次"},
        )
        assert again.status_code == 409
        after = await ok(
            client,
            "GET",
            f"/member-full/league-recommendations?profile_ids={profile['id']}",
        )
        assert after["status"][0]["has_record"] is False
        assert after["summary"] == {"total": 1, "active": 0, "revoked": 1}
