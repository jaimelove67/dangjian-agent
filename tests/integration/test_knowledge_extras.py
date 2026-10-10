"""知识库增量能力验证（模块1 M1-02/03/04）：处理状态、元数据维护、原始文件留存下载。

独立 PostgreSQL + 临时文件存储目录；不写开发业务库、不调用云模型。
"""

import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_tenant, get_current_user
from app.main import app
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
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
                    command.upgrade(cfg, "009_member_workflow")

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


def actor(
    user_id="kb-manager", role=UserRole.SCHOOL_ADMIN, org="school-a", tenant="kb-a"
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


async def upload_document(client, doc_id="M1-EXTRA-001"):
    response = await client.post(
        "/api/v1/knowledge-docs",
        data={
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
        },
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
        assert (
            await client.get("/api/v1/knowledge-docs/M1-EXTRA-T2/file")
        ).status_code == 404
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
