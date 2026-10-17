"""原生 PostgreSQL 验证模块6事务、审计防篡改、活跃权限、审核版本与队列恢复。"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import request_audit
from app.core.config import settings, tenant_config
from app.core.tenant import bypass_tenant_filter, tenant_context
from app.models.audit import AuditLog
from app.models.governance import DurableJob
from app.models.member import MemberCultivation, MemberProfile, MemberVote
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.governance import JobCreate, ReviewDecision, ReviewSubmit
from app.services import job_service
from app.services.governance_service import (
    GovernanceUpdate,
    read_governance,
    save_governance,
    supply_rules,
)
from app.services.identity_guard import ensure_active_identity
from app.services.identity_service import IdentityService
from app.services.member_service import _load_scoring_rules
from app.services.review_service import ReviewService

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def governance_url():
    name = "party_m6_test_" + uuid.uuid4().hex[:12]
    admin = make_url(settings.DATABASE_URL).set(database="postgres")
    target = admin.set(database=name)

    async def provision(create):
        assert name.startswith("party_m6_test_") and len(name) == 26
        engine = create_async_engine(admin, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'{"CREATE" if create else "DROP"} DATABASE "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(provision(True))

    async def migrate():
        engine = create_async_engine(target, poolclass=NullPool)
        try:
            async with engine.begin() as conn:

                def upgrade(sync):
                    config = Config("alembic.ini")
                    config.attributes["connection"] = sync
                    command.upgrade(config, "010_security_governance")
                    sync.execute(
                        text(
                            "INSERT INTO config_revisions "
                            "(id,tenant_id,version,actor_id,reason,values,created_at,updated_at) "
                            "VALUES ('legacy-revision','legacy-tenant',1,'legacy-actor',"
                            "'isolated upgrade evidence','{}','2026-01-01','2026-01-01')"
                        )
                    )
                    before = (
                        sync.execute(
                            text("SELECT * FROM config_revisions WHERE id='legacy-revision'")
                        )
                        .mappings()
                        .one()
                    )
                    command.upgrade(config, "head")
                    assert (
                        sync.execute(
                            text("SELECT * FROM config_revisions WHERE id='legacy-revision'")
                        )
                        .mappings()
                        .one()
                        == before
                    )
                    defaults = (
                        sync.execute(
                            text(
                                "SELECT column_default FROM information_schema.columns "
                                "WHERE table_name IN "
                                "('config_revisions','human_reviews','durable_jobs','model_usage') "
                                "AND column_name IN ('created_at','updated_at')"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert len(defaults) == 8 and all(defaults)

                await conn.run_sync(upgrade)
        finally:
            await engine.dispose()

    try:
        asyncio.run(migrate())
        yield target
    finally:
        asyncio.run(provision(False))


@pytest.fixture
async def native(governance_url, monkeypatch):
    engine = create_async_engine(governance_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(job_service, "async_session_maker", maker)
    monkeypatch.setattr(request_audit, "async_session_maker", maker)
    try:
        yield engine, maker
    finally:
        await engine.dispose()


async def seed(db):
    tid, rootid, branchid = (str(uuid.uuid4()) for _ in range(3))
    school = Tenant(
        id=tid,
        tenant_id=tid,
        name="独立数据库测试学校",
        tenant_type="school",
        path="/" + tid,
        is_active=True,
        config={},
    )
    root = OrgUnit(
        id=rootid,
        tenant_id=tid,
        name="测试根组织",
        org_type="school",
        path="/" + rootid,
        is_active=True,
    )
    branch = OrgUnit(
        id=branchid,
        tenant_id=tid,
        name="测试支部",
        org_type="branch",
        parent_id=rootid,
        path="/" + rootid + "/" + branchid,
        is_active=True,
    )
    author = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        username="a" + uuid.uuid4().hex,
        name="测试提交人",
        password_hash="synthetic",
        role=UserRole.BRANCH_SECRETARY,
        org_unit_id=branchid,
        is_active=True,
    )
    reviewer = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        username="r" + uuid.uuid4().hex,
        name="测试审核人",
        password_hash="synthetic",
        role=UserRole.SCHOOL_ADMIN,
        org_unit_id=rootid,
        is_active=True,
    )
    with bypass_tenant_filter():
        db.add_all([school, root, branch, author, reviewer])
        await db.commit()
    return school, root, branch, author, reviewer


async def test_failed_business_transaction_keeps_independent_audit_and_rejects_mutation(native):
    engine, maker = native
    event_id, tenant = str(uuid.uuid4()), str(uuid.uuid4())
    async with maker() as business:
        with tenant_context(tenant):
            business.add(
                Tenant(
                    id=tenant,
                    tenant_id=tenant,
                    name="会回滚的测试记录",
                    tenant_type="school",
                    path="/" + tenant,
                    config={},
                )
            )
            await business.flush()
            await request_audit.persist(
                {
                    "id": event_id,
                    "created_at": datetime.utcnow().isoformat(),
                    "tenant_id": tenant,
                    "user_id": "native-test",
                    "user_name": "native-test",
                    "action": "update",
                    "resource_type": "tenant",
                    "resource_id": tenant,
                    "request_id": str(uuid.uuid4()),
                    "result": "failed",
                    "data_level": "internal",
                }
            )
            await business.rollback()
    with bypass_tenant_filter():
        async with maker() as db:
            assert await db.get(Tenant, tenant) is None
            assert (await db.get(AuditLog, event_id)).result == "failed"
    for query in (
        f"UPDATE audit_logs SET result='success' WHERE id='{event_id}'",
        f"DELETE FROM audit_logs WHERE id='{event_id}'",
        "TRUNCATE audit_logs",
    ):
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(text(query))
    async with engine.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM audit_logs WHERE id=:id"), {"id": event_id}
            )
            == 1
        )


async def test_identity_tree_role_binding_and_parent_disable_are_live(native):
    _, maker = native
    async with maker() as db:
        school, root, branch, author, reviewer = await seed(db)
        school_id, author_id, root_id = school.id, author.id, root.id
        with tenant_context(school.id, reviewer.id):
            service = IdentityService(db, reviewer)
            dept = await service.save_org(
                None, {"name": "测试院系", "org_type": "department", "parent_id": root.id}
            )
            await service.save_org(None, {"parent_id": dept.id}, branch.id)
            assert branch.path == dept.path + "/" + branch.id
            with pytest.raises(HTTPException):
                await service.save_org(None, {"parent_id": branch.id}, dept.id)
            await db.rollback()
        # 失败的组织修改回滚，原组织和账号仍有效。
        with bypass_tenant_filter():
            author = await db.get(User, author_id)
            school = await db.get(Tenant, school_id)
            root = await db.get(OrgUnit, root_id)
        with tenant_context(school.id, author.id):
            await ensure_active_identity(db, author)
            school.is_active = False
            await db.commit()
            with pytest.raises(HTTPException) as exc:
                await ensure_active_identity(db, author)
            assert exc.value.status_code == 403


async def test_review_frozen_score_rejects_self_approval_and_invalidates_changed_evidence(native):
    _, maker = native
    async with maker() as db:
        school, root, branch, author, reviewer = await seed(db)
        with tenant_context(school.id, author.id):
            profile = MemberProfile(
                tenant_id=school.id,
                name="测试培养对象",
                org_name=branch.name,
                org_unit_id=branch.id,
            )
            db.add(profile)
            await db.flush()
            evidence = []
            for category in _load_scoring_rules()["weights"]:
                row = MemberCultivation(
                    tenant_id=school.id,
                    profile_id=profile.id,
                    org_unit_id=branch.id,
                    category=category,
                    score=Decimal("50"),
                    period="2026",
                    source_note="独立数据库测试证据",
                )
                db.add(row)
                evidence.append(row)
            await db.commit()
            body = ReviewSubmit(source_kind="score", source_id=profile.id, year=2026)
            row = await ReviewService(db, author).submit(body)
            await db.commit()
            assert (await ReviewService(db, author).submit(body)).id == row.id
            with pytest.raises(HTTPException) as exc:
                await ReviewService(db, author).decide(
                    row.id,
                    ReviewDecision(
                        decision="approved", source_version=row.source_version, opinion="测试自审"
                    ),
                )
            assert exc.value.status_code == 403
        with tenant_context(school.id, reviewer.id):
            await ReviewService(db, reviewer).decide(
                row.id,
                ReviewDecision(
                    decision="approved", source_version=row.source_version, opinion="核对测试证据"
                ),
            )
            await db.commit()
            assert row.status == "approved" and row.reviewed_by == reviewer.id
            evidence[0].score = Decimal("80")
            await db.commit()
            view = await ReviewService(db, reviewer).view(row, include_content=True)
            assert (
                view["stale"] and view["effective_status"] == "pending" and view["snapshot"] is None
            )
            fresh = await ReviewService(db, reviewer).submit(body)
            await db.commit()
            assert fresh.id != row.id and fresh.status == "pending"
            visible = await ReviewService(db, reviewer).visible_reviews()
            assert sum(item["effective_status"] == "pending" for item in visible) == 1


async def test_review_frozen_vote_summary_stays_anonymous_and_recounts_voters(native):
    _, maker = native
    async with maker() as db:
        school, _, branch, author, reviewer = await seed(db)
        with tenant_context(school.id, author.id):
            candidates = [
                MemberProfile(
                    tenant_id=school.id,
                    name=f"选优对象{index}",
                    org_name=branch.name,
                    org_unit_id=branch.id,
                )
                for index in (1, 2)
            ]
            db.add_all(candidates)
            await db.flush()
            db.add_all(
                [
                    MemberVote(
                        tenant_id=school.id,
                        batch_no="2026-1",
                        round_no=1,
                        profile_id=candidates[0].id,
                        voter_id=author.id,
                        vote="agree",
                    ),
                    MemberVote(
                        tenant_id=school.id,
                        batch_no="2026-1",
                        round_no=1,
                        profile_id=candidates[0].id,
                        voter_id=reviewer.id,
                        vote="disagree",
                    ),
                    MemberVote(
                        tenant_id=school.id,
                        batch_no="2026-1",
                        round_no=1,
                        profile_id=candidates[1].id,
                        voter_id=author.id,
                        vote="agree",
                    ),
                ]
            )
            await db.commit()
            body = ReviewSubmit(source_kind="vote", source_id="2026-1", round=1)
            row = await ReviewService(db, author).submit(body)
            await db.commit()
            frozen = row.snapshot["content"]
            assert frozen["voter_count"] == 2
            assert set(frozen["tally"][candidates[0].id]) == {
                "agree",
                "disagree",
                "abstain",
                "voted_by_me",
            }
        with tenant_context(school.id, reviewer.id):
            # 审核人组织范围更广也必须能打开汇总：票数按服务端计数，不靠投票人身份。
            view = await ReviewService(db, reviewer).view(row, include_content=True)
            assert not view["stale"]
            content = view["snapshot"]
            assert content["voter_count"] == 2
            first = content["tally"][candidates[0].id]
            assert (first["agree"], first["disagree"]) == (1, 1)
            assert "voters" not in first and author.id not in json.dumps(content)


async def test_job_dedup_expired_lease_revocation_and_bounded_retries(native, monkeypatch):
    _, maker = native
    async with maker() as db:
        school, _, _, author, _ = await seed(db)
        with tenant_context(school.id, author.id):
            body = JobCreate(kind="member_reminders", dedup_key="x" * 160)
            row = await job_service.enqueue(db, author, body)
            await db.commit()
            assert (await job_service.enqueue(db, author, body)).id == row.id
            assert len(row.dedup_key) == 64
    first = await job_service.claim()
    assert first is not None
    with bypass_tenant_filter():
        async with maker() as db:
            row = await db.get(DurableJob, first[1])
            row.lease_until = datetime.utcnow() - timedelta(seconds=1)
            await db.commit()
    second = await job_service.claim()
    assert second and second[1] == first[1] and second[2] != first[2]
    await job_service.execute(*first)  # 旧租约不能执行或提交任何业务结果。
    with bypass_tenant_filter():
        async with maker() as db:
            row = await db.get(DurableJob, second[1])
            author = await db.get(User, row.actor_id)
            author.is_active = False
            row.lease_until = datetime.utcnow() - timedelta(seconds=1)
            await db.commit()
    assert await job_service.run_once()
    with bypass_tenant_filter():
        async with maker() as db:
            row = await db.get(DurableJob, second[1])
            assert row.status == "failed" and row.attempts == 3 and row.result is None
            denied = (
                (
                    await db.execute(
                        select(AuditLog).where(
                            AuditLog.resource_id == row.id,
                            AuditLog.action == "job_attempt_failed",
                            AuditLog.result == "denied",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(denied) == 1 and denied[0].user_id == row.actor_id and denied[0].request_id
            # 这一条是"真正执行后因账号被禁用而拒绝"，实测耗时必须有
            assert isinstance(denied[0].new_value["duration_ms"], int)
            author = await db.get(User, row.actor_id)
            author.is_active = True
            await db.commit()
            with tenant_context(school.id, author.id):
                retry = await job_service.enqueue(
                    db, author, JobCreate(kind="member_reminders", dedup_key="temporary-failure")
                )
                await db.commit()
    monkeypatch.setattr(job_service, "execute", AsyncMock(side_effect=ConnectionError("synthetic")))
    for attempt in range(1, 4):
        assert await job_service.run_once()
        with bypass_tenant_filter():
            async with maker() as db:
                row = await db.get(DurableJob, retry.id)
                assert row.attempts == attempt
                assert row.status == ("failed" if attempt == 3 else "retry")
                failures = (
                    (
                        await db.execute(
                            select(AuditLog).where(
                                AuditLog.resource_id == row.id,
                                AuditLog.action == "job_attempt_failed",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(failures) == attempt
                assert len({event.request_id for event in failures}) == attempt
                # 真正执行的失败必须带实测耗时：排障要能区分"秒挂"和"跑到超时"
                assert isinstance(failures[-1].new_value["duration_ms"], int)
                row.available_at = datetime.utcnow() - timedelta(seconds=1)
                await db.commit()
    assert not await job_service.run_once()
    # 领取时发现租约已耗尽、事实上没有执行的尝试：记失败但不写耗时（界面显示"—"，不编造）
    with bypass_tenant_filter():
        async with maker() as db:
            stalled = DurableJob(
                tenant_id=str(school.id),
                actor_id=str(author.id),
                kind="member_reminders",
                dedup_key="lease-exhausted",
                payload={"document_ids": []},
                status="running",
                attempts=3,
                max_attempts=3,
                available_at=datetime.utcnow() - timedelta(minutes=1),
                lease_until=datetime.utcnow() - timedelta(seconds=1),
                lease_token="stalled-lease-token",
            )
            db.add(stalled)
            await db.commit()
    assert not await job_service.run_once()
    with bypass_tenant_filter():
        async with maker() as db:
            row = await db.get(DurableJob, stalled.id)
            assert row.status == "failed" and row.error_code == "lease_exhausted"
            skipped = (
                (
                    await db.execute(
                        select(AuditLog).where(
                            AuditLog.resource_id == row.id,
                            AuditLog.action == "job_attempt_failed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(skipped) == 1 and skipped[0].result == "failed"
            assert skipped[0].new_value["duration_ms"] is None
    # 超时是运行日志最需要单独认出来的失败：`asyncio.wait_for` 超时抛 TimeoutError，
    # 必须落失败审计（带实测耗时）并让调度循环存活，而不是把整个 worker 打挂。
    with bypass_tenant_filter():
        async with maker() as db:
            with tenant_context(school.id, author.id):
                slow = await job_service.enqueue(
                    db, author, JobCreate(kind="member_reminders", dedup_key="timeout-failure")
                )
                await db.commit()
    monkeypatch.setattr(job_service, "execute", AsyncMock(side_effect=TimeoutError))
    assert await job_service.run_once()
    with bypass_tenant_filter():
        async with maker() as db:
            row = await db.get(DurableJob, slow.id)
            assert row.status == "retry" and row.attempts == 1
            timed_out = (
                (
                    await db.execute(
                        select(AuditLog).where(
                            AuditLog.resource_id == row.id,
                            AuditLog.action == "job_attempt_failed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(timed_out) == 1
            assert timed_out[0].result == "failed"
            assert timed_out[0].new_value["error_code"] == "TimeoutError"
            assert isinstance(timed_out[0].new_value["duration_ms"], int)


async def test_school_governance_version_conflict_and_pending_model_policy(native):
    _, maker = native
    async with maker() as db:
        school, _, _, _, reviewer = await seed(db)
        with tenant_context(school.id, reviewer.id):
            original = await read_governance(db, reviewer)
            assert original["admission"]["status"] == "pending"
            body = GovernanceUpdate(
                expected_version=0, reason="测试版本留痕", values=original["values"]
            )
            saved = await save_governance(db, reviewer, body)
            await db.commit()
            assert saved["version"] == 1
            with pytest.raises(HTTPException) as conflict:
                await save_governance(db, reviewer, body)
            assert conflict.value.status_code == 409
            original["values"]["model_policy"].update(
                external_enabled=True, evidence="测试凭证", allowed_hosts=[]
            )
            with pytest.raises(HTTPException) as pending:
                await save_governance(
                    db,
                    reviewer,
                    GovernanceUpdate(
                        expected_version=1, reason="禁止未确认模型", values=original["values"]
                    ),
                )
            assert pending.value.status_code == 422


async def test_school_governance_records_knowledge_supply(native):
    """T-KB-13：供给机制经治理配置持久化，并按权威来源供知识库读取"""
    _, maker = native
    rule = {
        "owner_unit": "党委组织部",
        "owner_name": "张老师",
        "review_cycle_days": 365,
    }
    async with maker() as db:
        school, _, _, _, reviewer = await seed(db)
        with tenant_context(school.id, reviewer.id):
            values = (await read_governance(db, reviewer))["values"]
            values["knowledge_supply"] = {"school_policy": dict(rule)}
            saved = await save_governance(
                db,
                reviewer,
                GovernanceUpdate(expected_version=0, reason="登记学校制度供给机制", values=values),
            )
            await db.commit()
            assert saved["values"]["knowledge_supply"] == {"school_policy": rule}
            # 供给机制是条目排定复核日程的依据，必须能按租户原样读出
            assert await supply_rules(db, school.id) == {"school_policy": rule}

            # 无法识别的权威类别会被拒绝（请求边界上即 FastAPI 的 422）：
            # 否则会存下一个永远匹配不到知识条目的制度类别。
            with pytest.raises(ValidationError):
                GovernanceUpdate(
                    expected_version=1,
                    reason="非法权威类别",
                    values={**values, "knowledge_supply": {"party_document": dict(rule)}},
                )

            # 半填的机制同样拒绝：只写人不写周期，机制不会产生任何到期提醒
            with pytest.raises(ValidationError):
                GovernanceUpdate(
                    expected_version=1,
                    reason="半填机制",
                    values={
                        **values,
                        "knowledge_supply": {
                            "school_policy": {"owner_unit": "党委组织部", "owner_name": "张老师"}
                        },
                    },
                )


async def test_runtime_role_rejects_privileged_membership_and_database_owner(
    native, governance_url, monkeypatch
):
    from scripts import module6_runtime_role as runtime

    engine, _ = native
    monkeypatch.setattr(runtime, "engine", engine)
    suffix = uuid.uuid4().hex[:12]
    role, privileged = "module6_rt_" + suffix, "module6_priv_" + suffix
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        await conn.execute(text(f'CREATE ROLE "{privileged}" NOLOGIN CREATEROLE'))
        await conn.execute(text(f'GRANT "{privileged}" TO "{role}"'))
        owner = await conn.scalar(text("SELECT current_user"))
    try:
        with pytest.raises(ValueError):
            await runtime.apply(role)
        async with engine.begin() as conn:
            await conn.execute(text(f'REVOKE "{privileged}" FROM "{role}"'))
            await conn.execute(
                text(f'ALTER DATABASE "{governance_url.database}" OWNER TO "{role}"')
            )
        with pytest.raises(ValueError):
            await runtime.apply(role)
    finally:
        async with engine.begin() as conn:
            quoted_owner = str(owner).replace('"', '""')
            await conn.execute(
                text(f'ALTER DATABASE "{governance_url.database}" OWNER TO "{quoted_owner}"')
            )
            await conn.execute(text(f'DROP ROLE "{role}"'))
            await conn.execute(text(f'DROP ROLE "{privileged}"'))
