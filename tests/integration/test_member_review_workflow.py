"""真实 HTTP 与隔离 PostgreSQL 验证民主评议党员（T-ORG-11）；不调用云模型、不写开发业务库。"""

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
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration

TENANT = "review-a"
BRANCH = "review-branch"
OTHER_BRANCH = "review-branch-other"

# 一人一年一条：每个用例用独立年度，避免同一支部的历史记录互相干扰。
YEAR_MAIN = 2031
YEAR_REQUIREMENTS = 2032
YEAR_ATTENTION = 2033
YEAR_QUEUE = 2034
YEAR_SINGLE = 2040


@pytest.fixture(scope="module")
def review_url(storage_url):
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
                db.add(
                    Tenant(
                        id=TENANT,
                        tenant_id=TENANT,
                        name="合成学校",
                        tenant_type="school",
                        path=TENANT,
                        config={},
                    )
                )
                for org_id, kind, parent in [
                    ("review-school", "school", None),
                    ("review-dept", "department", "review-school"),
                    (BRANCH, "branch", "review-dept"),
                    (OTHER_BRANCH, "branch", "review-school"),
                ]:
                    db.add(
                        OrgUnit(
                            id=org_id,
                            tenant_id=TENANT,
                            name="合成组织-" + org_id,
                            org_type=kind,
                            parent_id=parent,
                            path=org_id,
                        )
                    )
                # 本人查看要落到"账号 → 档案"这条链上，因此账号必须是真实行
                db.add(
                    User(
                        id="review-self",
                        tenant_id=TENANT,
                        username="review-self",
                        name="合成党员本人",
                        password_hash="synthetic",
                        role=UserRole.MEMBER,
                        org_unit_id=BRANCH,
                        is_active=True,
                        is_deleted=False,
                    )
                )
                await db.flush()
                for profile_id, name, stage, active, org, user_id in [
                    ("review-p1", "方案一党员", "member", True, BRANCH, "review-self"),
                    ("review-p2", "方案二党员", "probationary", True, BRANCH, None),
                    ("review-p3", "方案三申请人", "applicant", True, BRANCH, None),
                    ("review-p4", "方案四外支部", "member", True, OTHER_BRANCH, None),
                    ("review-p5", "方案五已停止", "member", False, BRANCH, None),
                ]:
                    db.add(
                        MemberProfile(
                            id=profile_id,
                            tenant_id=TENANT,
                            name=name,
                            org_name="合成组织-" + org,
                            org_unit_id=org,
                            current_stage=stage,
                            stage_joined_on=date(2019, 7, 1),
                            user_id=user_id,
                            materials=[],
                            pending=0,
                            is_active=active,
                        )
                    )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    return storage_url


def actor(user_id, role=UserRole.DEPARTMENT_ADMIN, org="review-dept"):
    user = User(
        id=user_id,
        tenant_id=TENANT,
        username=user_id,
        name="合成组织人员",
        role=role,
        org_unit_id=org,
        is_active=True,
        is_deleted=False,
    )
    user.knowledge_org_ids = [org, "review-school"]
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
    return response.json()["data"]


async def refused(client, method, path, status, body=None, params=None):
    response = await client.request(method, "/api/v1" + path, json=body, params=params)
    assert response.status_code == status, response.text
    return response.json()["message"]


async def workspace(client, year, org_unit_id=BRANCH):
    return await ok(
        client,
        "get",
        "/meeting/member-reviews/workspace",
        params={"year": year, "org_unit_id": org_unit_id},
    )


async def target_of(client, year, review_id):
    data = await workspace(client, year)
    return next(row for row in data["targets"] if row["review_id"] == review_id)


async def revision_of(client, review_id):
    """版本号从服务端读，避免用例自己推算修订次数；顺带验证读取接口可用。"""
    return (await ok(client, "get", f"/meeting/member-reviews/{review_id}"))["revision"]


def recorded(**overrides):
    """一次填齐送审必填项；用例只覆盖自己关心的字段。"""
    values = {
        "procedure": {
            "self_assessment": "本人对照党员标准自评：按时参加组织生活，完成学习任务。",
            "peer_review": "其他党员认为该同志理论学习还需加强。",
            "test": {
                "eligible": 10,
                "attended": 9,
                "outstanding": 2,
                "qualified": 7,
                "basic": 0,
                "unqualified": 0,
            },
            "branch_opinion": "支委会根据评议情况和日常表现，同意评定为合格。",
        },
        "grade": "qualified",
        "basis": "民主测评情况与日常表现",
        "rectification": "继续加强理论学习，按期完成整改。",
        "reason": "录入民主评议结果",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_launch_record_review_and_self_view(review_url):
    admin = actor("review-admin")
    async with client_for(review_url, admin) as (client, _):
        launched = await ok(
            client,
            "post",
            "/meeting/member-reviews/launch",
            {"year": YEAR_MAIN, "org_unit_id": BRANCH, "reason": "按年度发起民主评议"},
        )
        # 正式党员 + 预备党员 = 2；申请人、已停止参加的党员不参加评议
        assert launched["created"] == 2
        assert launched["skipped"] == 0
        assert launched["target_total"] == 2

        data = await workspace(client, YEAR_MAIN)
        assert data["target_total"] == 2
        assert data["progress"]["not_started"] == 0
        assert data["progress"]["draft"] == 2
        assert data["grades"] == {
            "outstanding": 0,
            "qualified": 0,
            "basic": 0,
            "unqualified": 0,
        }
        assert [row["stage_label"] for row in data["targets"]] == ["正式党员", "预备党员"]

        first, second = launched["items"]
        row_id = first["review_id"]
        assert first["missing"] == [
            "个人自评待录",
            "支部评定意见待录",
            "评定等次待定",
            "评定依据待填",
        ]
        assert first["advisories"] == ["未登记党员互评意见", "未登记民主测评票数"]
        assert first["can_review"] is False
        assert second["member_name"] == "方案二党员"

        # 缺项一次说清，不放行
        message = await refused(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            status=422,
            body={"expected_revision": first["revision"], "reason": "第一次送审"},
        )
        assert message == "个人自评待录；支部评定意见待录；评定等次待定；评定依据待填"

        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {"expected_revision": first["revision"], **recorded()},
        )
        fetched = await ok(client, "get", f"/meeting/member-reviews/{row_id}")
        assert fetched["review_status"] == "draft"
        assert fetched["revision"] == first["revision"] + 1
        assert fetched["missing"] == []
        assert fetched["advisories"] == []
        assert fetched["grade_label"] == "合格"
        # 字段级敏感分级（T-MEM-12）：详情带密级与出网 / 向量化口径；同级查看者仍看得到互评
        assert fetched["data_level"] == "sensitive" and fetched["data_level_label"] == "敏感"
        assert fetched["cloud_allowed"] is False and fetched["embedding_allowed"] is True
        assert fetched["redacted_fields"] == []
        assert fetched["procedure"]["peer_review"].startswith("其他党员认为")

        revision = await revision_of(client, row_id)
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            {"expected_revision": revision, "reason": "录入完成送审"},
        )
        self_review = await refused(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            status=403,
            body={
                "expected_revision": await revision_of(client, row_id),
                "decision": "approved",
                "reason": "自审",
            },
        )
        assert "另一位" in self_review

    reviewer = actor("review-reviewer", UserRole.BRANCH_SECRETARY, BRANCH)
    async with client_for(review_url, reviewer) as (client, _):
        pending = await target_of(client, YEAR_MAIN, row_id)
        assert pending["review_status"] == "pending"
        assert pending["can_review"] is True
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            {
                "expected_revision": await revision_of(client, row_id),
                "decision": "approved",
                "reason": "材料齐全，同意评定",
            },
        )
        data = await workspace(client, YEAR_MAIN)
        assert data["progress"]["approved"] == 1
        assert data["progress"]["draft"] == 1
        assert data["grades"]["qualified"] == 1
        assert data["outstanding"] == 0
        assert data["outstanding_ratio"] == 0.0
        assert data["attention"] == []
        assert "系统不自动" in data["notices"]["outstanding_notice"]
        assert "党章党规" in data["notices"]["unqualified_notice"]

    # 本人只能看到自己已生效的结果
    self_user = actor("review-self", UserRole.MEMBER, BRANCH)
    async with client_for(review_url, self_user) as (client, _):
        data = await ok(client, "get", "/member/self/reviews", params={"year": YEAR_MAIN})
        assert [item["grade_label"] for item in data["items"]] == ["合格"]
        assert data["items"][0]["year"] == YEAR_MAIN
        other_year = await ok(client, "get", "/member/self/reviews", params={"year": 2029})
        assert other_year["items"] == []

    async with client_for(review_url, admin) as (client, _):
        again = await ok(
            client,
            "post",
            "/meeting/member-reviews/launch",
            {"year": YEAR_MAIN, "org_unit_id": BRANCH, "reason": "重复发起不覆盖"},
        )
        # 已录入并审核过的记录不会被二次发起清成草稿
        assert again["created"] == 0
        assert again["skipped"] == 2
        kept = await target_of(client, YEAR_MAIN, row_id)
        assert kept["review_status"] == "approved"
        assert kept["grade"] == "qualified"


@pytest.mark.asyncio
async def test_out_of_scope_org_is_rejected(review_url):
    secretary = actor("review-secretary", UserRole.BRANCH_SECRETARY, BRANCH)
    async with client_for(review_url, secretary) as (client, _):
        message = await refused(
            client,
            "post",
            "/meeting/member-reviews/launch",
            status=403,
            body={"year": YEAR_MAIN, "org_unit_id": OTHER_BRANCH, "reason": "越权发起"},
        )
        assert "权限范围" in message
        # 只看得到本支部：另一个支部的评议对象不会出现在工作区
        data = await workspace(client, YEAR_MAIN, org_unit_id=BRANCH)
        assert {row["org_unit_id"] for row in data["targets"]} == {BRANCH}
        denied = await refused(
            client,
            "get",
            f"/meeting/member-reviews/{'nonexistent'}",
            status=404,
        )
        assert "不存在" in denied


@pytest.mark.asyncio
async def test_submission_requires_the_blocking_fields(review_url):
    admin = actor("review-admin")
    async with client_for(review_url, admin) as (client, _):
        # 等次不在制度口径内：请求体本身就被拒绝
        await refused(
            client,
            "post",
            "/meeting/member-reviews",
            status=422,
            body={
                "year": YEAR_SINGLE,
                "profile_id": "review-p1",
                "grade": "excellent",
                "reason": "等次不在制度口径内",
            },
        )
        # 申请人不是评议对象
        await refused(
            client,
            "post",
            "/meeting/member-reviews",
            status=422,
            body={"year": YEAR_SINGLE, "profile_id": "review-p3", "reason": "申请人不成评议对象"},
        )

        launched = await ok(
            client,
            "post",
            "/meeting/member-reviews/launch",
            {"year": YEAR_REQUIREMENTS, "org_unit_id": BRANCH, "reason": "按年度发起"},
        )
        row_id = launched["items"][0]["review_id"]
        await refused(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            status=422,
            body={"expected_revision": 1, "reason": "缺项送审"},
        )
        # 只写空白不算内容：可以存成草稿，但送审时仍按缺项拦下
        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {
                "expected_revision": 1,
                "procedure": {"self_assessment": "  ", "branch_opinion": " "},
                "grade": "qualified",
                "basis": " ",
                "reason": "空白内容",
            },
        )
        blank = await refused(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            status=422,
            body={"expected_revision": await revision_of(client, row_id), "reason": "空白内容送审"},
        )
        assert blank == "个人自评待录；支部评定意见待录；评定依据待填"
        # 测评票数自相矛盾：实到多于应到、票数多于实到
        await refused(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            status=422,
            body={
                "expected_revision": await revision_of(client, row_id),
                **recorded(procedure={"test": {"eligible": 5, "attended": 6}}),
            },
        )
        await refused(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            status=422,
            body={
                "expected_revision": await revision_of(client, row_id),
                **recorded(
                    procedure={"test": {"eligible": 5, "attended": 4, "outstanding": 3, "qualified": 2}}
                ),
            },
        )
        # 不一致的版本号不能被静默覆盖
        message = await refused(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            status=409,
            body={"expected_revision": 7, **recorded()},
        )
        assert "已被修订" in message

        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {"expected_revision": await revision_of(client, row_id), **recorded()},
        )
        # 互评与测评只作提示：不登记也允许送审（线上线下混用时不逼组织编造）
        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {
                "expected_revision": await revision_of(client, row_id),
                "procedure": {
                    "self_assessment": "本人自评。",
                    "peer_review": "",
                    "test": None,
                    "branch_opinion": "支委会同意评定为合格。",
                },
                "grade": "qualified",
                "basis": "日常表现",
                "rectification": "",
                "reason": "线下开展，票数未汇总",
            },
        )
        submitted = await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            {"expected_revision": await revision_of(client, row_id), "reason": "线下评议完成"},
        )
        assert submitted["review_status"] == "pending"

    reviewer = actor("review-reviewer-2", UserRole.BRANCH_SECRETARY, BRANCH)
    async with client_for(review_url, reviewer) as (client, _):
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            {
                "expected_revision": await revision_of(client, row_id),
                "decision": "rejected",
                "reason": "支部意见需要补充依据",
            },
        )
        # 同一版本不能重复审核
        await refused(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            status=409,
            body={
                "expected_revision": await revision_of(client, row_id),
                "decision": "approved",
                "reason": "重复审核",
            },
        )
        rejected = await ok(client, "get", f"/meeting/member-reviews/{row_id}")
        assert rejected["review_status"] == "rejected"
        # 发起 → 修订 → 送审 → 审核：每一次写操作都留下一版完整快照，编号只增不减
        revisions = rejected["revisions"]
        assert revisions[0]["action"] == "review"
        assert revisions[-1]["action"] == "launch"
        assert {item["action"] for item in revisions} == {"launch", "revise", "submit", "review"}
        assert [item["revision"] for item in revisions] == list(range(len(revisions), 0, -1))
        assert rejected["revision"] == len(revisions)
        assert all(item["actor_id"] for item in revisions)

    async with client_for(review_url, admin) as (client, _):
        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {
                "expected_revision": await revision_of(client, row_id),
                **recorded(basis="民主测评情况、日常表现与支部研究结论"),
            },
        )
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            {"expected_revision": await revision_of(client, row_id), "reason": "补充依据后重新送审"},
        )

    async with client_for(review_url, reviewer) as (client, _):
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            {
                "expected_revision": await revision_of(client, row_id),
                "decision": "approved",
                "reason": "依据已补充，同意",
            },
        )
        approved = await ok(client, "get", f"/meeting/member-reviews/{row_id}")
        assert approved["review_status"] == "approved"
        assert approved["review_comment"] == "依据已补充，同意"


@pytest.mark.asyncio
async def test_low_grades_are_flagged_for_research(review_url):
    admin = actor("review-admin")
    async with client_for(review_url, admin) as (client, _):
        launched = await ok(
            client,
            "post",
            "/meeting/member-reviews/launch",
            {"year": YEAR_ATTENTION, "org_unit_id": BRANCH, "reason": "按年度发起"},
        )
        probationary = next(row for row in launched["items"] if row["member_name"] == "方案二党员")
        row_id = probationary["review_id"]
        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {"expected_revision": probationary["revision"], **recorded(grade="unqualified")},
        )
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/submit",
            {"expected_revision": await revision_of(client, row_id), "reason": "送审"},
        )

    reviewer = actor("review-reviewer-3", UserRole.BRANCH_SECRETARY, BRANCH)
    async with client_for(review_url, reviewer) as (client, _):
        await ok(
            client,
            "post",
            f"/meeting/member-reviews/{row_id}/review",
            {
                "expected_revision": await revision_of(client, row_id),
                "decision": "approved",
                "reason": "情况属实",
            },
        )
        data = await workspace(client, YEAR_ATTENTION)
        assert data["grades"]["unqualified"] == 1
        assert [item["member_name"] for item in data["attention"]] == ["方案二党员"]
        assert data["attention"][0]["grade_label"] == "不合格"
        assert data["attention"][0]["rectification"] == "继续加强理论学习，按期完成整改。"
        # 系统只提示"须研究处置"，不生成处置意见
        assert "研究决定" in data["notices"]["unqualified_notice"]
        assert "系统不自动生成" in data["notices"]["unqualified_notice"]


@pytest.mark.asyncio
async def test_unified_review_queue_carries_member_reviews(review_url):
    admin = actor("review-admin")
    async with client_for(review_url, admin) as (client, _):
        launched = await ok(
            client,
            "post",
            "/meeting/member-reviews/launch",
            {"year": YEAR_QUEUE, "org_unit_id": BRANCH, "reason": "按年度发起"},
        )
        row_id = launched["items"][0]["review_id"]
        await ok(
            client,
            "patch",
            f"/meeting/member-reviews/{row_id}",
            {"expected_revision": launched["items"][0]["revision"], **recorded()},
        )
        queued = await ok(
            client,
            "post",
            "/admin/reviews",
            {"source_kind": "member_review", "source_id": row_id},
        )
        assert queued["status"] == "pending"
        assert queued["source_kind"] == "member_review"
        source_version = queued["source_version"]
        # 统一入口送审不能绕过业务侧必填项与状态机
        source = await ok(client, "get", f"/meeting/member-reviews/{row_id}")
        assert source["review_status"] == "pending"
        assert source["submitted_by"] == "review-admin"

    other = actor("review-admin-2")
    async with client_for(review_url, other) as (client, _):
        detail = await ok(client, "get", f"/admin/reviews/{queued['id']}")
        assert detail["source_version"] == source_version
        decided = await ok(
            client,
            "post",
            f"/admin/reviews/{queued['id']}/decision",
            {
                "decision": "approved",
                "source_version": source_version,
                "opinion": "统一审核队列通过",
            },
        )
        assert decided["status"] == "approved"
        source = await ok(client, "get", f"/meeting/member-reviews/{row_id}")
        assert source["review_status"] == "approved"

    self_user = actor("review-self", UserRole.MEMBER, BRANCH)
    async with client_for(review_url, self_user) as (client, _):
        data = await ok(client, "get", "/member/self/reviews", params={"year": YEAR_QUEUE})
        assert [item["grade_label"] for item in data["items"]] == ["合格"]
