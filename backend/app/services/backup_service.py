"""Reuse authenticated backup scripts; restore only to newly generated isolated targets."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import settings
from app.core.maintenance import quiescence
from app.core.tenant import tenant_context
from app.db.session import async_session_maker
from app.models.backup import BackupJob
from app.models.user import User
from app.services.identity_service import is_platform_admin

running: set[asyncio.Task] = set()


def capabilities() -> dict[str, Any]:
    from scripts.module6_backup import postgres_client_available

    return {
        "enabled": settings.BACKUP_API_ENABLED,
        "database_tools": all(
            postgres_client_available(os.getenv(name, default))
            for name, default in [("PG_DUMP_BIN", "pg_dump"), ("PG_RESTORE_BIN", "pg_restore")]
        ),
        "restore_configured": bool(
            settings.RESTORE_DATABASE_ADMIN_URL
            and settings.RESTORE_REDIS_URL
            and settings.RESTORE_REDIS_URL != settings.REDIS_URL
        ),
        "scope": "当前服务数据库、认证加密文件及认证吊销记录；恢复仅写新建隔离目标",
    }


def root() -> Path:
    path = Path(settings.BACKUP_STORAGE_DIR).absolute()
    if path.resolve() != path:
        raise ValueError("备份目录不能使用符号链接")
    return path


def bundle_path(record_id: str) -> Path:
    safe = str(uuid.UUID(record_id))
    return root() / (safe + ".sealed")


def view(row: BackupJob) -> dict[str, Any]:
    return {
        k: v for k, v in row.dict().items() if k not in {"tenant_id", "is_deleted", "dedup_key"}
    }


async def execute(tenant_id: str, job_id: str) -> None:
    from scripts.module6_backup import backup, db_connect, restore

    with tenant_context(tenant_id):
        async with async_session_maker() as db:
            row = (await db.execute(select(BackupJob).where(BackupJob.id == job_id))).scalar_one()
            user = (
                await db.execute(
                    select(User).where(
                        User.id == row.actor_id,
                        User.tenant_id == tenant_id,
                        User.is_active.is_(True),
                        User.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if user is None or not await is_platform_admin(db, user):
                row.status, row.result = "failed", {"error_code": "actor_unavailable"}
                await db.commit()
                return
            row.status = "running"
            await db.commit()
            try:
                root().mkdir(parents=True, exist_ok=True)
                async with quiescence():
                    if row.kind == "backup":
                        result = await backup(
                            bundle_path(row.id), settings.DATABASE_URL, settings.REDIS_URL, True
                        )
                        result["sha256"] = await asyncio.to_thread(
                            lambda: hashlib.sha256(bundle_path(row.id).read_bytes()).hexdigest()
                        )
                    else:
                        if not capabilities()["restore_configured"]:
                            raise ValueError("隔离恢复连接尚未配置")
                        assert (
                            settings.RESTORE_DATABASE_ADMIN_URL
                            and settings.RESTORE_REDIS_URL
                            and row.source_id
                        )
                        database_name = "module6_restore_" + uuid.uuid4().hex
                        admin_url = make_url(settings.RESTORE_DATABASE_ADMIN_URL)
                        target = admin_url.set(database=database_name).render_as_string(
                            hide_password=False
                        )
                        connection = await db_connect(settings.RESTORE_DATABASE_ADMIN_URL)
                        try:
                            await connection.execute('CREATE DATABASE "' + database_name + '"')
                        finally:
                            await connection.close()
                        directory = root() / "drills" / row.id
                        result = await restore(
                            bundle_path(row.source_id),
                            target,
                            settings.RESTORE_REDIS_URL,
                            directory / "files",
                            directory / "audit",
                            None,
                            True,
                        )
                        result.update(
                            isolated_database=database_name, replaces_current_database=False
                        )
                row.status, row.result = "succeeded", result
            except Exception as exc:
                row.status, row.result = "failed", {
                    "error_code": type(exc).__name__,
                    "message": "维护未完成；请按任务编号查阅受控运维日志，原服务数据未被恢复覆盖",
                }
            row.finished_at = datetime.now(UTC).replace(tzinfo=None)
            await write_audit(
                db,
                tenant_id=tenant_id,
                user_id=row.actor_id,
                user_name=row.actor_id,
                action="backup_job_" + row.status,
                resource_type="backup",
                resource_id=row.id,
                request_id=row.id,
                result="success" if row.status == "succeeded" else "failed",
                data_level="internal",
                new_value={"kind": row.kind, "status": row.status},
            )
            await db.commit()


def launch(tenant_id: str, job_id: str) -> None:
    task = asyncio.create_task(execute(tenant_id, job_id))
    running.add(task)
    task.add_done_callback(running.discard)


async def require_platform(db: AsyncSession, user: User) -> None:
    if not await is_platform_admin(db, user):
        raise HTTPException(403, "仅平台管理员可以维护备份及隔离恢复")
