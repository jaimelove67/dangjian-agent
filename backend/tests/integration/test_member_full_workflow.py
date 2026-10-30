"""真实 HTTP 与隔离 PostgreSQL 验证模块2（发展党员全流程）；不调用云模型、不写开发业务库。"""

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
from app.rules import data_sensitivity as ds
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
                    command.upgrade(cfg, "head")

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


async def new_profile(
    client,
    name,
    org="branch-a",
    stage="applicant",
    year=None,
    birth_date="1990-01-01",
    stage_joined_on=None,
):
    return await ok(
        client,
        "POST",
        "/member/roster",
        {
            "name": name,
            "org_unit_id": org,
            "current_stage": stage,
            "stage_joined_on": stage_joined_on,
            "birth_date": birth_date,
            "materials": [],
            "pending": 0,
        },
    )


@pytest.mark.asyncio
async def test_material_preview_original_and_scope(member_url, tmp_path, monkeypatch):
    from sqlalchemy import select

    from app.core.encryption import MAGIC
    from app.models.member import MemberMaterial
    from app.services.file_store import read_member_archive

    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))

    def no_model(*args, **kwargs):
        raise AssertionError("Local material processing must not call models")

    monkeypatch.setattr("app.services.member_archive_service.get_model_service", no_model)
    content = "思想汇报\n汇报人：合成预填人员\n文档日期：2020-01-01".encode()
    async with client_for(member_url, actor()) as (client, engine):
        profile = await new_profile(client, "合成预填人员")
        url = f"/api/v1/member-full/profiles/{profile['id']}/materials"
        result = await client.post(url + "/preview", files={"file": ("材料.txt", content)})
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        assert result.json()["data"]["fields"]["material_type"] == "思想汇报"
        before = await ok(client, "GET", f"/member-full/profiles/{profile['id']}")
        assert before["materials"] == []
        assert list(tmp_path.rglob("*.bin")) == []
        response = await client.post(
            url + "/scan",
            data={
                "material_type": "思想汇报",
                "file_version": "v2",
                "submit_date": "2020-02-01",
                "reason": "人工确认后归档",
            },
            files={"file": ("材料.txt", content)},
        )
        assert response.status_code == 200, response.text
        record = response.json()["data"]
        assert record["review_status"] == "pending" and record["file_version"] == "v2"
        assert record["submit_date"] == "2020-02-01" and record["has_file"]
        after = await ok(client, "GET", f"/member-full/profiles/{profile['id']}")
        assert after["current_stage"] == "applicant"
        original = await client.get(f"/api/v1/member-full/materials/{record['id']}/file")
        assert original.status_code == 200 and original.content == content
        assert original.headers["cache-control"] == "no-store"
        paths = list(tmp_path.rglob("*.bin"))
        assert len(paths) == 1 and paths[0].read_bytes().startswith(MAGIC)
        async with AsyncSession(engine) as db:
            stored = await db.scalar(
                select(MemberMaterial).where(MemberMaterial.id == record["id"])
            )
            assert read_member_archive(stored.file_path, stored.content_sha256) == content
            stored.data_level = "classified"
            await db.commit()
        denied = await client.get(f"/api/v1/member-full/materials/{record['id']}/file")
        assert denied.status_code == 403 and content not in denied.content
    for account in [
        actor("foreign", tenant="member-b", org="school-b"),
        actor("wrong-branch", org="branch-b", role=UserRole.BRANCH_SECRETARY),
    ]:
        async with client_for(member_url, account) as (client, _):
            assert (
                await client.post(url + "/preview", files={"file": ("材料.txt", content)})
            ).status_code == 404
            assert (
                await client.get(f"/api/v1/member-full/materials/{record['id']}/file")
            ).status_code == 404
    async with client_for(member_url, actor("no-permission", role=UserRole.MEMBER)) as (client, _):
        assert (
            await client.post(url + "/preview", files={"file": ("材料.txt", content)})
        ).status_code == 403
        assert (
            await client.get(f"/api/v1/member-full/materials/{record['id']}/file")
        ).status_code == 403


@pytest.mark.asyncio
async def test_batch_roster_material_and_transition_lifecycle(member_url):
    today = date.today().isoformat()
    async with client_for(member_url, actor()) as (client, _):
        batch = await ok(
            client,
            "POST",
            "/member-full/batches",
            {
                "year": 2026,
                "batch_no": "B1",
                "label": "2026年第一批发展对象",
                "org_unit_id": "branch-a",
                "reason": "建立年度批次",
            },
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
        # 材料记录上传与审核；入党申请书须有落款日期，且申请满 6 个月才能转积极分子。
        application_date = (date.today() - timedelta(days=200)).isoformat()
        for material_type in ("入党申请书", "党组织谈话记录"):
            body = {"material_type": material_type, "submit_date": today, "reason": "登记材料"}
            if material_type == "入党申请书":
                body["document_date"] = application_date
            await ok(
                client,
                "POST",
                f"/member-full/profiles/{profile['id']}/materials",
                body,
            )
        listed = await ok(client, "GET", f"/member-full/profiles/{profile['id']}/materials")
        assert listed["items"] and all(
            item["review_status"] == "pending" for item in listed["items"]
        )
        # 材料二进制不得进入响应，也不得因延迟列懒加载而 500。
        assert all("content" not in item for item in listed["items"])
        # 字段级敏感分级（T-MEM-12）：每行都带密级与出网 / 向量化口径
        assert all(item["data_level_label"] for item in listed["items"])
        assert all(item["cloud_allowed"] is True for item in listed["items"])
        assert all(item["redacted_fields"] == [] for item in listed["items"])
        for item in listed["items"]:
            if not item.get("legacy_material"):
                await ok(
                    client,
                    "POST",
                    f"/member-full/materials/{item['id']}/review",
                    {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
                )
        # 政审类材料按涉密级收敛：第三人字段正文不出界面（T-MEM-12）
        politics = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {"material_type": "政治审查材料", "submit_date": today, "reason": "登记政审材料"},
        )
        assert politics["data_level"] == "classified" and politics["cloud_allowed"] is False
        await ok(
            client,
            "POST",
            f"/member-full/materials/{politics['id']}/review",
            {"review_status": "approved", "note": "经向其舅舅王某某核实", "reason": "人工核验"},
        )
        after_review = await ok(client, "GET", f"/member-full/profiles/{profile['id']}/materials")
        politics = next(
            item for item in after_review["items"] if item["material_type"] == "政治审查材料"
        )
        assert politics["note"] == ds.CLASSIFIED_NOTE
        assert "note" in politics["redacted_fields"]
        assert "王某某" not in str(after_review)
        # 非法流转被拒（未满足合法顺序）
        response = await client.post(
            "/api/v1" + f"/member-full/profiles/{profile['id']}/transition",
            json={
                "target_stage": "member",
                "decision_date": today,
                "basis": "越权一步到位",
                "opinion": "",
            },
        )
        assert response.status_code == 422
        # 材料未齐时流转被拒
        await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {"material_type": "思想汇报", "submit_date": today, "reason": "登记材料"},
        )
        response = await client.post(
            "/api/v1" + f"/member-full/profiles/{profile['id']}/transition",
            json={
                "target_stage": "candidate",
                "decision_date": today,
                "basis": "材料未齐越级",
                "opinion": "",
            },
        )
        assert response.status_code == 422
        # 具备全部积极分子材料后流转成功
        profile = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/transition",
            {
                "target_stage": "activist",
                "decision_date": today,
                "basis": "支委会研究确定，培养联系人形成结论",
                "opinion": "同意列为入党积极分子",
            },
        )
        assert profile["current_stage"] == "activist"
        detail = await ok(client, "GET", f"/member-full/profiles/{profile['id']}")
        assert detail["stage_history"][-1]["to_stage"] == "activist"
        stats = await ok(client, "GET", "/member-full/stats?year=2026&batch_no=B1")
        assert stats["total"] == 1
        batches = await ok(client, "GET", "/member-full/batches?year=2026")
        assert batches["items"][0]["member_count"] == 1


@pytest.mark.asyncio
async def test_application_age_and_six_month_gate(member_url):
    today = date.today()
    async with client_for(member_url, actor()) as (client, _):
        underage = await new_profile(
            client,
            "未满十八周岁申请人",
            birth_date=(today - timedelta(days=365 * 17)).isoformat(),
        )
        rejected = await client.post(
            f"/api/v1/member-full/profiles/{underage['id']}/materials",
            json={
                "material_type": "入党申请书",
                "document_date": today.isoformat(),
                "reason": "登记材料",
            },
        )
        assert rejected.status_code == 422
        assert "未满18周岁" in rejected.text

        missing_date = await client.post(
            f"/api/v1/member-full/profiles/{underage['id']}/materials",
            json={"material_type": "入党申请书", "reason": "登记材料"},
        )
        assert missing_date.status_code == 422
        assert "落款日期" in missing_date.text

        profile = await new_profile(client, "未满六个月申请人")
        item = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {
                "material_type": "入党申请书",
                "document_date": (today - timedelta(days=150)).isoformat(),
                "submit_date": today.isoformat(),
                "reason": "登记材料",
            },
        )
        await ok(
            client,
            "POST",
            f"/member-full/materials/{item['id']}/review",
            {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
        )
        talk = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {"material_type": "党组织谈话记录", "submit_date": today.isoformat(), "reason": "登记材料"},
        )
        await ok(
            client,
            "POST",
            f"/member-full/materials/{talk['id']}/review",
            {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
        )
        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition",
            json={
                "target_stage": "activist",
                "decision_date": today.isoformat(),
                "basis": "支委会研究确定",
                "opinion": "同意列为入党积极分子",
            },
        )
        assert blocked.status_code == 422
        assert "6 个月" in blocked.text

        # 历史材料可能在上线前已核验通过；流转时仍要按落款日期复核 18 周岁，不能靠旧数据绕过。
        historical = await new_profile(client, "历史未成年申请")
        application = await ok(
            client,
            "POST",
            f"/member-full/profiles/{historical['id']}/materials",
            {
                "material_type": "入党申请书",
                "document_date": (today - timedelta(days=200)).isoformat(),
                "submit_date": today.isoformat(),
                "reason": "登记材料",
            },
        )
        await ok(
            client,
            "POST",
            f"/member-full/materials/{application['id']}/review",
            {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
        )
        historical_talk = await ok(
            client,
            "POST",
            f"/member-full/profiles/{historical['id']}/materials",
            {"material_type": "党组织谈话记录", "submit_date": today.isoformat(), "reason": "登记材料"},
        )
        await ok(
            client,
            "POST",
            f"/member-full/materials/{historical_talk['id']}/review",
            {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
        )
        await ok(
            client,
            "PATCH",
            f"/member-full/profiles/{historical['id']}",
            {
                "birth_date": (today - timedelta(days=365 * 17)).isoformat(),
                "reason": "更正出生年月",
            },
        )
        blocked_age = await client.post(
            f"/api/v1/member-full/profiles/{historical['id']}/transition",
            json={
                "target_stage": "activist",
                "decision_date": today.isoformat(),
                "basis": "支委会研究确定",
                "opinion": "同意列为入党积极分子",
            },
        )
        assert blocked_age.status_code == 422
        assert "未满18周岁" in blocked_age.text


@pytest.mark.asyncio
async def test_political_review_and_training_are_hard_gates(member_url):
    today = date.today()
    async with client_for(member_url, actor()) as (client, _):
        senior = await new_profile(client, "正式党员联系人", stage="member")
        profile = await new_profile(
            client,
            "政审培训对象",
            stage="candidate",
            stage_joined_on=(today - timedelta(days=100)).isoformat(),
        )
        for material_type in ("政治审查材料", "公示情况报告", "支部大会决议"):
            item = await ok(
                client,
                "POST",
                f"/member-full/profiles/{profile['id']}/materials",
                {"material_type": material_type, "submit_date": today.isoformat(), "reason": "登记材料"},
            )
            await ok(
                client,
                "POST",
                f"/member-full/materials/{item['id']}/review",
                {"review_status": "approved", "note": "核验通过", "reason": "人工核验"},
            )

        body = {
            "target_stage": "probationary",
            "decision_date": today.isoformat(),
            "basis": "支部大会讨论通过",
            "opinion": "同意接收为预备党员",
        }
        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "政治审查结论未登记" in blocked.text

        review = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/political-reviews",
            {
                "status": "passed",
                "reviewed_on": today.isoformat(),
                "scope": "本人及直系亲属",
                "conclusion": "政治审查合格",
                "note": "支委会审查形成结论",
                "reason": "登记政审结论",
            },
        )
        assert review["status"] == "passed"

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "集中培训未登记" in blocked.text

        training = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/trainings",
            {
                "start_on": (today - timedelta(days=2)).isoformat(),
                "end_on": today.isoformat(),
                "days": 3,
                "hours": 24,
                "issuer": "学校党校",
                "reason": "登记集中培训",
            },
        )
        assert training["days"] == 3

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "培养联系人未登记" in blocked.text

        contact = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "contact",
                "occurred_on": (today - timedelta(days=80)).isoformat(),
                "reason": "指定培养联系人",
                "details": {"linked_profile_id": senior["id"]},
            },
        )
        assert contact["details"]["linked_name"] == senior["name"]
        assert contact["status"] == "assigned"

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "入党介绍人未登记" in blocked.text

        introducer = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "introducer",
                "occurred_on": today.isoformat(),
                "reason": "确定入党介绍人",
                "details": {"linked_profile_id": senior["id"]},
            },
        )
        assert introducer["details"]["linked_name"] == senior["name"]

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "支委会审查未通过或未登记" in blocked.text

        branch_review = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "branch_committee_review",
                "occurred_on": today.isoformat(),
                "status": "passed",
                "summary": "支委会审查通过",
                "reason": "支委会审查",
            },
        )
        assert branch_review["status"] == "passed"

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "上级党委预审未通过或未登记" in blocked.text

        pre_review = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "upper_pre_review",
                "occurred_on": today.isoformat(),
                "status": "passed",
                "summary": "上级党委预审通过",
                "reason": "上级党委预审",
                "details": {"upper_org": "校党委"},
            },
        )
        assert pre_review["status"] == "passed"

        blocked = await client.post(
            f"/api/v1/member-full/profiles/{profile['id']}/transition", json=body
        )
        assert blocked.status_code == 422
        assert "入党志愿书未提交或未登记" in blocked.text

        application_form = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "application_form",
                "occurred_on": today.isoformat(),
                "status": "submitted",
                "reason": "填写入党志愿书",
                "details": {"form_no": "2026-001"},
            },
        )
        assert application_form["status"] == "submitted"

        profile = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/transition",
            body,
        )
        assert profile["current_stage"] == "probationary"

        talk = await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/procedures",
            {
                "kind": "upper_talk",
                "occurred_on": today.isoformat(),
                "summary": "谈话情况良好",
                "reason": "上级党委派人谈话",
                "details": {"talker": "校党委组织员"},
            },
        )
        assert talk["status"] == "completed"

        detail = await ok(client, "GET", f"/member-full/profiles/{profile['id']}")
        assert detail["political_reviews"]["satisfied"] is True
        assert detail["trainings"]["satisfied"] is True
        assert detail["procedures"]["contacts"]["satisfied"] is True
        assert detail["procedures"]["introducers"]["count"] == 1
        assert detail["procedures"]["branch_committee_review"]["satisfied"] is True
        assert detail["procedures"]["upper_pre_review"]["satisfied"] is True
        assert detail["procedures"]["application_form"]["satisfied"] is True
        assert detail["procedures"]["upper_talk"]["satisfied"] is True


@pytest.mark.asyncio
async def test_scoring_requires_evidence_and_flags_risks(member_url):
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "合成学员乙")
        for category, score in (
            ("theory_test", 80),
            ("volunteer_service", 90),
            ("public_review", 70),
        ):
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
        assert result["dimensions"]["theory_test"]["evidence"][0]["source_id"].startswith(
            "member_cultivation:"
        )
        # T-SEC-13：评分必须强制标注辅助性质，并说明依据保留在哪里
        assert "辅助参考" in result["disclaimer"] and "人工终审" in result["disclaimer"]
        assert "evidence" in result["disclaimer"]


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
        # 换一个年度批次、同一轮次不算重复：批次是一次独立的选优。
        # 数据库唯一约束漏了 batch_no 时这里会 500（约束比服务层查重更严），所以必须钉住。
        await ok(
            client,
            "POST",
            "/member-full/votes",
            {
                "batch_no": "B2",
                "round_no": 1,
                "votes": [{"profile_id": first["id"], "vote": "agree", "comment": "新批次"}],
            },
        )
        new_batch = await ok(client, "GET", "/member-full/votes/summary?batch_no=B2&round_no=1")
        assert new_batch["voter_count"] == 1
        assert new_batch["tally"][first["id"]]["agree"] == 1
    async with client_for(
        member_url, actor("member-voter2", UserRole.BRANCH_SECRETARY, "branch-a")
    ) as (client, _):
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
        # 无记名（T-MEM-12）：汇总不返回任何投票人身份，只回答"我投没投过这个人"
        assert "voters" not in summary["tally"][first["id"]]
        assert summary["tally"][first["id"]]["voted_by_me"] is True
        assert summary["tally"][second["id"]]["voted_by_me"] is False
        assert "member-author" not in str(summary) and "member-voter2" not in str(summary)
        # 选优汇总同样强制标注，且指向可逐条核对的投票明细分
        assert "辅助参考" in summary["note"] and "投票明细" in summary["note"]
        assert "不给出投票人身份" in summary["note"]


@pytest.mark.asyncio
async def test_reminders_sync_deduplicate_and_resolve(member_url):
    today = date.today().isoformat()
    async with client_for(member_url, actor()) as (client, _):
        profile = await new_profile(client, "提醒对象甲")
        await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {
                "material_type": "入党申请书",
                "document_date": (date.today() - timedelta(days=200)).isoformat(),
                "submit_date": today,
                "reason": "登记材料",
            },
        )
        await ok(
            client,
            "POST",
            f"/member-full/profiles/{profile['id']}/materials",
            {"material_type": "党组织谈话记录", "submit_date": today, "reason": "登记材料"},
        )
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
            {
                "target_stage": "activist",
                "decision_date": today,
                "basis": "支委会研究确定",
                "opinion": "同意",
            },
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
        # 档案检查结论必须标注辅助性质与依据位置
        assert "辅助参考" in result["note"] and "材料记录与阶段历史" in result["note"]
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
        assert any(
            "风险" in item or "人工核验" in item or "未提供" in item
            for item in result2["result"]["risks"]
        )


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
