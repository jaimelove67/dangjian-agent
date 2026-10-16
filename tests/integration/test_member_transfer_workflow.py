"""真实 HTTP 与隔离 PostgreSQL 验证组织关系接转（T-MEM-14）；不调用云模型、不写开发业务库。"""

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
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url

pytestmark = pytest.mark.integration

TENANT = "transfer-a"
SCHOOL = "transfer-school"
DEPT = "transfer-dept"
BRANCH = "transfer-branch"
OTHER = "transfer-other"

TODAY = date.today()
# 每个年度只用一个评议年度即可；本文件不关心年度口径。
YEAR = 2038


@pytest.fixture(scope="module")
def transfer_url(storage_url):
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
                    (SCHOOL, "school", None),
                    (DEPT, "department", SCHOOL),
                    (BRANCH, "branch", DEPT),
                    (OTHER, "branch", SCHOOL),
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
                for profile_id, name, stage, org, active in [
                    ("tr-out", "转出党员", "member", BRANCH, True),
                    ("tr-probationary", "预备党员", "probationary", BRANCH, True),
                    ("tr-applicant", "培养对象", "applicant", BRANCH, True),
                    ("tr-keep", "留下党员", "member", BRANCH, True),
                    ("tr-pending", "待接收党员", "member", BRANCH, True),
                    ("tr-revoked", "作废党员", "member", BRANCH, True),
                    ("tr-other", "另一支部党员", "member", OTHER, True),
                    # 越权用例专用：始终留在另一个支部，不受前面用例的支部调动影响
                    ("tr-hidden", "范围外党员", "member", OTHER, True),
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


def actor(user_id, role=UserRole.DEPARTMENT_ADMIN, org=DEPT):
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
    user.knowledge_org_ids = [org, SCHOOL]
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


def letter(**overrides):
    """一次登记的完整介绍信要素：用例只覆盖自己关心的字段。"""
    values = {
        "letter_no": "转字2026-001",
        "counterpart_org": "合成外校党委",
        "issued_on": (TODAY - timedelta(days=10)).isoformat(),
        "reason": "办理组织关系转出",
    }
    values.update(overrides)
    return values


async def roster(client, **params):
    return await ok(client, "get", "/member/roster", params=params or None)


async def review_targets(client, year=YEAR, org_unit_id=BRANCH):
    data = await ok(
        client,
        "get",
        "/meeting/member-reviews/workspace",
        params={"year": year, "org_unit_id": org_unit_id},
    )
    return [row["profile_id"] for row in data["targets"]]


@pytest.mark.asyncio
async def test_outgoing_letter_waits_for_receipt_then_leaves_the_roster(transfer_url):
    admin = actor("transfer-admin")
    async with client_for(transfer_url, admin) as (client, _):
        before = await roster(client)
        assert "tr-out" in {item["id"] for item in before["items"]}

        created = await ok(
            client,
            "post",
            "/member-full/transfers",
            {"direction": "out", "profile_id": "tr-out", **letter()},
        )
        assert created["status"] == "pending"
        assert created["status_label"] == "待接收"
        # 开介绍信不等于转出完成：状态停在待接收，且此时还算是本组织党员
        assert created["state"] == "out_pending"
        assert created["state_label"] == "转出待接收"
        assert created["overdue"] is False
        assert created["valid_until"] == (TODAY - timedelta(days=10) + timedelta(days=90)).isoformat()
        assert created["days_left"] == 80
        assert "回执后才算转出完成" in created["notice"]
        transfer_id = created["id"]

        pending = await roster(client)
        marked = next(item for item in pending["items"] if item["id"] == "tr-out")
        assert marked["relation_status"] == "out_pending"
        assert "tr-out" in await review_targets(client)

        settled = await ok(
            client,
            "post",
            f"/member-full/transfers/{transfer_id}/settle",
            {"receipt_no": "回执2026-088", "reason": "收到接收组织回执"},
        )
        assert settled["status"] == "settled"
        assert settled["state"] == "transferred_out"
        assert settled["settled_on"] == TODAY.isoformat()
        assert "不再计入本组织在册名单" in settled["notice"]

        # 名册默认不含已转出：他们已不属于本组织在册党员
        after = await roster(client)
        assert "tr-out" not in {item["id"] for item in after["items"]}
        assert after["total"] == before["total"] - 1
        # 需要查历史时显式勾选，且带标识说明为什么他不算在册
        kept = await roster(client, include_transferred=True)
        historical = next(item for item in kept["items"] if item["id"] == "tr-out")
        assert historical["relation_status"] == "transferred_out"
        assert kept["total"] == before["total"]

        stats = await ok(client, "get", "/member-full/stats")
        assert stats["total"] == after["total"]
        assert "tr-out" not in await review_targets(client)

        # 已回执的接转不能重复回执
        assert "已回执" in await refused(
            client,
            "post",
            f"/member-full/transfers/{transfer_id}/settle",
            status=409,
            body={"reason": "重复回执"},
        )
        detail = await ok(client, "get", f"/member-full/transfers/{transfer_id}")
        assert [item["action"] for item in detail["history"]] == ["create", "settle"]
        assert all(item["actor_id"] == "transfer-admin" for item in detail["history"])

        # 关系已经转走，不能对同一个人再开一封介绍信（重复转出）
        assert "已转出" in await refused(
            client,
            "post",
            "/member-full/transfers",
            status=409,
            body={
                "direction": "out",
                "profile_id": "tr-out",
                **letter(letter_no="转字2026-008", counterpart_org="合成外校党委"),
            },
        )

        # 后来关系又转回本校同一支部：状态从"已转出"回到"在册"，不会被上一次粘住
        back = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "in",
                "profile_id": "tr-out",
                "org_unit_id": BRANCH,
                **letter(letter_no="转字2026-009", counterpart_org="合成外校党委"),
            },
        )
        assert back["state"] == "in_place"
        assert back["created_profile"] is False
        assert "tr-out" in {item["id"] for item in (await roster(client))["items"]}


@pytest.mark.asyncio
async def test_revoking_a_letter_puts_the_member_back(transfer_url):
    admin = actor("transfer-admin")
    async with client_for(transfer_url, admin) as (client, _):
        created = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "out",
                "profile_id": "tr-revoked",
                **letter(letter_no="转字2026-010", counterpart_org="合成另一单位党委"),
            },
        )
        assert created["state"] == "out_pending"
        assert "tr-revoked" not in {
            item["id"]
            for item in (await roster(client, include_transferred=True))["items"]
            if item["relation_status"] == "transferred_out"
        }
        pending = next(
            item for item in (await roster(client))["items"] if item["id"] == "tr-revoked"
        )
        assert pending["relation_status"] == "out_pending"

        revoked = await ok(
            client,
            "post",
            f"/member-full/transfers/{created['id']}/revoke",
            {"reason": "介绍信抬头写错，重新开具"},
        )
        assert revoked["status"] == "revoked"
        assert revoked["state"] == "in_place"
        assert revoked["state_label"] == "在册"
        assert "记录保留可查" in revoked["notice"]

        # 作废视同未发生：人还在名册里，也不是已转出
        listed = next(
            item for item in (await roster(client))["items"] if item["id"] == "tr-revoked"
        )
        assert listed["relation_status"] == "in_place"

        assert "已作废" in await refused(
            client,
            "post",
            f"/member-full/transfers/{created['id']}/revoke",
            status=409,
            body={"reason": "重复作废"},
        )
        assert "已作废" in await refused(
            client,
            "post",
            f"/member-full/transfers/{created['id']}/settle",
            status=409,
            body={"reason": "作废后回执"},
        )
        detail = await ok(client, "get", f"/member-full/transfers/{created['id']}")
        assert [item["action"] for item in detail["history"]] == ["create", "revoke"]
        assert detail["revoke_reason"] == "介绍信抬头写错，重新开具"


@pytest.mark.asyncio
async def test_incoming_transfer_creates_a_profile_and_lists_the_archive(transfer_url):
    school = actor("transfer-school-admin", UserRole.SCHOOL_ADMIN, SCHOOL)
    async with client_for(transfer_url, school) as (client, _):
        incoming = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "in",
                "name": "合成转入党员",
                "org_unit_id": BRANCH,
                "current_stage": "member",
                "stage_joined_on": "2020-07-01",
                "letter_no": "转入字2026-021",
                "counterpart_org": "合成外校党委",
                "issued_on": (TODAY - timedelta(days=5)).isoformat(),
                "reason": "接收组织关系转入",
            },
        )
        assert incoming["created_profile"] is True
        assert incoming["state"] == "in_place"
        # 转入要核对档案：清单按阶段沿既有材料要求累加，缺项一次说清
        archive = incoming["archive"]
        assert archive["check_id"]
        assert len(archive["required"]) == 12
        assert "入党申请书" in archive["required"]
        assert "转正申请书" in archive["required"]
        assert archive["missing"] == archive["required"]
        assert "待核对档案" in incoming["notice"]

        listed = next(
            item
            for item in (await roster(client))["items"]
            if item["name"] == "合成转入党员"
        )
        assert listed["stage"] == "member"
        assert listed["org_unit_id"] == BRANCH
        assert listed["relation_status"] == "in_place"
        assert "合成转入党员" in [
            row["member_name"]
            for row in (
                await ok(
                    client,
                    "get",
                    "/meeting/member-reviews/workspace",
                    params={"year": YEAR, "org_unit_id": BRANCH},
                )
            )["targets"]
        ]

        # 同一学校内支部之间调动：关联既有档案，档案归属改到接收组织
        moved = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "in",
                "profile_id": "tr-other",
                "org_unit_id": BRANCH,
                "letter_no": "转入字2026-022",
                "counterpart_org": "合成组织-" + OTHER,
                "issued_on": (TODAY - timedelta(days=3)).isoformat(),
                "reason": "校内支部之间调整",
            },
        )
        assert moved["created_profile"] is False
        assert moved["state"] == "in_place"
        relocated = next(
            item for item in (await roster(client))["items"] if item["id"] == "tr-other"
        )
        assert relocated["org_unit_id"] == BRANCH
        assert "tr-other" in await review_targets(client)

        # 回执只表示档案核对完成，不改变"在册"这一事实
        done = await ok(
            client,
            "post",
            f"/member-full/transfers/{moved['id']}/settle",
            {"receipt_no": "回执2026-090", "reason": "档案核对完成"},
        )
        assert done["state"] == "in_place"
        assert "转入办结" in done["notice"]


@pytest.mark.asyncio
async def test_guards_scope_and_ledger(transfer_url):
    admin = actor("transfer-admin")
    async with client_for(transfer_url, admin) as (client, _):
        # 培养对象不是"组织关系接转"的对象
        message = await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={"direction": "out", "profile_id": "tr-applicant", **letter()},
        )
        assert "预备党员与正式党员" in message
        # 转出必须指定名册中的党员，且不能借转出重复登记姓名
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={"direction": "out", **letter()},
        )
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={"direction": "out", "profile_id": "tr-keep", "name": "重名", **letter()},
        )
        # 转入要么关联既有档案、要么登记姓名 / 阶段 / 进入阶段日期
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={"direction": "in", "org_unit_id": BRANCH, **letter()},
        )
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={
                "direction": "in",
                "name": "合成无阶段",
                "org_unit_id": BRANCH,
                "letter_no": "转入字2026-030",
                "counterpart_org": "合成外校党委",
                "issued_on": TODAY.isoformat(),
                "reason": "缺阶段",
            },
        )
        # 介绍信要素本身要成立：不能未来开具、有效期不能早于开具
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={
                "direction": "out",
                "profile_id": "tr-keep",
                **letter(issued_on=(TODAY + timedelta(days=1)).isoformat()),
            },
        )
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=422,
            body={
                "direction": "out",
                "profile_id": "tr-keep",
                **letter(valid_until=(TODAY - timedelta(days=30)).isoformat()),
            },
        )
        # 越权：看不到的组织里的档案一律当作不存在
        assert "不存在" in await refused(
            client,
            "post",
            "/member-full/transfers",
            status=404,
            body={"direction": "out", "profile_id": "tr-hidden", **letter()},
        )
        assert "权限范围" in await refused(
            client,
            "get",
            "/member-full/transfers",
            status=403,
            params={"org_unit_id": OTHER},
        )
        # 同一档案同时只能有一次未办结的接转
        first = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "out",
                "profile_id": "tr-pending",
                **letter(letter_no="转字2026-040", counterpart_org="合成第三个单位党委"),
            },
        )
        assert first["state"] == "out_pending"
        assert "未办结" in await refused(
            client,
            "post",
            "/member-full/transfers",
            status=409,
            body={
                "direction": "out",
                "profile_id": "tr-pending",
                **letter(letter_no="转字2026-041"),
            },
        )

        # 超过有效期仍未回执：提示核实，不自动判定失败
        overdue = await ok(
            client,
            "post",
            "/member-full/transfers",
            {
                "direction": "out",
                "profile_id": "tr-keep",
                **letter(
                    letter_no="转字2026-050",
                    counterpart_org="合成第四个单位党委",
                    issued_on=(TODAY - timedelta(days=100)).isoformat(),
                ),
            },
        )
        assert overdue["overdue"] is True
        assert overdue["days_left"] == -10
        assert "不自动判定转出失败" in overdue["overdue_notice"]

        ledger = await ok(
            client, "get", "/member-full/transfers", params={"overdue": True}
        )
        assert {row["letter_no"] for row in ledger["items"]} == {"转字2026-050"}
        assert ledger["summary"]["overdue"] == 1
        assert ledger["summary"]["pending_total"] >= 2
        assert "系统不自动认定接收" in ledger["notice"]

        filtered = await ok(
            client, "get", "/member-full/transfers", params={"direction": "in"}
        )
        assert all(row["direction"] == "in" for row in filtered["items"])
        assert await refused(
            client, "get", "/member-full/transfers", status=422, params={"direction": "sideways"}
        )

    # 没有组织管理权限的党员连台账都读不到，更不能登记
    member = actor("transfer-member", UserRole.MEMBER, BRANCH)
    async with client_for(transfer_url, member) as (client, _):
        await refused(client, "get", "/member-full/transfers", status=403)
        await refused(
            client,
            "post",
            "/member-full/transfers",
            status=403,
            body={"direction": "out", "profile_id": "tr-keep", **letter()},
        )
