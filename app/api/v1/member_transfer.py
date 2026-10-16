"""党员组织关系接转 API（模块2 延伸 / T-MEM-14）：转入 / 转出、介绍信、回执与作废。

权限沿用党员发展口径：查询 ``member.query``；登记、回执与作废 ``member.stage_transition``。
接转只登记事实（介绍信要素、对方组织、回执），不代替上级审批与备案（见 T-MEM-11），
也不自动认定"已接收"。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.member_transfer import TransferCreate, TransferRevoke, TransferSettle
from app.services.member_transfer_service import TransferService

router = APIRouter()
_query = require_permissions(Permission.MEMBER_QUERY)
_manage = require_permissions(Permission.STAGE_TRANSITION)


async def transfer_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> TransferService:
    """鉴权依赖与服务共用同一请求事务。"""
    return await TransferService(db, user).initialize()


async def respond(
    request: Request,
    service: TransferService,
    data: dict[str, Any],
    action: str,
    resource_id: str | None = None,
) -> APIResponse[dict]:
    """审计只留方向、状态、档案编号与介绍信号，不复制备注正文。"""
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type="member_transfer",
        resource_id=resource_id,
        data_level="sensitive",
        new_value={
            key: data[key]
            for key in (
                "direction",
                "status",
                "profile_id",
                "letter_no",
                "created_profile",
                "total",
            )
            if key in data
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/member-full/transfers", response_model=APIResponse[dict])
async def list_transfers(
    request: Request,
    direction: str | None = Query(None, pattern="^(in|out)$"),
    status: str | None = Query(None, pattern="^(pending|settled|revoked)$"),
    org_unit_id: str | None = Query(None, max_length=36),
    profile_id: str | None = Query(None, max_length=36),
    overdue: bool = Query(False, description="只看超过介绍信有效期仍未回执的"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: TransferService = Depends(transfer_service),
) -> APIResponse[dict]:
    """接转台账：转入 / 转出与介绍信，附待接收、待核对与逾期汇总。"""
    data = await service.list_transfers(
        direction=direction,
        status=status,
        org_unit_id=org_unit_id,
        profile_id=profile_id,
        overdue_only=overdue,
        page=page,
        page_size=page_size,
    )
    return await respond(request, service, data, "read_member_transfers")


@router.post(
    "/member-full/transfers",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def create_transfer(
    request: Request,
    body: TransferCreate,
    service: TransferService = Depends(transfer_service),
) -> APIResponse[dict]:
    """登记一次接转：转出沿用名册档案；转入可关联既有档案或新建档案并核对档案清单。"""
    data = await service.create(body)
    return await respond(request, service, data, "create_member_transfer", data["id"])


@router.get("/member-full/transfers/{transfer_id}", response_model=APIResponse[dict])
async def transfer_detail(
    request: Request,
    transfer_id: str,
    service: TransferService = Depends(transfer_service),
) -> APIResponse[dict]:
    """单条接转明细与只追加操作留痕。"""
    data = await service.detail(transfer_id)
    return await respond(request, service, data, "read_member_transfer", transfer_id)


@router.post(
    "/member-full/transfers/{transfer_id}/settle",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def settle_transfer(
    request: Request,
    transfer_id: str,
    body: TransferSettle,
    service: TransferService = Depends(transfer_service),
) -> APIResponse[dict]:
    """登记回执：转出收到回执才算转出完成；转入则标记档案核对完成。"""
    data = await service.settle(transfer_id, body)
    return await respond(request, service, data, "settle_member_transfer", transfer_id)


@router.post(
    "/member-full/transfers/{transfer_id}/revoke",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def revoke_transfer(
    request: Request,
    transfer_id: str,
    body: TransferRevoke,
    service: TransferService = Depends(transfer_service),
) -> APIResponse[dict]:
    """作废本次接转（介绍信开错 / 未办成 / 回执录错），记录保留可查。"""
    data = await service.revoke(transfer_id, body)
    return await respond(request, service, data, "revoke_member_transfer", transfer_id)
