"""Controlled operations API; no overwrite/cleanup or arbitrary destination API is exposed."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.db.session import get_db
from app.deps import get_current_user
from app.models.backup import BackupJob
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.school_business import Input
from app.services import backup_service as service

router = APIRouter()


class Create(Input):
    name: str = Field(min_length=1, max_length=200)
    dedup_key: str = Field(min_length=1, max_length=100)
    confirm_maintenance: bool
    source_id: str | None = Field(default=None, max_length=36)


@router.get("/admin/backups")
async def list_backups(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> APIResponse:
    await service.require_platform(db, user)
    rows = list(
        (
            await db.execute(
                select(BackupJob)
                .where(BackupJob.tenant_id == user.tenant_id)
                .order_by(BackupJob.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return APIResponse(
        data={"capabilities": service.capabilities(), "items": [service.view(r) for r in rows]}
    )


@router.post("/admin/backups")
async def create_backup(
    body: Create,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    await service.require_platform(db, user)
    caps = service.capabilities()
    if not caps["enabled"] or not caps["database_tools"]:
        raise HTTPException(503, "维护接口尚未启用或未配置 PostgreSQL 备份恢复客户端")
    if not body.confirm_maintenance:
        raise HTTPException(422, "请确认短暂维护窗口及仅写隔离目标的恢复范围")
    from app.services.identity_service import IdentityService

    await IdentityService(db, user).tenant(lock=True)
    current = (
        await db.execute(
            select(BackupJob).where(
                BackupJob.tenant_id == user.tenant_id, BackupJob.dedup_key == body.dedup_key
            )
        )
    ).scalar_one_or_none()
    if current:
        if current.source_id != body.source_id or current.name != body.name:
            raise HTTPException(409, "请求编号已经用于不同维护任务")
        return APIResponse(data=service.view(current))
    active = (
        await db.execute(
            select(BackupJob.id).where(
                BackupJob.tenant_id == user.tenant_id, BackupJob.status.in_(["queued", "running"])
            )
        )
    ).first()
    if active:
        raise HTTPException(409, "已有维护任务未结束，请查看任务状态")
    if body.source_id:
        source = (
            await db.execute(
                select(BackupJob).where(
                    BackupJob.id == body.source_id,
                    BackupJob.tenant_id == user.tenant_id,
                    BackupJob.kind == "backup",
                    BackupJob.status == "succeeded",
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise HTTPException(404, "可恢复的真实备份不存在")
        if not caps["restore_configured"]:
            raise HTTPException(503, "隔离恢复数据库管理连接及独立 Redis 目标尚未配置")
    row = BackupJob(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        actor_id=user.id,
        name=body.name,
        kind="restore_drill" if body.source_id else "backup",
        source_id=body.source_id,
        dedup_key=body.dedup_key,
        status="queued",
        result={},
    )
    db.add(row)
    await audit_operation(
        db, request, user, action="backup_job_create", resource_type="backup", resource_id=row.id
    )
    await db.commit()
    service.launch(str(user.tenant_id), row.id)
    return APIResponse(data=service.view(row))


@router.get("/admin/backups/{record_id}/file")
async def file(
    record_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    await service.require_platform(db, user)
    row = (
        await db.execute(
            select(BackupJob).where(
                BackupJob.id == record_id,
                BackupJob.tenant_id == user.tenant_id,
                BackupJob.kind == "backup",
                BackupJob.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    if row is None or not service.bundle_path(row.id).is_file():
        raise HTTPException(404, "备份文件不存在")
    return FileResponse(
        service.bundle_path(row.id),
        filename=f"backup-{row.id}.sealed",
        media_type="application/octet-stream",
    )
