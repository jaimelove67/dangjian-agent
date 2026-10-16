"""真实 HTTP 与隔离 PostgreSQL 验证上级审批 / 备案报送（T-MEM-11）；不写开发业务库。"""

import asyncio
import io
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
import pytest
from alembic import command
from alembic.config import Config
from openpyxl import load_workbook
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

TENANT = "upper-a"
SCHOOL = "upper-school"
DEPT = "upper-dept"
BRANCH = "upper-branch"
OTHER = "upper-other"

TODAY = date.today()


@pytest.fixture(scope="module")
def upper_url(storage_url):
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
                for profile_id, name, stage, org in [
                    ("ur-probationary", "预备党员甲", "probationary", BRANCH),
                    ("ur-applicant", "申请人乙", "applicant", BRANCH),
                    ("ur-activist", "积极分子丙", "activist", BRANCH),
                    ("ur-candidate", "发展对象丁", "candidate", BRANCH),
                    ("ur-member", "正式党员戊", "member", BRANCH),
                    ("ur-other", "另一支部党员", "member", OTHER),
                    # 越权用例专用：始终留在另一个支部
                    ("ur-hidden", "范围外党员", "member", OTHER),
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
                            is_active=True,
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


def report(profile_id, item, **overrides):
    values = {
        "profile_id": profile_id,
        "item": item,
        "upper_org": "合成院系党委",
        "letter_no": "报字2026-001",
        "submitted_on": (TODAY - timedelta(days=30)).isoformat(),
        "reason": "向院系党委报送备案材料",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_report_waits_for_reply_and_reply_does_not_move_the_stage(upper_url):
    admin = actor("upper-admin")
    async with client_for(upper_url, admin) as (client, _):
        workspace = await ok(client, "get", "/member-full/upper-reports")
        assert "不代替上级党组织审批" in workspace["notice"]
        assert {entry["item"] for entry in workspace["items_catalog"]} == {
            "activist_record",
            "candidate_record",
            "probationary_approval",
            "member_approval",
        }
        catalog = next(
            entry for entry in workspace["items_catalog"] if entry["item"] == "probationary_approval"
        )
        # 依据由后端单源给出：界面不自己编条文
        assert "细则" in catalog["basis"]
        assert "中国共产党入党志愿书" in catalog["materials"]

        created = await ok(
            client,
            "post",
            "/member-full/upper-reports",
            report("ur-probationary", "probationary_approval"),
        )
        # 报送只是"材料已报出"：状态停在待批复，党员阶段不动
        assert created["status"] == "submitted"
        assert created["status_label"] == "已报送待批复"
        assert created["kind"] == "approval"
        assert created["stage"] == "probationary"
        assert created["deadline"] == (TODAY - timedelta(days=30) + timedelta(days=90)).isoformat()
        assert created["days_left"] == 60
        assert created["overdue"] is False
        assert "材料已报出" in created["notice"]
        # 随报材料清单来自阶段材料要求 + 本事项另需材料
        assert "政治审查材料" in created["materials"]
        assert "中国共产党入党志愿书" in created["materials"]
        report_id = created["id"]

        # 同一党员同一事项只能有一条未办结的报送
        assert "未办结" in await refused(
            client,
            "post",
            "/member-full/upper-reports",
            status=409,
            body=report("ur-probationary", "probationary_approval", letter_no="报字2026-002"),
        )

        listed = await ok(
            client,
            "get",
            "/member-full/upper-reports",
            params={"item": "probationary_approval", "status": "submitted"},
        )
        assert listed["total"] >= 1
        assert listed["summary"]["pending"] >= 1
        assert listed["summary"]["pending_approval"] >= 1
        assert all(row["item"] == "probationary_approval" for row in listed["items"])

        # 没有文号的"同意"不是批复：契约层直接拦掉（具体文案由单元测试守住）
        await refused(
            client,
            "post",
            f"/member-full/upper-reports/{report_id}/settle",
            status=422,
            body={"result": "agreed", "reply_no": "", "reason": "口头通知"},
        )

        settled = await ok(
            client,
            "post",
            f"/member-full/upper-reports/{report_id}/settle",
            {
                "result": "agreed",
                "decided_on": (TODAY - timedelta(days=5)).isoformat(),
                "reply_no": "合成党组〔2026〕15号",
                "reason": "收到院系党委批复",
            },
        )
        assert settled["status"] == "settled"
        assert settled["result_label"] == "同意 / 批准"
        assert settled["reply_no"] == "合成党组〔2026〕15号"
        # 回填的是上级结论：系统不自动改阶段
        assert "阶段不会自动变化" in settled["notice"]

        profile = await ok(client, "get", "/member-full/profiles/ur-probationary")
        assert profile["current_stage"] == "probationary"

        assert "已回填" in await refused(
            client,
            "post",
            f"/member-full/upper-reports/{report_id}/settle",
            status=409,
            body={"result": "agreed", "reply_no": "又一份", "reason": "重复回填"},
        )
        detail = await ok(client, "get", f"/member-full/upper-reports/{report_id}")
        assert [item["action"] for item in detail["history"]] == ["submit", "settle"]
        assert all(item["actor_id"] == "upper-admin" for item in detail["history"])


@pytest.mark.asyncio
async def test_stage_prerequisite_revoke_and_rejected_reply(upper_url):
    admin = actor("upper-admin")
    async with client_for(upper_url, admin) as (client, _):
        # 还没到那个环节不给办：入党申请人不能说"支部大会已通过接收预备党员"
        message = await refused(
            client,
            "post",
            "/member-full/upper-reports",
            status=422,
            body=report("ur-applicant", "probationary_approval"),
        )
        assert "环节" in message
        # 积极分子只能报积极分子备案，不能报发展对象备案
        assert "环节" in await refused(
            client,
            "post",
            "/member-full/upper-reports",
            status=422,
            body=report("ur-activist", "candidate_record"),
        )

        first = await ok(
            client,
            "post",
            "/member-full/upper-reports",
            report("ur-activist", "activist_record"),
        )
        assert first["kind"] == "record"
        assert first["status_label"] == "已报送待批复"
        # 备案类细则未统一规定时限：不显示到期倒计时，也不编一个期限
        assert first["deadline"] is None
        assert first["days_left"] is None
        assert first["overdue"] is False
        assert "备案时限按上级党委规定" in first["no_deadline_note"]
        assert "入党积极分子备案报告" in first["materials"]

        # 备案类不设到期，但"已报送"仍要能筛出来
        records = await ok(client, "get", "/member-full/upper-reports", params={"kind": "record"})
        assert all(row["kind"] == "record" for row in records["items"])

        revoked = await ok(
            client,
            "post",
            f"/member-full/upper-reports/{first['id']}/revoke",
            {"reason": "事项报错，重新登记"},
        )
        assert revoked["status"] == "revoked"
        assert "视同未发生" in revoked["notice"]
        assert "已作废" in await refused(
            client,
            "post",
            f"/member-full/upper-reports/{first['id']}/revoke",
            status=409,
            body={"reason": "重复作废"},
        )
        assert "已作废" in await refused(
            client,
            "post",
            f"/member-full/upper-reports/{first['id']}/settle",
            status=409,
            body={"result": "agreed", "reply_no": "×号", "reason": "作废后回填"},
        )
        # 作废后可以重新报送（作废不等于"已办结"）
        again = await ok(
            client,
            "post",
            "/member-full/upper-reports",
            report("ur-activist", "activist_record", letter_no="报字2026-003"),
        )
        assert again["status"] == "submitted"

        # 批复"不同意"：登记结论但不回退阶段，也不把人移出名册
        rejected = await ok(
            client,
            "post",
            f"/member-full/upper-reports/{again['id']}/settle",
            {
                "result": "rejected",
                "reply_no": "合成党组〔2026〕16号",
                "reason": "院系党委认为材料尚不齐备",
            },
        )
        assert rejected["result_label"] == "不同意"
        assert "不自动回退阶段" in rejected["notice"]
        profile = await ok(client, "get", "/member-full/profiles/ur-activist")
        assert profile["current_stage"] == "activist"

        # 重新报送时点名上一次"不同意"，避免把上次结论当没发生
        retry = await ok(
            client,
            "post",
            "/member-full/upper-reports",
            report("ur-activist", "activist_record", letter_no="报字2026-004"),
        )
        assert "上一次" in retry["notice"] and "不同意" in retry["notice"]

        # "需补充材料"必须写清缺什么
        await refused(
            client,
            "post",
            f"/member-full/upper-reports/{retry['id']}/settle",
            status=422,
            body={"result": "supplement", "decide_note": "", "reason": "先记一下"},
        )
        supplement = await ok(
            client,
            "post",
            f"/member-full/upper-reports/{retry['id']}/settle",
            {
                "result": "supplement",
                "decide_note": "缺群众评议材料原件",
                "reason": "院系党委退回补件",
            },
        )
        assert supplement["result_label"] == "需补充材料"
        summary = await ok(client, "get", "/member-full/upper-reports")
        assert summary["summary"]["supplement"] >= 1


@pytest.mark.asyncio
async def test_scope_permission_and_export(upper_url):
    admin = actor("upper-admin")
    async with client_for(upper_url, admin) as (client, _):
        # 报送要在自己的组织范围内：越权组织里的档案当作不存在
        assert "不存在" in await refused(
            client,
            "post",
            "/member-full/upper-reports",
            status=404,
            body=report("ur-hidden", "member_approval"),
        )
        assert "权限范围" in await refused(
            client,
            "get",
            "/member-full/upper-reports",
            status=403,
            params={"org_unit_id": "not-a-real-org"},
        )
        # 事项、类别与状态不能让请求自己编：非法值一律 422
        await refused(
            client,
            "post",
            "/member-full/upper-reports",
            status=422,
            body=report("ur-member", "system_approved"),
        )
        await refused(
            client,
            "get",
            "/member-full/upper-reports",
            status=422,
            params={"kind": "self_approval"},
        )
        await refused(
            client,
            "get",
            "/member-full/upper-reports",
            status=422,
            params={"status": "system_done"},
        )
        # 正式党员可以补登历史审批（存量人员按事实回填）
        historic = await ok(
            client,
            "post",
            "/member-full/upper-reports",
            report("ur-member", "member_approval", letter_no="报字2026-005"),
        )
        assert historic["item_label"].startswith("预备党员转正")

        # 导出是**台账**（报送要素 + 随报材料清单），不含材料原件与政审材料内容
        response = await client.get("/api/v1/member-full/upper-reports/export")
        assert response.status_code == 200, response.text
        assert "spreadsheetml" in response.headers["content-type"]
        book = load_workbook(io.BytesIO(response.content))
        assert book.sheetnames == ["报送台账", "导出说明"]
        header = [cell.value for cell in book["报送台账"][1]]
        assert header[:4] == ["事项", "类别", "姓名", "组织"]
        assert "随报材料" in header
        rows = [
            [cell.value for cell in row] for row in book["报送台账"].iter_rows(min_row=2)
        ]
        assert any(row[2] == "正式党员戊" for row in rows)
        guide = "\n".join(
            str(cell.value)
            for row in book["导出说明"].iter_rows()
            for cell in row
            if cell.value
        )
        assert "不含材料原件" in guide

    # 看得到党员发展但看不到接转台账的角色：本人视角没有 member.query
    member = actor("upper-member", UserRole.MEMBER, BRANCH)
    async with client_for(upper_url, member) as (client, _):
        assert "权限不足" in await refused(
            client, "get", "/member-full/upper-reports", status=403
        )
