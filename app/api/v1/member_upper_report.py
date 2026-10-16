"""上级党组织审批 / 备案报送 API（模块2 延伸 / T-MEM-11）：报送、批复回填、作废与导出。

权限沿用党员发展口径：查询 ``member.query``；报送 / 回填 / 作废 ``member.stage_transition``。

这里没有、也不会有"审批通过"接口：系统没有上级党组织的登录身份，回填接口登记的是
**上级的批复结果**（含批复文号），不是系统的结论；回填也不改动党员的阶段。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.constants import XLSX_MEDIA_TYPE
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.member_upper_report import UpperReportCreate, UpperReportRevoke, UpperReportSettle
from app.services.audit_export import MAX_EXPORT_ROWS
from app.services.member_upper_report_service import UpperReportService
from app.services.roster_io import build_upper_report_export

router = APIRouter()
_query = require_permissions(Permission.MEMBER_QUERY)
_manage = require_permissions(Permission.STAGE_TRANSITION)


async def report_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> UpperReportService:
    """鉴权依赖与服务共用同一请求事务。"""
    return await UpperReportService(db, user).initialize()


async def respond(
    request: Request,
    service: UpperReportService,
    data: dict[str, Any],
    action: str,
    resource_id: str | None = None,
) -> APIResponse[dict]:
    """审计只留事项、类别、状态、档案编号与批复文号，不复制备注正文。"""
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type="member_upper_report",
        resource_id=resource_id,
        data_level="sensitive",
        new_value={
            key: data[key]
            for key in (
                "item",
                "kind",
                "status",
                "result",
                "profile_id",
                "reply_no",
                "total",
            )
            if key in data
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/member-full/upper-reports", response_model=APIResponse[dict])
async def list_upper_reports(
    request: Request,
    item: str | None = Query(None, max_length=40),
    kind: str | None = Query(None, pattern="^(record|approval)$"),
    status: str | None = Query(None, pattern="^(submitted|settled|revoked)$"),
    org_unit_id: str | None = Query(None, max_length=36),
    profile_id: str | None = Query(None, max_length=36),
    overdue: bool = Query(False, description="只看超过审批时限仍未回填批复的"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: UpperReportService = Depends(report_service),
) -> APIResponse[dict]:
    """报送台账：备案 / 审批事项、报送要素与批复结果，附待批复与超期汇总。"""
    data = await service.list_reports(
        item=item,
        kind=kind,
        status=status,
        org_unit_id=org_unit_id,
        profile_id=profile_id,
        overdue_only=overdue,
        page=page,
        page_size=page_size,
    )
    return await respond(request, service, data, "read_member_upper_reports")


@router.post(
    "/member-full/upper-reports",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def create_upper_report(
    request: Request,
    body: UpperReportCreate,
    service: UpperReportService = Depends(report_service),
) -> APIResponse[dict]:
    """登记一次向上级党组织的报送：事项由后端映射依据与随报材料清单。"""
    data = await service.create(body)
    return await respond(request, service, data, "create_member_upper_report", data["id"])


@router.get(
    "/member-full/upper-reports/export",
    summary="导出报送台账（Excel）",
)
async def export_upper_reports(
    request: Request,
    service: UpperReportService = Depends(report_service),
) -> Response:
    """导出报送台账：随报材料清单便于交接与对账，不含材料原件与政审材料内容。"""
    rows, total = await service.export_rows(limit=MAX_EXPORT_ROWS + 1)
    if total > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": (
                    f"当前范围共 {total} 条，超过单次导出上限 {MAX_EXPORT_ROWS} 条："
                    "请按组织分批导出，避免生成打不开的大文件。"
                ),
            },
        )
    content = build_upper_report_export(
        rows,
        scope_note=(
            "本表为上级审批 / 备案报送台账：只含报送要素与批复结果，"
            "不含材料原件、也不含政治审查材料内容（另见材料面板与 T-MEM-12）"
        ),
    )
    await audit_operation(
        service.db,
        request,
        service.user,
        action="export_member_upper_reports",
        resource_type="member_upper_report",
        data_level="sensitive",
        new_value={"count": total},
    )
    await service.db.commit()
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="upper-report-export.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/member-full/upper-reports/{report_id}", response_model=APIResponse[dict])
async def upper_report_detail(
    request: Request,
    report_id: str,
    service: UpperReportService = Depends(report_service),
) -> APIResponse[dict]:
    """单条报送明细与只追加操作留痕。"""
    data = await service.detail(report_id)
    return await respond(request, service, data, "read_member_upper_report", report_id)


@router.post(
    "/member-full/upper-reports/{report_id}/settle",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def settle_upper_report(
    request: Request,
    report_id: str,
    body: UpperReportSettle,
    service: UpperReportService = Depends(report_service),
) -> APIResponse[dict]:
    """回填上级批复结果（同意 / 不同意 / 需补充材料）；不改动党员阶段。"""
    data = await service.settle(report_id, body)
    return await respond(request, service, data, "settle_member_upper_report", report_id)


@router.post(
    "/member-full/upper-reports/{report_id}/revoke",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def revoke_upper_report(
    request: Request,
    report_id: str,
    body: UpperReportRevoke,
    service: UpperReportService = Depends(report_service),
) -> APIResponse[dict]:
    """作废本次报送（报错事项 / 重复报送 / 报送有误），记录保留可查。"""
    data = await service.revoke(report_id, body)
    return await respond(request, service, data, "revoke_member_upper_report", report_id)
