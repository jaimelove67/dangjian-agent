"""组织生活（三会一课）API：活动计划登记、材料议程、纪要审核、任务台账与考核复用。

权限：支部书记及以上可查询（``meeting.query``）；登记与纪要维护需要
``meeting.manage``；纪要审核需要 ``meeting.review``；归档需要
``meeting.manage`` + ``meeting.archive``。建议与生成内容只作草稿，不代组织结论。
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
from app.schemas.meeting import (
    ActivityCreate,
    ActivityUpdate,
    ReviewRequest,
    RevisionRequest,
    TaskCreate,
    TaskHandle,
    TaskUpdate,
)
from app.services.activity_service import ACTIVITY_TYPES, ActivityService

router = APIRouter()
_query = require_permissions(Permission.MEETING_QUERY)
_manage = require_permissions(Permission.MEETING_MANAGE)
_review = require_permissions(Permission.MEETING_REVIEW)
_archive = require_permissions(Permission.MEETING_MANAGE, Permission.MEETING_ARCHIVE)


async def activity_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> ActivityService:
    """鉴权依赖和服务共用同一请求事务。"""
    return await ActivityService(db, user).initialize()


async def respond(
    request: Request,
    service: ActivityService,
    data: dict[str, Any],
    action: str,
    resource_type: str = "meeting",
    resource_id: str | None = None,
) -> APIResponse[dict]:
    """审计仅存编号、版本及数量，不复制人员、原文或政策资料正文。"""
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_level="sensitive",
        new_value={key: data[key] for key in ("revision", "total", "year") if key in data},
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/meeting/org-units", response_model=APIResponse[dict])
async def organizations(
    request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """查询当前人员可访问的组织范围。"""
    return await respond(
        request,
        service,
        {
            "items": [
                {"id": str(org.id), "name": org.name, "org_type": org.org_type}
                for org in service.orgs
            ]
        },
        "read_orgs",
    )


@router.get("/meeting/type-options", response_model=APIResponse[dict])
async def type_options(
    request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """活动类型与年度规定频次提示（频次仅提示，不自动认定完成）。"""
    return await respond(
        request,
        service,
        {
            "types": [
                {"value": key, "label": label} for key, label in ACTIVITY_TYPES.items()
            ],
            "requirements": None,
        },
        "read_type_options",
    )


@router.get("/meeting/records", response_model=APIResponse[dict])
async def records(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    activity_type: str | None = Query(None, max_length=40),
    execution_status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """按年度、组织、类型与执行状态分页查询组织生活计划与记录。"""
    return await respond(
        request,
        service,
        await service.list_records(
            year=year,
            org_unit_id=org_unit_id,
            activity_type=activity_type,
            execution_status=execution_status,
            page=page,
            page_size=page_size,
        ),
        "read_records",
    )


@router.post("/meeting/records", response_model=APIResponse[dict], dependencies=[Depends(_manage)])
async def create_record(
    body: ActivityCreate, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """登记一次组织生活活动计划。"""
    record = await service.create(body)
    return await respond(
        request, service, await service.record_data(record), "create", "meeting", str(record.id)
    )


@router.get("/meeting/records/{record_id}", response_model=APIResponse[dict])
async def record_detail(
    record_id: str, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """读取当前权限和合规开关允许的活动记录。"""
    record = await service.record(record_id)
    return await respond(
        request, service, await service.record_data(record), "read", "meeting", record_id
    )


@router.patch(
    "/meeting/records/{record_id}", response_model=APIResponse[dict], dependencies=[Depends(_manage)]
)
async def update_record(
    record_id: str, body: ActivityUpdate, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """登记会议文本与参会情况，修改后重新审核纪要。"""
    record = await service.update(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "revise", "meeting", record_id
    )


@router.get("/meeting/records/{record_id}/recommendations", response_model=APIResponse[dict])
async def recommendations(
    record_id: str,
    request: Request,
    q: str | None = Query(None, min_length=1, max_length=300),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """从授权知识库推荐议题与学习材料，不补写虚构文件。"""
    return await respond(
        request, service, await service.recommendations(record_id, q), "recommend_materials", "meeting", record_id
    )


@router.post(
    "/meeting/records/{record_id}/generate-agenda",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def generate_agenda(
    record_id: str,
    body: RevisionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """生成有真实摘录的通知与议程草稿，供支部研究确定。"""
    record = await service.generate_agenda(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "generate_agenda", "meeting", record_id
    )


@router.post(
    "/meeting/records/{record_id}/generate-minutes",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def generate_minutes(
    record_id: str,
    body: RevisionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """仅提取原文中明确标注的学习要点、共识与工作要求。"""
    record = await service.generate_minutes(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "generate_minutes", "meeting", record_id
    )


@router.post(
    "/meeting/records/{record_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def submit_record(
    record_id: str,
    body: RevisionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """核查原文定位、参会、日期及依据后提交纪要。"""
    record = await service.submit(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "submit", "meeting", record_id
    )


@router.post(
    "/meeting/records/{record_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_review)],
)
async def review_record(
    record_id: str,
    body: ReviewRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """人工审核当前纪要版本，不允许自审。"""
    record = await service.review(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "review", "meeting", record_id
    )


@router.get("/meeting/records/{record_id}/revisions", response_model=APIResponse[dict])
async def record_revisions(
    record_id: str, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """查询纪要修订与审核历史，屏蔽当前不可访问内容。"""
    record = await service.record(record_id)
    return await respond(
        request,
        service,
        {"items": await service.revisions(record)},
        "read_revisions",
        "meeting",
        record_id,
    )


@router.post(
    "/meeting/records/{record_id}/archive",
    response_model=APIResponse[dict],
    dependencies=[Depends(_archive)],
)
async def archive_record(
    record_id: str,
    body: RevisionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """学校确认电子效力后归档人工审核通过的记录。"""
    record = await service.archive(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "archive", "meeting", record_id
    )


@router.get("/meeting/records/{record_id}/export", response_model=APIResponse[dict])
async def export_record(
    record_id: str, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """按当前权限导出归档、材料摘录与确认证据。"""
    return await respond(
        request, service, await service.export(record_id), "export", "meeting", record_id
    )


@router.post(
    "/meeting/records/{record_id}/tasks",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def create_task(
    record_id: str,
    body: TaskCreate,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """从会议原文登记任务摘录；责任人或期限缺省待人工补齐。"""
    task = await service.create_task(record_id, body)
    return await respond(
        request,
        service,
        {"task": task.dict(), "notice": "任务待人工确认责任人与期限后进入台账"},
        "create_task",
        "meeting_task",
        str(task.id),
    )


@router.patch(
    "/meeting/tasks/{task_id}", response_model=APIResponse[dict], dependencies=[Depends(_manage)]
)
async def confirm_task(
    task_id: str,
    body: TaskUpdate,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """人工补齐责任人与期限后确认任务进入台账。"""
    task = await service.confirm_task(task_id, body)
    return await respond(
        request,
        service,
        {"task": task.dict(), "notice": "任务已确认进入台账"},
        "confirm_task",
        "meeting_task",
        task_id,
    )


@router.post(
    "/meeting/tasks/{task_id}/handle",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def handle_task(
    task_id: str,
    body: TaskHandle,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """任务完成或取消，处理结果留痕。"""
    task = await service.handle_task(task_id, body)
    return await respond(
        request,
        service,
        {"task": task.dict(), "notice": "任务处理结果已记录"},
        "handle_task",
        "meeting_task",
        task_id,
    )


@router.get("/meeting/tasks", response_model=APIResponse[dict])
async def tasks(
    request: Request,
    org_unit_id: str | None = Query(None, max_length=36),
    year: int | None = Query(None, ge=2000, le=2100),
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """按组织、年度与状态分页查询任务台账。"""
    return await respond(
        request,
        service,
        await service.list_tasks(
            org_unit_id=org_unit_id, year=year, status=status, page=page, page_size=page_size
        ),
        "read_tasks",
        "meeting_task",
    )


@router.get("/meeting/history", response_model=APIResponse[dict])
async def history(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    activity_type: str | None = Query(None, max_length=40),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """经合规门禁按年度、组织与类型查询历史归档。"""
    return await respond(
        request,
        service,
        await service.history(
            year=year,
            org_unit_id=org_unit_id,
            activity_type=activity_type,
            page=page,
            page_size=page_size,
        ),
        "read_history",
    )


@router.get("/meeting/stats", response_model=APIResponse[dict])
async def stats(
    request: Request,
    year: int = Query(ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """只读归集组织生活次数与参学比例，所有数字保留稳定来源。"""
    return await respond(
        request,
        service,
        await service.stats(year, org_unit_id),
        "read_stats",
    )
