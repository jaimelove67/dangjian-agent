"""隔离 PostgreSQL 库验证移植功能的权限、事务、迁移和正式 HTTP 接口。"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_tenant, get_current_user
from app.llm.service import ModelService
from app.main import app
from app.models.audit import AuditLog
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.qa_session import QASession
from app.models.user import User, UserRole
from app.rag.retrieval.access import knowledge_filters
from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url


@pytest.fixture(scope="module")
def business_url(storage_url):
    async def prepare():
        engine = create_async_engine(storage_url, poolclass=NullPool, hide_parameters=True)
        try:
            async with engine.begin() as connection:

                def migrate(sync_connection, revision):
                    config = Config()
                    config.set_main_option("script_location", "migrations")
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, revision)
                    return ScriptDirectory.from_config(config).get_current_head()

                await connection.run_sync(migrate, "004")
                # 模拟协作者 004 已部署并保存过没有 doc_id/index 的旧引用。
                await connection.execute(
                    text(
                        "INSERT INTO qa_sessions "
                        "(id, tenant_id, user_id, question, answer, citations) "
                        "VALUES ('legacy-qa', 'legacy-tenant', 'legacy-user', "
                        "'旧问题', '保留旧回答', :citations)"
                    ),
                    {
                        "citations": json.dumps(
                            [
                                {
                                    "title": "旧制度",
                                    "issuer": "旧单位",
                                    "content": "旧片段",
                                    "score": 0.9,
                                }
                            ]
                        )
                    },
                )
                expected_revision = await connection.run_sync(migrate, "head")
                assert (
                    await connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == expected_revision
                )
            async with AsyncSession(engine, expire_on_commit=False) as db:
                orgs = [
                    ("school-a", "tenant-a", "school", None, False),
                    ("dept-a", "tenant-a", "department", "school-a", False),
                    ("branch-a", "tenant-a", "branch", "dept-a", False),
                    ("dept-b", "tenant-a", "department", "school-a", False),
                    ("branch-b", "tenant-a", "branch", "dept-b", False),
                    ("deleted-branch", "tenant-a", "branch", "dept-a", True),
                    ("hidden-child", "tenant-a", "branch", "deleted-branch", False),
                    ("foreign", "tenant-b", "branch", "dept-a", False),
                ]
                for org_id, tenant, kind, parent, deleted in orgs:
                    db.add(
                        OrgUnit(
                            id=org_id,
                            tenant_id=tenant,
                            name="组织-" + org_id,
                            org_type=kind,
                            parent_id=parent,
                            path=org_id,
                            is_deleted=deleted,
                        )
                    )
                for record_id, tenant, org, deleted, active in [
                    ("a", "tenant-a", "branch-a", False, True),
                    ("dept", "tenant-a", "dept-a", False, True),
                    ("b", "tenant-a", "branch-b", False, True),
                    ("unbound", "tenant-a", None, False, True),
                    ("deleted", "tenant-a", "branch-a", True, True),
                    ("inactive", "tenant-a", "branch-a", False, False),
                    ("hidden", "tenant-a", "hidden-child", False, True),
                    ("foreign", "tenant-b", "foreign", False, True),
                ]:
                    db.add(
                        MemberProfile(
                            id=record_id,
                            tenant_id=tenant,
                            name="合成人员-" + record_id,
                            org_name="合成组织",
                            org_unit_id=org,
                            current_stage="activist",
                            stage_joined_on=date.today() - timedelta(days=400),
                            is_deleted=deleted,
                            is_active=active,
                        )
                    )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    return storage_url


def user(role=UserRole.BRANCH_SECRETARY, org="branch-a", tenant="tenant-a", user_id=None):
    return User(
        id=user_id or str(uuid.uuid4()),
        tenant_id=tenant,
        username="synthetic-reviewer",
        name="合成用户",
        role=role,
        org_unit_id=org,
        is_active=True,
        is_deleted=False,
    )


@asynccontextmanager
async def client_for(url, current_user):
    engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:

            async def database():
                yield db

            app.dependency_overrides[get_db] = database
            app.dependency_overrides[get_current_user] = lambda: current_user
            app.dependency_overrides[get_current_tenant] = lambda: current_user.tenant_id
            with tenant_context(current_user.tenant_id, user_id=current_user.id):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    yield client, db
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.parametrize(
    "role,org,expected",
    [
        (UserRole.BRANCH_SECRETARY, "branch-a", {"a"}),
        (UserRole.ORGANIZER, "branch-a", {"a"}),
        (UserRole.DEPARTMENT_ADMIN, "dept-a", {"a", "dept"}),
        (UserRole.SCHOOL_ADMIN, "school-a", {"a", "dept", "b"}),
        (UserRole.SYSTEM_ADMIN, None, {"a", "dept", "b", "unbound", "hidden"}),
        (UserRole.BRANCH_SECRETARY, None, set()),
        (UserRole.BRANCH_SECRETARY, "foreign", set()),
        (UserRole.DEPARTMENT_ADMIN, "branch-a", set()),
    ],
)
async def test_roster_respects_role_org_tenant_and_active_flags(business_url, role, org, expected):
    async with client_for(business_url, user(role, org)) as (client, _):
        response = await client.get("/api/v1/member/roster")
        assert response.status_code == 200
        data = response.json()["data"]
        assert {item["id"] for item in data["items"]} == expected
        assert data["total"] == len(expected)
        assert all(item["days_in_stage"] == 400 for item in data["items"])


@pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.APPLICANT])
async def test_ordinary_user_cannot_read_or_create_roster(business_url, role):
    async with client_for(business_url, user(role)) as (client, _):
        assert (await client.get("/api/v1/member/roster")).status_code == 403
        assert (await client.get("/api/v1/member/org-units")).status_code == 403
        assert (
            await client.post("/api/v1/member/roster", json={"name": "合成人员"})
        ).status_code == 403


async def test_roster_pagination_and_org_selector_use_same_scope(business_url):
    async with client_for(business_url, user(UserRole.DEPARTMENT_ADMIN, "dept-a")) as (client, _):
        first = (await client.get("/api/v1/member/roster?page_size=1")).json()["data"]
        second = (await client.get("/api/v1/member/roster?page_size=1&page=2")).json()["data"]
        assert first["total"] == second["total"] == 2
        assert {first["items"][0]["id"], second["items"][0]["id"]} == {"a", "dept"}
        orgs = (await client.get("/api/v1/member/org-units")).json()["data"]
        assert {org["id"] for org in orgs} == {"dept-a", "branch-a"}
        assert (await client.get("/api/v1/member/roster?page=0")).status_code == 422


@pytest.mark.parametrize("org_id", ["branch-b", "foreign", "deleted-branch", "missing"])
async def test_roster_creation_rejects_out_of_scope_org(business_url, org_id):
    async with client_for(business_url, user()) as (client, db):
        before = await db.scalar(select(func.count(MemberProfile.id)))
        response = await client.post(
            "/api/v1/member/roster", json={"name": "合成人员", "org_unit_id": org_id}
        )
        assert response.status_code == 403
        assert await db.scalar(select(func.count(MemberProfile.id))) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": "合成人员", "current_stage": "unknown"},
        {"name": "合成人员", "stage_joined_on": "2999-01-01"},
        {"name": "合成人员", "pending": 2147483648},
        {"name": "合成人员", "materials": [""]},
    ],
)
async def test_invalid_member_input_is_rejected_before_write(business_url, payload):
    async with client_for(business_url, user()) as (client, _):
        assert (await client.post("/api/v1/member/roster", json=payload)).status_code == 422


async def test_member_registration_is_persisted_canonical_and_audited(business_url):
    async with client_for(business_url, user()) as (client, db):
        response = await client.post(
            "/api/v1/member/roster",
            json={
                "name": " 合成新台账 ",
                "org_name": "伪造其他组织",
                "materials": ["材料甲", "材料甲"],
            },
        )
        assert response.status_code == 200
        item = response.json()["data"]
        assert item["org_name"] == "组织-branch-a" and item["org_unit_id"] == "branch-a"
        assert item["name"] == "合成新台账" and item["days_in_stage"] == 0
        assert item["materials"] == ["材料甲"]
        profile = await db.get(MemberProfile, item["id"])
        assert profile.current_stage == "applicant"
        audit = (
            await db.execute(select(AuditLog).where(AuditLog.resource_id == item["id"]))
        ).scalar_one()
        assert audit.action == "create" and audit.data_level == "sensitive"
        assert "合成新台账" not in str(audit.new_value)
        # 删除本用例新增台账的可见性，不影响其他用例固定名册预期。
        profile.is_deleted = True
        await db.commit()


async def add_document(db, *, org="dept-a", tenant="tenant-a", shared=False):
    identifier = "soft-delete-" + uuid.uuid4().hex
    document = KnowledgeDoc(
        tenant_id=tenant,
        doc_id=identifier,
        file_name="synthetic.txt",
        title="软删除测试制度",
        issuer="合成单位",
        level="central" if shared else "school",
        visibility="public" if shared else "school",
        security_level="public",
        effective_date=date(2020, 1, 1),
        status="effective",
        tags=[],
        doc_metadata={"org_unit_id": org},
    )
    db.add(document)
    await db.flush()
    db.add(
        EmbeddingChunk(
            tenant_id=tenant,
            doc_id=document.id,
            chunk_id=identifier + "-1",
            content="软删除测试专用规则。",
            sequence=1,
        )
    )
    await db.commit()
    return document


async def test_soft_delete_stops_listing_and_retrieval_but_keeps_audit_and_rows(business_url):
    current_user = user(UserRole.DEPARTMENT_ADMIN, "dept-a")
    async with client_for(business_url, current_user) as (client, db):
        document = await add_document(db)
        assert await KeywordRetriever(db).retrieve(
            "软删除测试专用规则",
            filters={**knowledge_filters(current_user), "doc_ids": [document.doc_id]},
        )
        response = await client.delete("/api/v1/knowledge-docs/" + document.doc_id)
        assert response.status_code == 200
        await db.refresh(document)
        assert document.is_deleted and document.status == "abolished"
        chunks = (
            (await db.execute(select(EmbeddingChunk).where(EmbeddingChunk.doc_id == document.id)))
            .scalars()
            .all()
        )
        assert chunks and all(chunk.is_deleted for chunk in chunks)
        assert not await KeywordRetriever(db).retrieve(
            "软删除测试专用规则",
            filters={
                **knowledge_filters(current_user),
                "doc_ids": [document.doc_id],
                "include_expired": True,
            },
        )
        for suffix in ("", "/chunks"):
            assert (
                await client.get("/api/v1/knowledge-docs/" + document.doc_id + suffix)
            ).status_code == 404
        assert (await client.delete("/api/v1/knowledge-docs/" + document.doc_id)).status_code == 404
        listed = (await client.get("/api/v1/knowledge-docs", params={"q": document.doc_id})).json()[
            "data"
        ]
        assert listed["total"] == 0 and listed["items"] == []
        audit = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.resource_id == document.id, AuditLog.action == "delete"
                )
            )
        ).scalar_one()
        assert audit.new_value["is_deleted"] is True


@pytest.mark.parametrize(
    "org,tenant,shared",
    [
        ("dept-b", "tenant-a", False),
        (None, "tenant-a", False),
        ("foreign", "tenant-b", True),
    ],
)
async def test_delete_does_not_turn_read_access_into_write_access(
    business_url, org, tenant, shared
):
    async with client_for(business_url, user(UserRole.DEPARTMENT_ADMIN, "dept-a")) as (client, db):
        document = await add_document(db, org=org, tenant=tenant, shared=shared)
        assert (await client.delete("/api/v1/knowledge-docs/" + document.doc_id)).status_code == 404
        await db.refresh(document)
        assert document.is_deleted is False


async def test_ordinary_user_cannot_delete_knowledge(business_url):
    async with client_for(business_url, user(UserRole.MEMBER)) as (client, _):
        assert (await client.delete("/api/v1/knowledge-docs/nonexistent")).status_code == 403


async def test_old_collaborator_history_survives_upgrade_and_remains_readable(business_url):
    async with client_for(
        business_url, user(UserRole.MEMBER, None, "legacy-tenant", "legacy-user")
    ) as (client, _):
        data = (await client.get("/api/v1/qa/sessions")).json()["data"]
        assert data["total"] == 1
        record = data["items"][0]
        assert record["answer"] == "保留旧回答" and record["refused"] is True
        assert record["citations"][0]["index"] == 1
        assert record["citations"][0]["doc_id"] == ""
        assert record["warnings"] and record["disclaimer"]


async def test_persistent_history_is_private_and_paginated(business_url):
    current_user = user(UserRole.MEMBER, None)
    async with client_for(business_url, current_user) as (client, db):
        for tenant, owner, deleted in [
            ("tenant-a", current_user.id, False),
            ("tenant-a", current_user.id, False),
            ("tenant-a", "other-owner", False),
            ("tenant-b", current_user.id, False),
            ("tenant-a", current_user.id, True),
        ]:
            db.add(
                QASession(
                    tenant_id=tenant,
                    user_id=owner,
                    question="合成问题",
                    answer="合成答案",
                    is_deleted=deleted,
                )
            )
        await db.commit()
        first = (await client.get("/api/v1/qa/sessions?page_size=1")).json()["data"]
        second = (await client.get("/api/v1/qa/sessions?page_size=1&page=2")).json()["data"]
        assert first["total"] == second["total"] == 2
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert (await client.get("/api/v1/qa/sessions?page_size=101")).status_code == 422


@pytest.mark.parametrize("fail_history", [False, True])
async def test_real_qa_preserves_complete_history_or_recovers_from_failed_flush(
    business_url, monkeypatch, fail_history, caplog
):
    current_user = user(UserRole.MEMBER, None)
    source = RetrievalResult(
        "qa-chunk",
        "第一条 要求提交申请。",
        0.9,
        "qa-document",
        article="第一条",
        metadata={
            "title": "合成制度",
            "issuer": "合成单位",
            "file_name": "synthetic.txt",
            "security_level": "internal",
            "effective_date": "2020-01-01",
            "expiration_date": (date.today() + timedelta(days=10)).isoformat(),
        },
    )
    monkeypatch.setattr(HybridRetriever, "retrieve", AsyncMock(return_value=[source]))
    monkeypatch.setattr(
        ModelService,
        "generate",
        AsyncMock(return_value=SimpleNamespace(content="第一条要求提交申请。[1]")),
    )
    monkeypatch.setattr(
        "app.api.v1.qa._session_store",
        lambda _: SimpleNamespace(get_history=AsyncMock(return_value=[]), append_turn=AsyncMock()),
    )
    async with client_for(business_url, current_user) as (client, db):
        if fail_history:
            original_flush = db.flush

            async def invalid_history_flush(*args, **kwargs):
                for record in db.new:
                    if isinstance(record, QASession):
                        record.question = None  # 真实 NOT NULL 错误，验证 SAVEPOINT 恢复事务。
                await original_flush(*args, **kwargs)

            monkeypatch.setattr(db, "flush", invalid_history_flush)
        response = await client.post(
            "/api/v1/qa",
            json={"question": "合成制度需要哪些材料？", "session_id": "persisted-session"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["has_sufficient_evidence"] and data["citations"][0]["doc_id"] == "qa-document"
        history = (await client.get("/api/v1/qa/sessions")).json()["data"]
        audits = (
            (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.user_id == current_user.id, AuditLog.action == "qa_ask"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        if fail_history:
            assert history["total"] == 0
            assert "问答历史保存失败，本次回答仍可使用。" in data["warnings"]
            assert "合成制度需要哪些材料" not in caplog.text
            assert "INSERT INTO qa_sessions" not in caplog.text
        else:
            assert history["total"] == 1
            stored = history["items"][0]
            for key, value in data.items():
                assert stored[key] == value
            assert stored["session_id"] == "persisted-session"
