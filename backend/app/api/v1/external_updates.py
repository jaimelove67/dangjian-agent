"""三会一课最新外部资料：抓取、审核与知识库发布。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.external import ExternalUpdate
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.schemas.external import ExternalReviewRequest
from app.services.external_update_service import fetch_updates, review_update

router = APIRouter()
_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _payload(row: ExternalUpdate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "summary": row.summary,
        "published_at": row.published_at,
        "fetched_at": row.fetched_at,
        "status": row.status,
        "review_note": row.review_note,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "knowledge_doc_id": row.knowledge_doc_id,
    }


def _ensure_school(user: User) -> None:
    if user.role == UserRole.SYSTEM_ADMIN:
        raise HTTPException(403, "平台管理员不办理学校三会一课资料。")


@router.get("/external-updates", response_model=APIResponse[dict])
async def list_external_updates(
    request: Request,
    status: str | None = Query(None, pattern=r"^(pending|approved|rejected)$"),
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    _ensure_school(user)
    query = select(ExternalUpdate).where(
        ExternalUpdate.tenant_id == str(user.tenant_id),
        ExternalUpdate.is_deleted.is_(False),
    )
    if status:
        query = query.where(ExternalUpdate.status == status)
    rows = (
        (
            await db.execute(
                query.order_by(
                    ExternalUpdate.fetched_at.desc(), ExternalUpdate.created_at.desc()
                ).limit(200)
            )
        )
        .scalars()
        .all()
    )
    return APIResponse(data={"items": [_payload(row) for row in rows]}, trace_id=_trace(request))


@router.post("/external-updates/fetch", response_model=APIResponse[dict])
async def fetch_external_updates(
    request: Request,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    _ensure_school(user)
    try:
        result = await fetch_updates(db, user)
        await audit_operation(
            db,
            request,
            user,
            action="fetch_external_updates",
            resource_type="external_update",
            data_level="public",
            new_value={
                "added": result["added"],
                "skipped": result["skipped"],
                "errors": len(result["errors"]),
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return APIResponse(data=result, trace_id=_trace(request))


@router.post("/external-updates/{update_id}/review", response_model=APIResponse[dict])
async def review_external_update(
    update_id: str,
    body: ExternalReviewRequest,
    request: Request,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    _ensure_school(user)
    row, doc = await review_update(db, user, update_id, body.decision, body.note)
    await audit_operation(
        db,
        request,
        user,
        action=f"{body.decision}_external_update",
        resource_type="external_update",
        resource_id=str(row.id),
        data_level="public",
        new_value={
            "status": row.status,
            "source_url": row.source_url,
            "knowledge_doc_id": row.knowledge_doc_id,
            "note": body.note,
        },
    )
    await db.commit()
    data = _payload(row)
    if doc is not None:
        data["knowledge_doc"] = {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "summary": doc.summary,
        }
    return APIResponse(data=data, trace_id=_trace(request))
