"""复用 PostgreSQL 的可恢复任务队列。业务结果与完成状态在同一事务提交。"""

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.security import Permission, has_permission
from app.core.tenant import bypass_tenant_filter, tenant_context
from app.db.session import async_session_maker
from app.models.assessment import AssessmentTask
from app.models.governance import DurableJob
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.governance import JobCreate, JobKind
from app.services.org_scope import accessible_org_units

logger = logging.getLogger(__name__)
JOB_PERMISSIONS = {
    "member_reminders": Permission.MEMBER_QUERY,
    "assessment_reminders": Permission.ASSESSMENT_QUERY,
    "embedding": Permission.KNOWLEDGE_MANAGE,
}


async def enqueue(db: AsyncSession, user: User, body: JobCreate) -> DurableJob:
    if not has_permission(user.role, JOB_PERMISSIONS[body.kind]):
        raise HTTPException(403, "无权执行此类任务")
    key = hashlib.sha256(f"{user.id}:{body.kind}:{body.dedup_key}".encode()).hexdigest()
    if body.kind == "embedding":
        if not body.document_ids:
            raise HTTPException(422, "请提供待处理文档")
        from app.models.knowledge import KnowledgeDoc
        from app.services.document_authority import require_document_write_access

        ids = list(dict.fromkeys(body.document_ids))
        rows = list(
            (
                await db.execute(
                    select(KnowledgeDoc).where(
                        KnowledgeDoc.id.in_(ids),
                        KnowledgeDoc.is_deleted.is_(False),
                        KnowledgeDoc.tenant_id == str(user.tenant_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != len(ids):
            raise HTTPException(404, "文档不存在或无写入权限")
        for document in rows:
            await require_document_write_access(db, user, document)
    else:
        ids = []
    stmt = select(DurableJob).where(
        DurableJob.tenant_id == str(user.tenant_id), DurableJob.dedup_key == key
    )
    current = (await db.execute(stmt)).scalar_one_or_none()
    payload = {"document_ids": ids}
    if current:
        if current.payload != payload:
            raise HTTPException(409, "任务去重编号已用于不同参数")
        return current
    row = DurableJob(
        tenant_id=str(user.tenant_id),
        actor_id=str(user.id),
        kind=body.kind,
        dedup_key=key,
        payload=payload,
        status="queued",
        attempts=0,
        max_attempts=3,
        available_at=datetime.utcnow(),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        current = (await db.execute(stmt)).scalar_one()
        if current.payload != payload:
            raise HTTPException(409, "任务去重编号已用于不同参数") from None
        return current
    return row


async def audit_failed_attempt(
    db: AsyncSession,
    job: DurableJob,
    token: str,
    result: str,
    *,
    duration_ms: int | None = None,
) -> None:
    """每次尝试保留追加审计，与任务状态同事务提交；不保存供应商错误正文。

    ``duration_ms`` 是这次尝试实际跑了多久：运行日志要能回答"这次失败是秒挂还是跑到超时"。
    没真正执行的情况（领取时发现租约已耗尽）不写数字，留给界面显示"—"，不编造耗时。
    """
    await write_audit(
        db,
        tenant_id=str(job.tenant_id),
        user_id=str(job.actor_id),
        user_name=str(job.actor_id),
        action="job_attempt_failed",
        resource_type="job",
        resource_id=str(job.id),
        request_id=token,
        result=result,
        data_level="internal",
        new_value={
            "kind": job.kind,
            "attempt": job.attempts,
            "status": job.status,
            "error_code": job.error_code,
            "duration_ms": duration_ms,
        },
    )


async def claim() -> tuple[str, str, str] | None:
    now = datetime.utcnow()
    with bypass_tenant_filter():
        async with async_session_maker() as db:
            exhausted = list(
                (
                    await db.execute(
                        select(DurableJob)
                        .where(
                            DurableJob.is_deleted.is_(False),
                            DurableJob.status == "running",
                            DurableJob.lease_until < now,
                            DurableJob.attempts >= DurableJob.max_attempts,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            for job in exhausted:
                token = job.lease_token or uuid.uuid4().hex
                job.status, job.error_code, job.finished_at = "failed", "lease_exhausted", now
                job.lease_until, job.lease_token = None, None
                await audit_failed_attempt(db, job, token, "failed")
            row = (
                await db.execute(
                    select(DurableJob)
                    .where(
                        DurableJob.is_deleted.is_(False),
                        DurableJob.attempts < DurableJob.max_attempts,
                        or_(
                            and_(
                                DurableJob.status.in_(["queued", "retry"]),
                                DurableJob.available_at <= now,
                            ),
                            and_(DurableJob.status == "running", DurableJob.lease_until < now),
                        ),
                    )
                    .order_by(DurableJob.available_at, DurableJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                await db.commit()
                return None
            row.status, row.attempts = "running", row.attempts + 1
            row.lease_token = str(uuid.uuid4())
            row.lease_until = now + timedelta(seconds=settings.JOB_TIMEOUT_SECONDS + 30)
            await db.commit()
            return str(row.tenant_id), str(row.id), row.lease_token


async def execute(tenant_id: str, record_id: str, token: str) -> None:
    started = time.monotonic()
    with tenant_context(tenant_id):
        async with async_session_maker() as db:
            job = (
                await db.execute(
                    select(DurableJob)
                    .where(
                        DurableJob.id == record_id,
                        DurableJob.tenant_id == tenant_id,
                        DurableJob.lease_token == token,
                        DurableJob.status == "running",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                return
            user = (
                await db.execute(
                    select(User).where(
                        User.id == job.actor_id,
                        User.tenant_id == tenant_id,
                        User.is_active.is_(True),
                        User.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                raise HTTPException(403, "任务执行身份或租户已失效")
            from app.services.identity_guard import ensure_active_identity

            await ensure_active_identity(db, user)
            if not has_permission(user.role, JOB_PERMISSIONS[job.kind]):
                raise HTTPException(403, "任务执行权限已撤销")
            if job.kind == "member_reminders":
                from app.services.member_service import MemberDevelopment

                member_service = await MemberDevelopment(db, user).initialize()
                count = await member_service.scan_all_reminders()
            elif job.kind == "assessment_reminders":
                from app.services.assessment_service import AssessmentService

                assessment_service = AssessmentService(db, user)
                org_ids = [row.id for row in await accessible_org_units(db, user)]
                pairs = (
                    await db.execute(
                        select(AssessmentTask.org_unit_id, AssessmentTask.year)
                        .where(
                            AssessmentTask.tenant_id == tenant_id,
                            AssessmentTask.is_deleted.is_(False),
                            AssessmentTask.org_unit_id.in_(org_ids),
                        )
                        .distinct()
                    )
                ).all()
                count = 0
                for org_id, year in pairs:
                    count += len(await assessment_service.sync_reminders(org_id, year))
            else:
                # 二次检查文档授权；队列执行期间角色及组织绑定可能已修改。
                from app.models.knowledge import KnowledgeDoc
                from app.rag.embedding_service import EmbeddingService
                from app.rag.retrieval.access import knowledge_filters
                from app.services.document_authority import require_document_write_access

                embedding_service = EmbeddingService(
                    db,
                    tenant_id=tenant_id,
                    access_filters=knowledge_filters(user, include_unpublished=True),
                )
                count = 0
                for document_id in job.payload["document_ids"]:
                    document = (
                        await db.execute(
                            select(KnowledgeDoc).where(
                                KnowledgeDoc.id == document_id,
                                KnowledgeDoc.tenant_id == tenant_id,
                                KnowledgeDoc.is_deleted.is_(False),
                            )
                        )
                    ).scalar_one_or_none()
                    if document is None:
                        raise HTTPException(404, "任务文档已失效")
                    await require_document_write_access(db, user, document)
                    count += await embedding_service.embed_chunks(doc_id=document_id)
            job.status, job.result, job.finished_at = (
                "done",
                {"processed": count},
                datetime.utcnow(),
            )
            job.lease_until, job.lease_token = None, None
            await write_audit(
                db,
                tenant_id=tenant_id,
                user_id=str(user.id),
                user_name=str(user.id),
                action="job_completed",
                resource_type="job",
                resource_id=record_id,
                request_id=uuid.uuid4().hex,
                result="success",
                data_level="internal",
                new_value={
                    "kind": job.kind,
                    "processed": count,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            await db.commit()


async def run_once() -> bool:
    claimed = await claim()
    if not claimed:
        return False
    tenant_id, record_id, token = claimed
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            execute(tenant_id, record_id, token), timeout=settings.JOB_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        with bypass_tenant_filter():
            async with async_session_maker() as db:
                row = (
                    await db.execute(
                        select(DurableJob)
                        .where(
                            DurableJob.id == record_id,
                            DurableJob.lease_token == token,
                            DurableJob.status == "running",
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row:
                    permanent = (
                        isinstance(exc, HTTPException)
                        and exc.status_code < 500
                        and exc.status_code != 429
                    )
                    row.status = (
                        "failed" if permanent or row.attempts >= row.max_attempts else "retry"
                    )
                    row.error_code = type(exc).__name__
                    row.available_at = datetime.utcnow() + timedelta(
                        seconds=min(300, 10**row.attempts)
                    )
                    row.lease_until, row.lease_token = None, None
                    if row.status == "failed":
                        row.finished_at = datetime.utcnow()
                    denied = isinstance(exc, HTTPException) and exc.status_code in {401, 403, 404}
                    await audit_failed_attempt(
                        db, row, token, "denied" if denied else "failed", duration_ms=duration_ms
                    )
                    await db.commit()
        logger.warning("durable_job_attempt_failed")
    return True


async def schedule_reminders() -> None:
    with bypass_tenant_filter():
        async with async_session_maker() as db:
            users = list(
                (
                    await db.execute(
                        select(User)
                        .join(Tenant, User.tenant_id == Tenant.id)
                        .where(
                            User.is_active.is_(True),
                            User.is_deleted.is_(False),
                            Tenant.is_active.is_(True),
                            Tenant.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
    for user in users:
        with tenant_context(str(user.tenant_id)):
            async with async_session_maker() as db:
                scheduled: tuple[tuple[JobKind, int], ...] = (
                    ("member_reminders", settings.MEMBER_REMINDER_SCAN_SECONDS),
                    ("assessment_reminders", settings.ASSESSMENT_REMINDER_SCAN_SECONDS),
                )
                for kind, interval in scheduled:
                    if has_permission(user.role, JOB_PERMISSIONS[kind]):
                        slot = int(datetime.utcnow().timestamp() // interval)
                        await enqueue(db, user, JobCreate(kind=kind, dedup_key=f"scheduled-{slot}"))
                await db.commit()


async def worker_loop() -> None:
    from app.core.request_audit import replay

    last_scan = 0.0
    while True:
        try:
            now = asyncio.get_running_loop().time()
            if now - last_scan >= 60:
                await schedule_reminders()
                await replay()
                last_scan = now
            if not await run_once():
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("durable_worker_dependencies_unavailable")
            await asyncio.sleep(5)
