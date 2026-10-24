"""School notices, supervision, role applications and versioned school rules."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.tenant import bypass_tenant_filter
from app.db.session import get_db
from app.deps import get_current_user
from app.models.meeting import ContentRevision
from app.models.user import User
from app.schemas import school_business as schema
from app.schemas.common import APIResponse
from app.services.school_business_service import SchoolBusinessService, view

router = APIRouter()


async def service(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SchoolBusinessService:
    return SchoolBusinessService(db, user)


async def respond(
    s: SchoolBusinessService, request: Request, data: Any, action: str, record_id: str | None = None
) -> APIResponse:
    await audit_operation(
        s.db, request, s.user, action=action, resource_type="school_business", resource_id=record_id
    )
    await s.db.commit()
    return APIResponse(data=data)


@router.get("/school/business/records")
async def records(
    kind: Literal["notice", "task", "permission"],
    tenant_id: str | None = None,
    s: SchoolBusinessService = Depends(service),
) -> APIResponse:
    return APIResponse(data=await s.list_records(kind, tenant_id))


@router.get("/school/business/records/{record_id}")
async def detail(record_id: str, s: SchoolBusinessService = Depends(service)) -> APIResponse:
    row = await s.record(record_id)
    with bypass_tenant_filter():
        revisions = list(
            (
                await s.db.execute(
                    select(ContentRevision)
                    .where(
                        ContentRevision.tenant_id == row.tenant_id,
                        ContentRevision.resource_type == "school_business",
                        ContentRevision.resource_id == row.id,
                    )
                    .order_by(ContentRevision.revision)
                )
            ).scalars()
        )
    return APIResponse(
        data={
            **view(row),
            "history": [
                {
                    "id": r.id,
                    "revision": r.revision,
                    "actor_id": r.actor_id,
                    "action": r.action,
                    "reason": r.reason,
                    "created_at": r.created_at,
                }
                for r in revisions
            ],
        }
    )


@router.post("/school/business/notices")
async def create_notice(
    body: schema.NoticeCreate, request: Request, s: SchoolBusinessService = Depends(service)
) -> APIResponse:
    row = await s.create("notice", body)
    return await respond(s, request, view(row), "notice_create", row.id)


@router.post("/school/business/tasks")
async def create_task(
    body: schema.TaskCreate, request: Request, s: SchoolBusinessService = Depends(service)
) -> APIResponse:
    row = await s.create("task", body)
    return await respond(s, request, view(row), "school_task_create", row.id)


@router.post("/school/business/permission-requests")
async def create_permission(
    body: schema.PermissionCreate, request: Request, s: SchoolBusinessService = Depends(service)
) -> APIResponse:
    row = await s.create("permission", body)
    return await respond(s, request, view(row), "permission_request_create", row.id)


@router.post("/school/business/records/{record_id}/publish")
async def publish(
    record_id: str,
    body: schema.Action,
    request: Request,
    s: SchoolBusinessService = Depends(service),
) -> APIResponse:
    row = await s.record(record_id, lock=True)
    await s.publish(row, body)
    return await respond(s, request, view(row), "school_publish", row.id)


@router.post("/school/business/records/{record_id}/complete")
async def complete(
    record_id: str,
    body: schema.Complete,
    request: Request,
    s: SchoolBusinessService = Depends(service),
) -> APIResponse:
    row = await s.record(record_id, lock=True)
    await s.complete(row, body)
    return await respond(s, request, view(row), "school_task_submit", row.id)


@router.post("/school/business/records/{record_id}/review")
async def review(
    record_id: str,
    body: schema.Review,
    request: Request,
    s: SchoolBusinessService = Depends(service),
) -> APIResponse:
    row = await s.record(record_id, lock=True)
    await s.review(row, body)
    return await respond(s, request, view(row), "school_business_review", row.id)


@router.post("/school/business/records/{record_id}/archive")
async def archive(
    record_id: str,
    body: schema.Action,
    request: Request,
    s: SchoolBusinessService = Depends(service),
) -> APIResponse:
    row = await s.record(record_id, lock=True)
    await s.archive(row, body)
    return await respond(s, request, view(row), "school_task_archive", row.id)


@router.get("/school/business/rules")
async def rules(s: SchoolBusinessService = Depends(service)) -> APIResponse:
    _, values = await s.rules()
    return APIResponse(data=values)


@router.put("/school/business/rules")
async def save_rules(
    body: schema.Rules, request: Request, s: SchoolBusinessService = Depends(service)
) -> APIResponse:
    return await respond(s, request, await s.save_rules(body), "school_rules_update")
