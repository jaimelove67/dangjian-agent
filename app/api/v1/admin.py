"""管理查询：当前租户的持久配置和只追加审计日志。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.audit import query_audit_logs
from app.core.config import tenant_config
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.common import APIResponse

router = APIRouter()
_require_config = require_permissions(Permission.CONFIG_MANAGE)
_require_audit = require_permissions(Permission.AUDIT_QUERY)


class TenantSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrieval_top_k: Optional[int] = Field(None, ge=1, le=50)
    rerank_top_k: Optional[int] = Field(None, ge=1, le=50)
    no_evidence_threshold: Optional[float] = Field(None, ge=0.05, le=1)
    exclude_expired_by_default: Optional[bool] = None
    activist_training_days: Optional[int] = Field(None, ge=1, le=3650)
    probationary_period_days: Optional[int] = Field(None, ge=1, le=3650)


@router.get("/admin/config", response_model=APIResponse[dict], summary="租户有效配置")
async def read_config(
    request: Request, user: User = Depends(_require_config), db: AsyncSession = Depends(get_db)
):
    await tenant_config.load(db, str(user.tenant_id))
    return APIResponse(
        data={
            key: tenant_config.get(str(user.tenant_id), key) for key in TenantSettings.model_fields
        },
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.patch("/admin/config", response_model=APIResponse[dict], summary="保存租户配置")
async def update_config(
    body: TenantSettings,
    request: Request,
    user: User = Depends(_require_config),
    db: AsyncSession = Depends(get_db),
):
    values = body.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(status_code=422, detail="必须提供非空配置值")
    old = {key: tenant_config.get(str(user.tenant_id), key) for key in values}
    try:
        await tenant_config.save(db, str(user.tenant_id), values)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit_operation(
        db,
        request,
        user,
        action="update",
        resource_type="tenant_config",
        resource_id=str(user.tenant_id),
        old_value=old,
        new_value=values,
    )
    await db.commit()
    return await read_config(request, user, db)


@router.get("/admin/audit-logs", response_model=APIResponse[dict], summary="审计日志查询")
async def read_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    action: Optional[str] = Query(None, max_length=50),
    resource_type: Optional[str] = Query(None, max_length=50),
    user: User = Depends(_require_audit),
    db: AsyncSession = Depends(get_db),
):
    stmt = query_audit_logs(
        tenant_id=str(user.tenant_id), action=action, resource_type=resource_type
    )
    total = (
        await db.execute(stmt.with_only_columns(func.count()).select_from(AuditLog).order_by(None))
    ).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    items = [
        {
            key: getattr(row, key)
            for key in (
                "id",
                "user_name",
                "action",
                "resource_type",
                "resource_id",
                "data_level",
                "request_id",
                "result",
                "old_value",
                "new_value",
            )
        }
        | {"created_at": row.created_at.isoformat()}
        for row in rows
    ]
    return APIResponse(
        data={"items": items, "total": total, "page": page, "page_size": page_size},
        trace_id=getattr(request.state, "trace_id", None),
    )
