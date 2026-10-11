"""当前租户的账号创建、持久配置和只追加审计日志。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.audit import audit_operation
from app.core.audit import query_audit_logs
from app.core.config import tenant_config
from app.core.security import Permission, hash_password
from app.db.session import get_db
from app.deps import require_permissions, require_roles
from app.models.audit import AuditLog
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.schemas.admin import AccountCreated, AccountCreateRequest, AccountOrgOption
from app.schemas.auth import UserInfo
from app.schemas.common import APIResponse
from app.services.org_scope import accessible_org_units

router = APIRouter()
_require_config = require_permissions(Permission.CONFIG_MANAGE)
_require_audit = require_permissions(Permission.AUDIT_QUERY)
_require_system_admin = require_roles(UserRole.SYSTEM_ADMIN)

# 与角色的业务范围一致；系统管理员可以绑定当前租户内的任意有效组织。
_ROLE_ORG_TYPES = {
    UserRole.SCHOOL_ADMIN: "school",
    UserRole.DEPARTMENT_ADMIN: "department",
    UserRole.BRANCH_SECRETARY: "branch",
    UserRole.ORGANIZER: "branch",
    UserRole.MEMBER: "branch",
    UserRole.APPLICANT: "branch",
}


@router.get(
    "/admin/org-units",
    response_model=APIResponse[list[AccountOrgOption]],
    summary="账号可分配的组织",
)
async def account_org_units(
    request: Request,
    user: User = Depends(_require_system_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[AccountOrgOption]]:
    """仅系统管理员可获取当前租户的有效组织选项。"""
    organizations = await accessible_org_units(db, user)
    return APIResponse(
        data=[
            AccountOrgOption(id=str(org.id), name=org.name, org_type=org.org_type)
            for org in organizations
            if org.org_type in {"school", "department", "branch"}
        ],
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post(
    "/admin/users",
    response_model=APIResponse[AccountCreated],
    status_code=201,
    summary="创建登录账号",
)
async def create_account(
    body: AccountCreateRequest,
    request: Request,
    user: User = Depends(_require_system_admin),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[AccountCreated]:
    """创建同租户账号，并在同一事务内记录不含密码的审计日志。"""
    organization = (
        await db.execute(
            select(OrgUnit)
            .where(
                OrgUnit.id == body.org_unit_id,
                OrgUnit.tenant_id == str(user.tenant_id),
                OrgUnit.is_deleted.is_(False),
                OrgUnit.org_type.in_(["school", "department", "branch"]),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=403, detail="请选择当前租户内的有效组织")
    expected_type = _ROLE_ORG_TYPES.get(body.role)
    if expected_type and organization.org_type != expected_type:
        raise HTTPException(status_code=422, detail="所选角色与组织类型不匹配")

    existing = (
        await db.execute(
            select(User.id).where(
                User.tenant_id == str(user.tenant_id), User.username == body.username
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名不可用，请更换后重试")

    account = User(
        tenant_id=str(user.tenant_id),
        username=body.username,
        name=body.name,
        password_hash=await run_in_threadpool(hash_password, body.password.get_secret_value()),
        role=body.role,
        org_unit_id=str(organization.id),
        is_active=True,
    )
    db.add(account)
    try:
        await db.flush()
    except IntegrityError as exc:
        # 用户名全局唯一；同时处理跨租户重名与并发创建，不泄露已有账号归属。
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名不可用，请更换后重试") from exc
    await audit_operation(
        db,
        request,
        user,
        action="create",
        resource_type="user",
        resource_id=str(account.id),
        new_value={"role": account.role.value, "org_unit_id": account.org_unit_id},
    )
    await db.commit()
    return APIResponse(
        data=AccountCreated(**UserInfo.from_user(account).model_dump(), org_name=organization.name),
        trace_id=getattr(request.state, "trace_id", None),
    )


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
