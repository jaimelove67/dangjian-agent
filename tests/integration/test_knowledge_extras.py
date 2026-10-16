"""知识库增量能力验证（模块1 M1-02/03/04）：处理状态、元数据维护、原始文件留存下载。

独立 PostgreSQL + 临时文件存储目录；不写开发业务库、不调用云模型。
"""

import asyncio
import io
import json
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import date

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_tenant, get_current_user
from app.main import app
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.rag.retrieval.access import knowledge_filters
from app.rag.retrieval.keyword import KeywordRetriever
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url
os.environ["FILE_STORAGE_DIR"] = tempfile.mkdtemp(prefix="party_files_")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def kb_url(storage_url):
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
                        id="kb-a",
                        tenant_id="kb-a",
                        name="合成学校",
                        tenant_type="school",
                        path="kb-a",
                        config={},
                    )
                )
                db.add(
                    Tenant(
                        id="kb-b",
                        tenant_id="kb-b",
                        name="另一学校",
                        tenant_type="school",
                        path="kb-b",
                        config={},
                    )
                )
                for org_id, tenant, kind, parent in [
                    ("school-a", "kb-a", "school", None),
                    ("department-a", "kb-a", "department", "school-a"),
                    ("school-b", "kb-b", "school", None),
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


def actor(user_id="kb-manager", role=UserRole.SCHOOL_ADMIN, org="school-a", tenant="kb-a"):
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
    user.knowledge_org_ids = [org]
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
    app.dependency_overrides[get_current_tenant] = lambda: str(current_user.tenant_id)
    try:
        with tenant_context(current_user.tenant_id, user_id=current_user.id):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, engine
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


UPLOAD_BYTES = ("第一条 综合党建知识库增量测试原文，仅用于回归验证。\n").encode()


async def upload_document(client, doc_id="M1-EXTRA-001", **overrides):
    data = {
        "doc_id": doc_id,
        "file_name": "extras.txt",
        "title": "增量能力测试文档",
        "issuer": "合成单位",
        "level": "school",
        "visibility": "school",
        "effective_date": "2026-01-01",
        "tags": "测试,回归",
        "security_level": "public",
        "status": "effective",
        "summary": "测试摘要",
    }
    data.update(overrides)
    response = await client.post(
        "/api/v1/knowledge-docs",
        data=data,
        files={"file": ("extras.txt", UPLOAD_BYTES, "text/plain")},
    )
    return response


@pytest.mark.asyncio
async def test_upload_processing_status_metadata_and_download(kb_url):
    manager = actor()
    async with client_for(kb_url, manager) as (client, _):
        response = await upload_document(client)
        assert response.status_code == 200, response.text
        assert response.json()["code"] == 0

        # M1-02 处理状态：未向量化时明确 pending，并给出重试入口
        status = await ok_json(client, "GET", "/knowledge-docs/M1-EXTRA-001/processing-status")
        assert status["status"] == "pending"
        assert status["total_chunks"] >= 1 and status["pending_chunks"] == status["total_chunks"]
        assert status["retry_endpoint"] == "/embeddings/embed"

        # M1-03 元数据维护：修正可见范围/标签并审计
        patched = await ok_json(
            client,
            "PATCH",
            "/knowledge-docs/M1-EXTRA-001/metadata",
            {
                "title": "增量能力测试文档（修订）",
                "tags": "测试,修订,回归",
                "effective_date": "2026-02-01",
                "expiration_date": "2026-12-31",
                "reason": "授权人员修正元数据",
            },
        )
        assert patched["title"].endswith("（修订）")
        assert patched["tags"] == ["测试", "修订", "回归"]

        # M1-04 原始文件下载：内容与上传一致、带完整性与版本
        download = await client.get("/api/v1/knowledge-docs/M1-EXTRA-001/file")
        assert download.status_code == 200
        assert download.content == UPLOAD_BYTES
        assert "attachment" in download.headers["content-disposition"]

        # 元数据校验失败/无权限场景
        bad = await client.patch(
            "/api/v1/knowledge-docs/M1-EXTRA-001/metadata",
            json={"visibility": "unknown", "reason": "非法值"},
        )
        assert bad.status_code == 422
    # 无管理权限角色不能修正元数据
    async with client_for(kb_url, actor(role=UserRole.MEMBER, org="department-a")) as (client, _):
        assert (
            await client.patch(
                "/api/v1/knowledge-docs/M1-EXTRA-001/metadata",
                json={"summary": "x", "reason": "越权"},
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_file_download_respects_tenant_and_file_missing(kb_url):
    async with client_for(kb_url, actor()) as (client, _):
        await upload_document(client, "M1-EXTRA-T2")
    # 另一租户不可见
    async with client_for(kb_url, actor(tenant="kb-b", org="school-b")) as (client, _):
        assert (await client.get("/api/v1/knowledge-docs/M1-EXTRA-T2")).status_code == 404
        assert (await client.get("/api/v1/knowledge-docs/M1-EXTRA-T2/file")).status_code == 404
        assert (
            await client.get("/api/v1/knowledge-docs/M1-EXTRA-T2/processing-status")
        ).status_code == 404


@pytest.mark.asyncio
async def test_evaluation_samples_are_valid_json(kb_url):
    path = os.path.join("tests", "evaluation", "samples", "qa_samples_v1.json")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    items = payload["items"]
    assert len(items) >= 40
    refusal = [item for item in items if item["should_refuse"]]
    valid = [item for item in items if item["category"] == "valid"]
    assert len(refusal) >= 10 and len(valid) >= 20
    assert all(item.get("key_points") for item in valid if not item.get("should_refuse"))


async def ok_json(client, method, path, body=None):
    response = await client.request(method, "/api/v1" + path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    return response.json()["data"]


# ---------------------------------------------------------------- T-KB-12 审核发布

PUBLIC_UPLOAD = ("第一条 综合党建知识库公共库审核测试原文，仅用于回归验证。\n").encode()


async def upload_public_document(client, doc_id="M1-REVIEW-001", **overrides):
    """入库公共可见内容：按 T-KB-12 应进入待审，批准后才可被检索。"""
    data = {
        "doc_id": doc_id,
        "file_name": "review.txt",
        "title": "公共库审核测试文档",
        "issuer": "合成单位",
        "level": "school",
        "visibility": "public",
        "effective_date": "2026-01-01",
        "tags": "审核,公共库",
        "security_level": "public",
        "status": "effective",
        "authority": "school_policy",
        "validity": "effective",
        "summary": "审核测试摘要",
    }
    data.update(overrides)
    return await client.post(
        "/api/v1/knowledge-docs",
        data=data,
        files={"file": ("review.txt", PUBLIC_UPLOAD, "text/plain")},
    )


async def keyword_hits(engine, user, query):
    """按登录身份走真实检索过滤（FTS/trigram，不调用模型）。"""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        with tenant_context(user.tenant_id, user_id=user.id):
            results = await KeywordRetriever(db).retrieve(
                query, top_k=5, filters=knowledge_filters(user)
            )
    return {result.doc_id for result in results}


@pytest.mark.asyncio
async def test_public_content_requires_review_before_publish(kb_url):
    manager = actor()
    query = "综合党建知识库公共库审核测试原文"
    async with client_for(kb_url, manager) as (client, engine):
        response = await upload_public_document(client)
        assert response.status_code == 200, response.text
        document = response.json()["data"]["document"]
        # T-DATA-05：条目带权威来源与效力状态；T-KB-12：公共内容入库即待审
        assert document["authority"] == "school_policy"
        assert document["validity"] == "effective"
        assert document["review_status"] == "pending"
        assert document["field_levels"] == {}

        # 待审内容不进入检索范围
        assert "M1-REVIEW-001" not in await keyword_hits(engine, manager, query)

        # 维护人员能在待审队列里看到它（普通党员看不到，见下一用例）
        pending = await ok_json(client, "GET", "/knowledge-docs?review_status=pending")
        assert any(item["doc_id"] == "M1-REVIEW-001" for item in pending["items"])

        # 对公共库内容更正可见范围外的条目审核会被拒绝
        await upload_document(client, "M1-REVIEW-T2")
        non_public = await client.post(
            "/api/v1/knowledge-docs/M1-REVIEW-T2/review", json={"decision": "approve"}
        )
        assert non_public.status_code == 409

        # 退回必须写明审核意见
        rejected = await client.post(
            "/api/v1/knowledge-docs/M1-REVIEW-001/review", json={"decision": "reject"}
        )
        assert rejected.status_code == 409

        # 批准发布：留痕审核人、时间与意见
        reviewed = await ok_json(
            client,
            "POST",
            "/knowledge-docs/M1-REVIEW-001/review",
            {"decision": "approve", "note": "已核对权威来源与效力"},
        )
        assert reviewed["review_status"] == "published"
        assert reviewed["reviewed_by"]
        assert reviewed["reviewed_at"]
        assert reviewed["review_note"] == "已核对权威来源与效力"

        # 发布后才进入检索范围
        assert "M1-REVIEW-001" in await keyword_hits(engine, manager, query)

        # 重复批准属于状态冲突
        assert (
            await client.post(
                "/api/v1/knowledge-docs/M1-REVIEW-001/review", json={"decision": "approve"}
            )
        ).status_code == 409

        # 公共内容换正文后重新进入待审，旧审核结论不再生效
        replaced = await client.put(
            "/api/v1/knowledge-docs/M1-REVIEW-001/content",
            data={"expected_revision": 1},
            files={"file": ("review.txt", PUBLIC_UPLOAD, "text/plain")},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["data"]["document"]["review_status"] == "pending"
        assert "M1-REVIEW-001" not in await keyword_hits(engine, manager, query)


@pytest.mark.asyncio
async def test_review_requires_review_permission(kb_url):
    # 普通党员没有知识库审核权限
    async with client_for(kb_url, actor(user_id="kb-member", role=UserRole.MEMBER)) as (client, _):
        assert (
            await client.post(
                "/api/v1/knowledge-docs/M1-REVIEW-001/review",
                json={"decision": "reject", "note": "越权"},
            )
        ).status_code == 403
        # 普通党员也不能查看待审队列
        assert (await client.get("/api/v1/knowledge-docs?review_status=pending")).status_code == 403


# ---------------------------------------------------------------- T-KB-13 供给机制与复核日程

SUPPLY_CONFIG = {
    "knowledge_supply": {
        "school_policy": {
            "owner_unit": "党委组织部",
            "owner_name": "张老师",
            "review_cycle_days": 365,
        }
    }
}


async def set_supply_config(engine, tenant_id, config):
    """直接写入租户配置：治理页的保存/审批流由 test_module6_governance 覆盖。"""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await db.execute(
            text(
                "UPDATE tenants SET config = CAST(:config AS json),"
                " config_version = config_version + 1 WHERE id = :tid"
            ),
            {"config": json.dumps(config), "tid": tenant_id},
        )
        await db.commit()


async def set_next_review(engine, doc_id, value):
    """把某条目的复核日程改到过去，模拟"到期未复核"。"""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await db.execute(
            text("UPDATE knowledge_docs SET next_review_at = :value WHERE doc_id = :doc_id"),
            {"value": value, "doc_id": doc_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_supply_mechanism_schedules_review_and_confirmation(kb_url):
    manager = actor(user_id="kb-supply")
    async with client_for(kb_url, manager) as (client, engine):
        await set_supply_config(engine, "kb-a", SUPPLY_CONFIG)
        try:
            # 入库即按学校供给机制带出责任部门 / 责任人与更新周期，并排定下次复核日程
            document = (await upload_document(client, "M1-SUPPLY-001")).json()["data"]["document"]
            assert document["authority"] == "school_policy"
            assert document["owner_unit"] == "党委组织部"
            assert document["owner_name"] == "张老师"
            assert document["review_cycle_days"] == 365
            assert document["next_review_at"] == "2027-01-01"  # 生效日 2026-01-01 + 365 天
            assert document["review_due"] is False

            # 未到期的条目不出现在"待复核"筛选里
            due = await ok_json(client, "GET", "/knowledge-docs?due_for_review=true")
            assert [item["doc_id"] for item in due["items"]] == []

            # 到期（含逾期）条目进入筛选，并带维护信号
            await set_next_review(engine, "M1-SUPPLY-001", date(2025, 1, 1))
            due = await ok_json(client, "GET", "/knowledge-docs?due_for_review=true")
            assert [item["doc_id"] for item in due["items"]] == ["M1-SUPPLY-001"]
            assert due["items"][0]["review_due"] is True

            # 复核确认：以确认时间为基准重排（一年一核），留痕且不再逾期
            confirmed = await ok_json(
                client,
                "POST",
                "/knowledge-docs/M1-SUPPLY-001/maintenance",
                {"note": "已核对仍现行有效，无需修订"},
            )
            assert confirmed["review_due"] is False
            assert confirmed["maintained_at"]
            assert (
                364 <= (date.fromisoformat(confirmed["next_review_at"]) - date.today()).days <= 366
            )
            assert await ok_json(client, "GET", "/knowledge-docs?due_for_review=true") == {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 40,
                "counts": {"all": 0},
            }

            # 非现行有效的条目没有复核义务：废止后不接受复核登记
            await ok_json(
                client,
                "PATCH",
                "/knowledge-docs/M1-SUPPLY-001/metadata",
                {"validity": "repealed", "reason": "对应法规已废止，同步退出使用"},
            )
            assert (
                await client.post(
                    "/api/v1/knowledge-docs/M1-SUPPLY-001/maintenance",
                    json={"note": "越权复核"},
                )
            ).status_code == 409

            # 未登记机制的权威类别不排日程，也不误报"到期"
            reference = (
                await upload_document(
                    client, "M1-SUPPLY-002", authority="reference", validity="effective"
                )
            ).json()["data"]["document"]
            assert reference["owner_unit"] is None
            assert reference["review_cycle_days"] is None
            assert reference["next_review_at"] is None
            assert reference["review_due"] is False
        finally:
            await set_supply_config(engine, "kb-a", {})


@pytest.mark.asyncio
async def test_supply_maintenance_requires_manage_permission(kb_url):
    # 普通党员不能登记复核确认
    async with client_for(kb_url, actor(user_id="kb-member-2", role=UserRole.MEMBER)) as (
        client,
        _,
    ):
        assert (
            await client.post(
                "/api/v1/knowledge-docs/M1-SUPPLY-001/maintenance", json={"note": "越权"}
            )
        ).status_code == 403


# ---------------------------------------------------------------- T-WF01-04 解析失败兜底


def scanned_pdf_bytes(pages: int = 3) -> bytes:
    """有页面但没有文字层的 PDF：扫描件 / 图片型 PDF 的字节特征。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def upload_bytes(client, doc_id, file_name, content, content_type, **overrides):
    data = {
        "doc_id": doc_id,
        "file_name": file_name,
        "title": "解析兜底测试文档",
        "issuer": "合成单位",
        "level": "school",
        "visibility": "school",
        "effective_date": "2026-01-01",
        "tags": "测试,兜底",
        "security_level": "public",
        "status": "effective",
    }
    data.update(overrides)
    return await client.post(
        "/api/v1/knowledge-docs",
        data=data,
        files={"file": (file_name, content, content_type)},
    )


@pytest.mark.asyncio
async def test_scanned_pdf_rejected_with_actionable_guidance(kb_url):
    """扫描件不能只回一句"没有可解析文本"：要说清页数、原因和三条出路。"""
    async with client_for(kb_url, actor()) as (client, _):
        response = await upload_bytes(
            client, "M1-SCAN-001", "scan.pdf", scanned_pdf_bytes(3), "application/pdf"
        )
        assert response.status_code == 422, response.text
        message = response.json()["message"]
        assert "3 页" in message and "文字层" in message and "OCR" in message
        assert "另存为 .docx 或 .txt" in message
        # 解析失败不落库：用户改好文件即可原样重提，不需要先清理残留
        assert (await client.get("/api/v1/knowledge-docs/M1-SCAN-001")).status_code == 404

        # 旧版 Word 与图片：认得出是什么，并给出下一步，而不是"格式不支持"就结束
        legacy = await upload_bytes(
            client,
            "M1-SCAN-002",
            "notice.doc",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
            "application/msword",
        )
        assert legacy.status_code == 415, legacy.text
        assert "另存为 .docx" in legacy.json()["message"]

        image = await upload_bytes(
            client, "M1-SCAN-003", "stamp.png", b"\x89PNG\r\n\x1a\n\x00\x00", "image/png"
        )
        assert image.status_code == 415, image.text
        assert "图片" in image.json()["message"] and "OCR" in image.json()["message"]

        table = await upload_bytes(
            client,
            "M1-SCAN-004",
            "roster.xlsx",
            b"PK\x03\x04\x00\x00",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert table.status_code == 415, table.text
        assert "不能作为制度正文入库" in table.json()["message"]


@pytest.mark.asyncio
async def test_replace_content_keeps_reason_and_accepts_fixed_file(kb_url):
    """替换正文是扫描件唯一的人工补救入口，不能把失败原因吞掉。"""
    async with client_for(kb_url, actor()) as (client, _):
        created = await upload_document(client, doc_id="M1-REPLACE-001")
        assert created.status_code == 200, created.text
        revision = created.json()["data"]["document"]["content_revision"]

        failed = await client.put(
            "/api/v1/knowledge-docs/M1-REPLACE-001/content",
            data={"expected_revision": str(revision)},
            files={"file": ("scan.pdf", scanned_pdf_bytes(2), "application/pdf")},
        )
        assert failed.status_code == 422, failed.text
        message = failed.json()["message"]
        assert "2 页" in message and "文字层" in message

        fixed = await client.put(
            "/api/v1/knowledge-docs/M1-REPLACE-001/content",
            data={"expected_revision": str(revision)},
            files={
                "file": (
                    "fixed.txt",
                    "第一条 补录后的可复制正文，用于替换扫描件。\n".encode(),
                    "text/plain",
                )
            },
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["data"]["chunk_count"] >= 1
