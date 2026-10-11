"""独立 PostgreSQL 测试库验证迁移及真实检索授权，不写现有业务库。"""

import asyncio
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import TenantConfig, settings
from app.core.tenant import bypass_tenant_filter, tenant_context
from app.llm.base import DataLevel, EmbeddingResponse
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import GatewayError
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.rag.embedding_service import EmbeddingService
from app.rag.retrieval.access import knowledge_filters
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever
from app.rules.document_metadata import MetadataValidationError
from app.services.knowledge_service import (
    DocumentConflictError,
    DocumentNotFoundError,
    create_document,
    replace_document_content,
)


@pytest.fixture(scope="module")
def storage_url():
    """仅创建和删除本 fixture 生成的随机测试库，名字不接受外部输入。"""
    name = "party_repair_test_" + uuid.uuid4().hex[:12]
    admin_url = make_url(settings.DATABASE_URL).set(database="postgres")
    test_url = admin_url.set(database=name)

    async def provision(create: bool):
        assert name.startswith("party_repair_test_") and len(name) == 30
        engine = create_async_engine(admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'{"CREATE" if create else "DROP"} DATABASE "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(provision(True))
    try:
        yield test_url
    finally:
        asyncio.run(provision(False))


@pytest.mark.asyncio
async def test_migration_adopts_users_without_changing_records(storage_url):
    engine = create_async_engine(storage_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(User.__table__.create)
            await conn.execute(
                User.__table__.insert().values(
                    id="existing-user",
                    tenant_id="existing-tenant",
                    username="existing",
                    name="保留用户",
                    password_hash="synthetic-hash",
                    role=UserRole.SYSTEM_ADMIN,
                    is_active=True,
                )
            )
            before = (await conn.execute(select(User.__table__))).mappings().all()

            def migrate(sync_conn):
                config = Config()
                config.set_main_option("script_location", "migrations")
                config.attributes["connection"] = sync_conn
                config.cmd_opts = SimpleNamespace(x=["adopt_existing_users=true"])
                command.upgrade(config, "head")
                return ScriptDirectory.from_config(config).get_current_head()

            expected_revision = await conn.run_sync(migrate)
            after = (await conn.execute(select(User.__table__))).mappings().all()
            assert before == after
            assert (
                await conn.scalar(text("SELECT version_num FROM alembic_version"))
                == expected_revision
            )
            assert await conn.scalar(text("SELECT to_regclass('knowledge_docs') IS NOT NULL"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_content_update_keeps_old_chunks_and_retrieves_new_version(storage_url):
    engine = create_async_engine(storage_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            with tenant_context("content-tenant"):
                document, _, _ = await create_document(
                    db,
                    tenant_id="content-tenant",
                    file_name="old.txt",
                    content="第一条 旧版本测试专用规则。".encode(),
                    metadata={
                        "doc_id": "business-document-identifier-longer-than-36-characters",
                        "file_name": "old.txt",
                        "title": "更新回归",
                        "issuer": "测试",
                        "level": "school",
                        "visibility": "school",
                        "security_level": "public",
                        "effective_date": "2020-01-01",
                        "status": "effective",
                        "tags": ["测试"],
                    },
                )
                await db.commit()
                _, count, revision = await replace_document_content(
                    db,
                    doc_id=document.doc_id,
                    tenant_id="content-tenant",
                    file_name="new.txt",
                    content="第一条 新版本测试专用规则。".encode(),
                    expected_revision=1,
                )
                assert revision == 1 and count > 0
                await db.commit()
                rows = (
                    (
                        await db.execute(
                            select(EmbeddingChunk).where(EmbeddingChunk.doc_id == document.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert any(row.is_deleted and "旧版本" in row.content for row in rows)
                assert any(
                    not row.is_deleted and row.embedding is None and "新版本" in row.content
                    for row in rows
                )
                user = User(id="content-reader", tenant_id="content-tenant", role=UserRole.MEMBER)
                assert not await KeywordRetriever(db).retrieve(
                    "旧版本测试专用规则", filters=knowledge_filters(user)
                )
                assert await KeywordRetriever(db).retrieve(
                    "新版本测试专用规则", filters=knowledge_filters(user)
                )
                with pytest.raises(DocumentConflictError):
                    await replace_document_content(
                        db,
                        doc_id=document.doc_id,
                        tenant_id="content-tenant",
                        file_name="new.txt",
                        content=b"test",
                        expected_revision=1,
                    )
                await db.rollback()
            with tenant_context("other-content-tenant"):
                with pytest.raises(DocumentNotFoundError):
                    await replace_document_content(
                        db,
                        doc_id="business-document-identifier-longer-than-36-characters",
                        tenant_id="other-content-tenant",
                        file_name="new.txt",
                        content=b"test",
                        expected_revision=2,
                    )
    finally:
        await engine.dispose()


async def seed(session):
    today = date.today()
    cases = [
        ("own", "tenant-a", "school", "public", "school", None, None, "effective", False),
        ("shared", "tenant-b", "central", "public", "public", None, None, "effective", False),
        ("private-other", "tenant-b", "school", "public", "school", None, None, "effective", False),
        ("sensitive", "tenant-a", "school", "sensitive", "school", None, None, "effective", False),
        (
            "branch-other",
            "tenant-a",
            "department",
            "internal",
            "branch",
            "org-b",
            None,
            "effective",
            False,
        ),
        (
            "expired-date",
            "tenant-a",
            "school",
            "public",
            "school",
            None,
            today - timedelta(days=1),
            "effective",
            False,
        ),
        ("abolished", "tenant-a", "school", "public", "school", None, None, "abolished", False),
        ("future", "tenant-a", "school", "public", "school", None, None, "effective", False),
        ("deleted", "tenant-a", "school", "public", "school", None, None, "effective", True),
        (
            "classified",
            "tenant-a",
            "school",
            "classified",
            "school",
            None,
            None,
            "effective",
            False,
        ),
        (
            "branch-own",
            "tenant-a",
            "department",
            "internal",
            "branch",
            "org-a",
            None,
            "effective",
            False,
        ),
    ]
    for name, tenant, level, security, visibility, org, end, status, deleted in cases:
        doc = KnowledgeDoc(
            id=str(uuid.uuid4()),
            tenant_id=tenant,
            doc_id="storage-" + name,
            file_name="synthetic.txt",
            title="共同制度 " + name,
            issuer="合成测试",
            level=level,
            visibility=visibility,
            security_level=security,
            effective_date=(
                today + timedelta(days=1) if name == "future" else today - timedelta(days=30)
            ),
            expiration_date=end,
            status=status,
            is_deleted=deleted,
            tags=["测试"],
            doc_metadata={"org_unit_id": org},
        )
        session.add(doc)
        session.add(
            EmbeddingChunk(
                tenant_id=tenant,
                doc_id=doc.id,
                chunk_id=str(uuid.uuid4()),
                content="第一条 共同制度要求提交申请。",
                sequence=0,
                embedding=[1.0] + [0.0] * 1023,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_real_keyword_and_vector_queries_enforce_all_boundaries(storage_url, monkeypatch):
    engine = create_async_engine(storage_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            with bypass_tenant_filter():
                await seed(session)
            member = User(
                id="query-user", tenant_id="tenant-a", role=UserRole.MEMBER, org_unit_id="org-a"
            )
            with tenant_context("tenant-a", user_id=member.id):
                expected = {"storage-own", "storage-shared"}
                keyword = await KeywordRetriever(session).retrieve(
                    "共同制度", top_k=50, filters=knowledge_filters(member)
                )
                assert {item.doc_id for item in keyword} == expected
                assert all(item.metadata["effective_date"] for item in keyword)
                service = SimpleNamespace(
                    embed=AsyncMock(return_value=SimpleNamespace(embeddings=[[1.0] + [0.0] * 1023]))
                )
                monkeypatch.setattr("app.rag.retrieval.vector.get_model_service", lambda: service)
                vector = await VectorRetriever(session).retrieve(
                    "共同制度", top_k=50, filters=knowledge_filters(member)
                )
                assert {item.doc_id for item in vector} == expected
                historical = await KeywordRetriever(session).retrieve(
                    "共同制度", top_k=50, filters=knowledge_filters(member, include_expired=True)
                )
                assert {item.doc_id for item in historical} == expected | {
                    "storage-expired-date",
                    "storage-abolished",
                }
                member.role = UserRole.BRANCH_SECRETARY
                secretary = await KeywordRetriever(session).retrieve(
                    "共同制度", top_k=50, filters=knowledge_filters(member)
                )
                assert {item.doc_id for item in secretary} == expected | {
                    "storage-branch-own",
                    "storage-sensitive",
                }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_configuration_is_persistent_and_inherited(storage_url):
    engine = create_async_engine(storage_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            with bypass_tenant_filter():
                db.add_all(
                    [
                        Tenant(
                            id="config-parent",
                            tenant_id="config-parent",
                            name="测试父级",
                            tenant_type="school",
                            path="/config-parent",
                            config={"retrieval_top_k": 15},
                        ),
                        Tenant(
                            id="config-child",
                            tenant_id="config-child",
                            name="测试子级",
                            tenant_type="department",
                            path="/config-parent/config-child",
                            parent_id="config-parent",
                            config={"no_evidence_threshold": 0.8},
                        ),
                    ]
                )
                await db.commit()
            config = TenantConfig()
            with tenant_context("config-child"):
                await config.load(db, "config-child")
                assert config.get("config-child", "retrieval_top_k") == 15
                await config.save(db, "config-child", {"retrieval_top_k": 7})
                await db.commit()
                reloaded = TenantConfig()
                await reloaded.load(db, "config-child")
                assert reloaded.get("config-child", "retrieval_top_k") == 7
                assert reloaded.get("config-child", "no_evidence_threshold") == 0.8
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_embedding_uses_document_security_and_preserves_vectors_on_invalid_output(
    storage_url, monkeypatch
):
    engine = create_async_engine(storage_url, poolclass=NullPool)
    model = SimpleNamespace(
        embed=AsyncMock(
            side_effect=lambda texts, **kwargs: EmbeddingResponse(
                embeddings=[[0.125] * 1024 for _ in texts],
                dimensions=1024,
                model_id="cloud-test-only",
            )
        )
    )
    monkeypatch.setattr("app.rag.embedding_service.get_model_service", lambda: model)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            with tenant_context("embedding-tenant"):

                async def document(
                    name,
                    security="public",
                    text_value="第一条 合成向量规则。",
                    title_value="合成向量规则",
                ):
                    return (
                        await create_document(
                            db,
                            tenant_id="embedding-tenant",
                            file_name="test.txt",
                            content=text_value.encode(),
                            metadata={
                                "doc_id": "embedding-" + name,
                                "file_name": "test.txt",
                                "title": title_value,
                                "issuer": "测试",
                                "level": "school",
                                "visibility": "school",
                                "security_level": security,
                                "effective_date": "2020-01-01",
                                "status": "effective",
                                "tags": ["测试"],
                            },
                        )
                    )[0]

                public = await document("public")
                sensitive = await document("sensitive", "sensitive", "第一条 合成敏感档案。")
                await document("pending")
                await db.commit()
                user = User(
                    id="embedding-admin", tenant_id="embedding-tenant", role=UserRole.SYSTEM_ADMIN
                )
                service = EmbeddingService(
                    db, data_level=DataLevel.PUBLIC, access_filters=knowledge_filters(user)
                )
                assert await service.embed_chunks(doc_id=public.doc_id) > 0
                assert model.embed.await_args.kwargs["data_level"] == DataLevel.PUBLIC
                await db.commit()
                model.embed.reset_mock()
                with pytest.raises(GatewayError):
                    await service.embed_chunks(doc_id=sensitive.doc_id)
                model.embed.assert_not_awaited()
                assert await service.embed_all_pending() > 0
                assert all(
                    not any("敏感档案" in value for value in call.kwargs["texts"])
                    for call in model.embed.await_args_list
                )
                assert (
                    await db.execute(
                        select(EmbeddingChunk.embedding).where(
                            EmbeddingChunk.doc_id == sensitive.id
                        )
                    )
                ).scalar_one() is None
                await db.commit()
                model.embed.return_value = EmbeddingResponse(
                    embeddings=[[0.0] * 768], dimensions=768, model_id="bad-test"
                )
                model.embed.side_effect = None
                with pytest.raises(ModelUnavailableError):
                    await service.embed_chunks(doc_id=public.doc_id, force_update=True)
                vector = (
                    await db.execute(
                        select(EmbeddingChunk.embedding).where(EmbeddingChunk.doc_id == public.id)
                    )
                ).scalar_one()
                assert all(value == 0.125 for value in vector)
                model.embed.reset_mock()
                with pytest.raises(MetadataValidationError):
                    await document("mislabelled", text_value="第一条 合成手机号 13900000000。")
                with pytest.raises(MetadataValidationError):
                    await document("mislabelled-title", title_value="合成手机号 13900000000")
                # 验证历史脏数据也不能绕过发送前检查。
                await db.execute(
                    update(EmbeddingChunk)
                    .where(EmbeddingChunk.doc_id == public.id)
                    .values(content="合成手机号 13900000000。")
                )
                await db.commit()
                with pytest.raises(GatewayError):
                    await service.embed_chunks(doc_id=public.doc_id, force_update=True)
                model.embed.assert_not_awaited()
    finally:
        await engine.dispose()
