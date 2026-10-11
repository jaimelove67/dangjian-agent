"""中心组学习 API：年度计划、每期材料、人工审核、归档及只读考核复用。"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.study import (
    ActivityUpdate,
    ArchivePolicyUpdate,
    ItemCreate,
    ItemUpdate,
    PlanCreate,
    PlanUpdate,
    ReviewRequest,
    RevisionRequest,
)
from app.services.archive_service import archive_policy, save_archive_policy
from app.services.meeting_service import STUDY_NOTICE
from app.services.study_materials import recommend_sources
from app.services.study_service import StudyService

router = APIRouter()
_query = require_permissions(Permission.STUDY_QUERY)
_manage = require_permissions(Permission.STUDY_MANAGE)
_review = require_permissions(Permission.STUDY_REVIEW)
_archive = require_permissions(Permission.STUDY_MANAGE, Permission.MEETING_ARCHIVE)
_confirm = require_permissions(Permission.ARCHIVE_CONFIRM)


async def study_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> StudyService:
    """鉴权依赖和服务共用同一请求事务。"""
    return await StudyService(db, user).initialize()


async def respond(
    request: Request,
    service: StudyService,
    data: dict[str, Any],
    action: str,
    resource_type: str = "study",
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


@router.get("/study/org-units", response_model=APIResponse[dict])
async def organizations(
    request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """查询当前人员可访问的学校与院系党委。"""
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


@router.get("/study/materials", response_model=APIResponse[dict])
async def materials(
    request: Request,
    org_unit_id: str = Query(max_length=36),
    q: str = Query(min_length=1, max_length=300),
    on: date | None = None,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """检索有效且适用于目标党委的真实知识材料。"""
    if org_unit_id not in service.org_ids:
        raise HTTPException(403, "无权访问该组织的学习材料")
    sources = await recommend_sources(
        service.db, service.user, org_unit_id, [], on=on or date.today(), query=q
    )
    return await respond(
        request,
        service,
        {
            "sources": sources,
            "missing": [] if sources else ["没有匹配的有效授权资料，政策依据待补"],
            "notice": STUDY_NOTICE,
        },
        "recommend_materials",
    )


@router.get("/study/plans", response_model=APIResponse[dict])
async def plans(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    start: date | None = None,
    end: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """按年度、期间与组织范围分页查询计划。"""
    return await respond(
        request,
        service,
        await service.list_plans(
            year=year, org_unit_id=org_unit_id, start=start, end=end, page=page, page_size=page_size
        ),
        "read_plans",
    )


@router.post("/study/plans", response_model=APIResponse[dict], dependencies=[Depends(_manage)])
async def create_plan(
    body: PlanCreate, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """创建年度学习草案并保留初始依据版本。"""
    plan = await service.create_plan(body)
    return await respond(
        request, service, await service.plan_data(plan), "create", "study_plan", str(plan.id)
    )


@router.get("/study/plans/{plan_id}", response_model=APIResponse[dict])
async def plan_detail(
    plan_id: str, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """查询授权年度重点及每期安排。"""
    plan = await service.plan(plan_id)
    return await respond(
        request, service, await service.plan_data(plan), "read", "study_plan", plan_id
    )


@router.patch(
    "/study/plans/{plan_id}", response_model=APIResponse[dict], dependencies=[Depends(_manage)]
)
async def update_plan(
    plan_id: str, body: PlanUpdate, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """修订年度重点，保留旧版本并撤销旧审核。"""
    plan = await service.update_plan(plan_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "revise", "study_plan", plan_id
    )


@router.post(
    "/study/plans/{plan_id}/items",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def add_item(
    plan_id: str, body: ItemCreate, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """增加学习安排，重新提交年度计划审核。"""
    plan = await service.add_item(plan_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "add_item", "study_plan", plan_id
    )


@router.patch(
    "/study/plans/{plan_id}/items/{item_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def update_item(
    plan_id: str,
    item_id: str,
    body: ItemUpdate,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """修订学习安排与人工议程提纲，保留活动关联。"""
    plan = await service.update_item(plan_id, item_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "revise_item", "study_plan", plan_id
    )


@router.get(
    "/study/plans/{plan_id}/items/{item_id}/recommendations", response_model=APIResponse[dict]
)
async def recommendations(
    plan_id: str,
    item_id: str,
    request: Request,
    q: str | None = Query(None, min_length=1, max_length=300),
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """从授权知识库推荐本期材料，不补写虚构文件。"""
    return await respond(
        request,
        service,
        await service.recommendations(plan_id, item_id, q),
        "recommend_materials",
        "study_plan",
        plan_id,
    )


@router.post(
    "/study/plans/{plan_id}/items/{item_id}/generate-drafts",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def generate_drafts(
    plan_id: str,
    item_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """按独立版本模板生成有真实摘录的议程与发言提纲。"""
    plan = await service.generate_drafts(plan_id, item_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "generate_drafts", "study_plan", plan_id
    )


@router.post(
    "/study/plans/{plan_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def submit_plan(
    plan_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """提交当前计划版本，由另一位组织人员审核。"""
    plan = await service.submit_plan(plan_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "submit", "study_plan", plan_id
    )


@router.post(
    "/study/plans/{plan_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_review)],
)
async def review_plan(
    plan_id: str,
    body: ReviewRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """人工通过或退回已提交的计划版本。"""
    plan = await service.review_plan(plan_id, body)
    return await respond(
        request, service, await service.plan_data(plan), "review", "study_plan", plan_id
    )


@router.get("/study/plans/{plan_id}/revisions", response_model=APIResponse[dict])
async def plan_revisions(
    plan_id: str, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """回看计划修订和人工审核证据，复核历史资料权限。"""
    plan = await service.plan(plan_id)
    return await respond(
        request,
        service,
        {"items": await service.revisions(plan, "study_plan")},
        "read_revisions",
        "study_plan",
        plan_id,
    )


@router.post(
    "/study/plans/{plan_id}/items/{item_id}/activity",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def start_activity(
    plan_id: str,
    item_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """为已审核安排登记稳定且可复用的共用活动记录。"""
    record = await service.start_activity(plan_id, item_id, body)
    return await respond(
        request,
        service,
        await service.activity_data(record),
        "register_activity",
        "meeting",
        str(record.id),
    )


@router.get("/study/activities/{activity_id}", response_model=APIResponse[dict])
async def activity_detail(
    activity_id: str, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """读取当前权限和合规开关允许的活动记录。"""
    record = await service.activity(activity_id)
    return await respond(
        request, service, await service.activity_data(record), "read", "meeting", activity_id
    )


@router.patch(
    "/study/activities/{activity_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def update_activity(
    activity_id: str,
    body: ActivityUpdate,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """登记原始文本与参学情况，修改后重新审核纪要。"""
    record = await service.update_activity(activity_id, body)
    return await respond(
        request, service, await service.activity_data(record), "revise", "meeting", activity_id
    )


@router.post(
    "/study/activities/{activity_id}/generate-minutes",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def generate_minutes(
    activity_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """仅提取原文中明确标注的学习要点、共识和要求。"""
    record = await service.generate_minutes(activity_id, body)
    return await respond(
        request,
        service,
        await service.activity_data(record),
        "generate_minutes",
        "meeting",
        activity_id,
    )


@router.post(
    "/study/activities/{activity_id}/submit",
    response_model=APIResponse[dict],
    dependencies=[Depends(_manage)],
)
async def submit_activity(
    activity_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """核查原文定位、参学、日期及依据后提交纪要。"""
    record = await service.submit_activity(activity_id, body)
    return await respond(
        request, service, await service.activity_data(record), "submit", "meeting", activity_id
    )


@router.post(
    "/study/activities/{activity_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_review)],
)
async def review_activity(
    activity_id: str,
    body: ReviewRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """人工审核当前纪要版本，不允许自审。"""
    record = await service.review_activity(activity_id, body)
    return await respond(
        request, service, await service.activity_data(record), "review", "meeting", activity_id
    )


@router.post(
    "/study/activities/{activity_id}/archive",
    response_model=APIResponse[dict],
    dependencies=[Depends(_archive)],
)
async def archive_activity(
    activity_id: str,
    body: RevisionRequest,
    request: Request,
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """学校确认电子效力后归档人工审核通过的记录。"""
    record = await service.archive_activity(activity_id, body)
    return await respond(
        request, service, await service.activity_data(record), "archive", "meeting", activity_id
    )


@router.get("/study/activities/{activity_id}/revisions", response_model=APIResponse[dict])
async def activity_revisions(
    activity_id: str, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """查询纪要修订与审核历史，屏蔽当前不可访问内容。"""
    record = await service.activity(activity_id)
    return await respond(
        request,
        service,
        {"items": await service.revisions(record, "meeting")},
        "read_revisions",
        "meeting",
        activity_id,
    )


@router.get(
    "/study/activities/{activity_id}/export",
    response_model=APIResponse[dict],
    dependencies=[Depends(_archive)],
)
async def export_activity(
    activity_id: str, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """按当前权限导出归档、材料摘录、计划与确认证据。"""
    return await respond(
        request,
        service,
        await service.export_activity(activity_id),
        "export",
        "meeting",
        activity_id,
    )


@router.get("/study/history", response_model=APIResponse[dict])
async def history(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    topic: str | None = Query(None, max_length=300),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """经合规门禁按年度、主题和党委查询历史归档。"""
    return await respond(
        request,
        service,
        await service.history(
            year=year, org_unit_id=org_unit_id, topic=topic, page=page, page_size=page_size
        ),
        "read_history",
    )


@router.get("/study/metrics", response_model=APIResponse[dict])
async def metrics(
    request: Request,
    year: int = Query(ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    service: StudyService = Depends(study_service),
) -> APIResponse[dict]:
    """只读归集学习次数与比例，所有数字保留稳定来源。"""
    return await respond(request, service, await service.metrics(year, org_unit_id), "read_metrics")


@router.get("/admin/electronic-archive", response_model=APIResponse[dict])
async def read_archive_policy(
    request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """读取当前学校电子归档的确认状态和依据。"""
    policy = await archive_policy(service.db, service.tenant_id)
    return await respond(
        request, service, {"enabled": False, "revision": 0, **policy}, "read_archive_policy"
    )


@router.patch(
    "/admin/electronic-archive", response_model=APIResponse[dict], dependencies=[Depends(_confirm)]
)
async def confirm_archive(
    body: ArchivePolicyUpdate, request: Request, service: StudyService = Depends(study_service)
) -> APIResponse[dict]:
    """由学校授权人员确认或撤销电子记录效力。"""
    if not service.org_ids:
        raise HTTPException(403, "当前学校组织尚未配置，不能确认电子归档")
    policy = await save_archive_policy(service.db, service.user, body)
    return await respond(
        request,
        service,
        policy,
        "confirm_archive" if body.enabled else "revoke_archive",
        "archive_policy",
        service.tenant_id,
    )
