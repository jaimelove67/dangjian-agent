"""组织生活（三会一课）API：活动计划登记、材料议程、纪要审核、任务台账与考核复用。

权限：支部书记及以上可查询（``meeting.query``）；登记与纪要维护需要
``meeting.manage``；纪要审核需要 ``meeting.review``；归档需要
``meeting.manage`` + ``meeting.archive``。建议与生成内容只作草稿，不代组织结论。
"""

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions, require_roles
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.schemas.meeting import (
    ActivityCreate,
    ActivityUpdate,
    AgendaFromUpdates,
    AgendaItemsRequest,
    DecisionsRequest,
    ImageMutation,
    ReviewRequest,
    RevisionRequest,
    TaskCreate,
    TopicFeedbackRequest,
    TopicSuggestionRequest,
    TaskHandle,
    TaskUpdate,
)
from app.services.activity_service import ACTIVITY_TYPES, ActivityService
from app.services.meeting_document_export import build_meeting_docx

router = APIRouter()
_query = require_permissions(Permission.MEETING_QUERY)
_manage = require_permissions(Permission.MEETING_MANAGE)
_review = require_permissions(Permission.MEETING_REVIEW)
_archive = require_permissions(Permission.MEETING_MANAGE, Permission.MEETING_ARCHIVE)
# 支部会议由支部书记主持、组织员协助登记；院系和学校管理员只审核、督办、归档。
_operator = require_roles(UserRole.BRANCH_SECRETARY, UserRole.ORGANIZER)
_secretary = require_roles(UserRole.BRANCH_SECRETARY)


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
            "types": [{"value": key, "label": label} for key, label in ACTIVITY_TYPES.items()],
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


@router.post(
    "/meeting/records",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def create_record(
    body: ActivityCreate, request: Request, service: ActivityService = Depends(activity_service)
) -> APIResponse[dict]:
    """登记一次组织生活活动计划。"""
    record = await service.create(body)
    return await respond(
        request, service, await service.record_data(record), "create", "meeting", str(record.id)
    )


@router.post(
    "/meeting/records/{record_id}/images",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def upload_record_image(
    record_id: str,
    request: Request,
    file: UploadFile = File(..., description="JPG、PNG 或 WebP 会议现场图片"),
    expected_revision: int = Form(..., ge=1),
    reason: str = Form(..., min_length=1, max_length=2000),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """上传一张现场图片；图片加密留存，只把元数据写入会议版本。"""
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            413,
            f"图片超过 {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB，请压缩后重试",
        )
    try:
        body = ImageMutation(expected_revision=expected_revision, reason=reason)
    except ValidationError:
        raise HTTPException(422, "请检查会议版本号和图片上传说明") from None
    record, image = await service.add_image(
        record_id,
        file_name=file.filename or "会议现场图片",
        content=content,
        body=body,
    )
    data = await service.record_data(record)
    await audit_operation(
        service.db,
        request,
        service.user,
        action="meeting_image_upload",
        resource_type="meeting",
        resource_id=str(record.id),
        data_level="sensitive",
        new_value={
            "image_id": image["id"],
            "file_name": image["file_name"],
            "size": image["size"],
            "revision": record.revision,
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.delete(
    "/meeting/records/{record_id}/images/{image_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def delete_record_image(
    record_id: str,
    image_id: str,
    body: ImageMutation,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """移除当前版本的图片引用；历史版本和加密原件仍保留可追溯。"""
    record = await service.remove_image(record_id, image_id, body)
    data = await service.record_data(record)
    await audit_operation(
        service.db,
        request,
        service.user,
        action="meeting_image_remove",
        resource_type="meeting",
        resource_id=str(record.id),
        data_level="sensitive",
        new_value={"image_id": image_id, "revision": record.revision},
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


@router.get("/meeting/records/{record_id}/images/{image_id}")
async def download_record_image(
    record_id: str,
    image_id: str,
    service: ActivityService = Depends(activity_service),
) -> Response:
    """按会议记录的授权范围读取图片原件；不暴露本地存储路径。"""
    content, image = await service.read_image(record_id, image_id)
    file_name = str(image.get("file_name") or "会议现场图片")
    return Response(
        content=content,
        media_type=str(image.get("content_type") or "application/octet-stream"),
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(file_name, safe='')}",
        },
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
    "/meeting/records/{record_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def update_record(
    record_id: str,
    body: ActivityUpdate,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """登记会议文本与参会情况，修改后重新审核纪要。"""
    record = await service.update(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "revise", "meeting", record_id
    )


@router.patch(
    "/meeting/records/{record_id}/agenda-items",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def update_agenda_items(
    record_id: str,
    body: AgendaItemsRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """保存人工编辑的议题条目，并同步更新议题单正文。"""
    record = await service.update_agenda_items(record_id, body)
    return await respond(
        request,
        service,
        await service.record_data(record),
        "update_agenda_items",
        "meeting",
        record_id,
    )


@router.patch(
    "/meeting/records/{record_id}/decisions",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def update_decisions(
    record_id: str,
    body: DecisionsRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """保存人工登记的会议决议和表决结果。"""
    record = await service.update_decisions(record_id, body)
    return await respond(
        request,
        service,
        await service.record_data(record),
        "update_decisions",
        "meeting",
        record_id,
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
        request,
        service,
        await service.recommendations(record_id, q),
        "recommend_materials",
        "meeting",
        record_id,
    )


@router.post(
    "/meeting/topic-suggestions",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def topic_suggestions(
    body: TopicSuggestionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """根据最新资料推荐会议主题，选中后再由人工创建会议草稿。"""
    return await respond(
        request,
        service,
        await service.topic_suggestions(body),
        "suggest_meeting_topics",
        "meeting",
    )


@router.post(
    "/meeting/topic-feedback",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def topic_feedback(
    body: TopicFeedbackRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """记录“有用 / 不相关 / 已开展”，只影响后续推荐，不自动改变会议状态。"""
    result = await service.topic_feedback(body)
    await audit_operation(
        service.db,
        request,
        service.user,
        action="feedback_meeting_topic",
        resource_type="meeting_topic",
        resource_id=None,
        data_level="internal",
        new_value={
            "org_unit_id": body.org_unit_id,
            "decision": body.decision,
            "activity_type": body.activity_type,
        },
    )
    await service.db.commit()
    return APIResponse(data=result, trace_id=getattr(request.state, "trace_id", None))


@router.post(
    "/meeting/records/{record_id}/generate-agenda",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def generate_agenda(
    record_id: str,
    body: RevisionRequest,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """生成会议通知、议题单和记录模板，供支部研究确定。"""
    record = await service.generate_agenda(record_id, body)
    return await respond(
        request, service, await service.record_data(record), "generate_agenda", "meeting", record_id
    )


@router.get(
    "/meeting/records/{record_id}/external-suggestions",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def external_suggestions(
    record_id: str,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """列出可用于当前会议的最新外部资料；普通办理人只看已采用资料。"""
    items = await service.external_suggestions(record_id)
    return APIResponse(data={"items": items}, trace_id=getattr(request.state, "trace_id", None))


@router.post(
    "/meeting/records/{record_id}/generate-agenda-from-updates",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
)
async def generate_agenda_from_updates(
    record_id: str,
    body: AgendaFromUpdates,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """批量采用所选外部资料，再生成通知、议题单和记录模板。"""
    record = await service.generate_agenda_from_external(record_id, body)
    if body.external_update_ids:
        await audit_operation(
            service.db,
            request,
            service.user,
            action="adopt_external_updates",
            resource_type="meeting",
            resource_id=record_id,
            data_level="public",
            new_value={"external_update_ids": body.external_update_ids},
        )
    return await respond(
        request,
        service,
        await service.record_data(record),
        "generate_agenda_from_updates",
        "meeting",
        record_id,
    )


@router.post(
    "/meeting/records/{record_id}/generate-minutes",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
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
        request,
        service,
        await service.record_data(record),
        "generate_minutes",
        "meeting",
        record_id,
    )


@router.post(
    "/meeting/records/{record_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator), Depends(_secretary)],
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


@router.get(
    "/meeting/records/{record_id}/documents.docx",
    summary="导出会议文书 Word",
)
async def export_record_docx(
    record_id: str,
    request: Request,
    service: ActivityService = Depends(activity_service),
) -> Response:
    """导出当前可访问会议的通知、议题、资料、记录和决议。"""
    record = await service.record(record_id)
    data = await service.record_data(record)
    if data.get("restricted"):
        raise HTTPException(403, "关联资料权限已变化，不能导出会议文书")
    content = build_meeting_docx(data)
    await audit_operation(
        service.db,
        request,
        service.user,
        action="export_meeting_documents",
        resource_type="meeting",
        resource_id=record_id,
        data_level="sensitive",
        new_value={"format": "docx", "revision": data.get("revision")},
    )
    await service.db.commit()
    filename = quote(f"{record.title}-会议文书.docx", safe="")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/meeting/records/{record_id}/tasks",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
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
    "/meeting/tasks/{task_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage), Depends(_operator)],
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
    dependencies=[Depends(_manage), Depends(_operator)],
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


@router.get("/meeting/frequency", response_model=APIResponse[dict])
async def frequency(
    request: Request,
    as_of: date | None = Query(None, description="按哪一天判断当前周期，缺省为今天"),
    org_unit_id: str | None = Query(None, max_length=36),
    service: ActivityService = Depends(activity_service),
) -> APIResponse[dict]:
    """三会一课周期频次与本周期提醒；完成认定只认已召开且人工审核通过的记录。"""
    return await respond(
        request,
        service,
        await service.frequency(org_unit_id, as_of or date.today()),
        "read_frequency",
    )
