"""发展党员全流程 API：批次、档案、材料记录、人工流转、提醒、培养、投票、评分与档案检查。

权限：查询 ``member.query``；登记、流转、材料审核与档案检查 ``member.stage_transition``；
评分 ``member.scoring``。所有建议与评分均不自动形成组织认定。
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.desensitization import mask_id_card
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.user import User
from app.schemas.common import APIResponse
from app.schemas.member_ext import (
    ArchiveCheckRun,
    BatchCreate,
    CultivationCreate,
    MaterialCreate,
    MaterialReview,
    PoliticalReviewCreate,
    ProcedureCreate,
    ProfileUpdate,
    ReminderResolve,
    ScoringRequest,
    TrainingCreate,
    TransitionRequest,
    VoteBatch,
)
from app.services.material_preview import preview_upload
from app.services.member_archive_service import scan_supported
from app.services.member_service import DECISION_BOUNDARY, MemberDevelopment, row_data

router = APIRouter()
_query = require_permissions(Permission.MEMBER_QUERY)
_transition = require_permissions(Permission.STAGE_TRANSITION)
_scoring = require_permissions(Permission.SCORING)


async def member_service(
    db: AsyncSession = Depends(get_db), user: User = Depends(_query)
) -> MemberDevelopment:
    return await MemberDevelopment(db, user).initialize()


def profile_payload(profile: Any) -> dict[str, Any]:
    """档案对外快照：身份证号只出脱敏值，完整号不出网，也不落审计。

    身份证号是登录账号来源，属于高敏字段；查看者要核对号码应走身份核验，
    而不是让完整号在浏览器和审计日志里各留一份。
    """
    data = row_data(profile)
    raw = data.pop("id_card_no", None)
    data["id_card_masked"] = mask_id_card(raw) if raw else None
    return data


async def respond(
    request: Request,
    service: MemberDevelopment,
    data: dict[str, Any],
    action: str,
    resource_type: str = "member",
    resource_id: str | None = None,
) -> APIResponse[dict]:
    await audit_operation(
        service.db,
        request,
        service.user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_level="sensitive",
        new_value={
            key: data[key]
            for key in ("total", "year", "stage", "batch_no", "org_unit_id")
            if key in data
        },
    )
    await service.db.commit()
    return APIResponse(data=data, trace_id=getattr(request.state, "trace_id", None))


def bind(body: Any, **extra: Any) -> dict[str, Any]:
    return {**body.model_dump(), **extra}


@router.get("/member-full/stats", response_model=APIResponse[dict])
async def roster_stats(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    batch_no: str | None = Query(None, max_length=20),
    org_unit_id: str | None = Query(
        None, max_length=36, description="按单个组织（支部）筛选；须在权限范围内，否则 403"
    ),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.roster_stats(year=year, batch_no=batch_no, org_unit_id=org_unit_id),
        "read_roster_stats",
    )


@router.get("/member-full/batches", response_model=APIResponse[dict])
async def batches(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    org_unit_id: str | None = Query(None, max_length=36),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.list_batches(
            year=year, org_unit_id=org_unit_id, page=page, page_size=page_size
        ),
        "read_batches",
        "member_batch",
    )


@router.post(
    "/member-full/batches", response_model=APIResponse[dict], dependencies=[Depends(_transition)]
)
async def create_batch(
    body: BatchCreate, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    batch = await service.create_batch(body)
    return await respond(
        request,
        service,
        row_data(batch),
        "create",
        "member_batch",
        str(batch.id),
    )


@router.get("/member-full/profiles/{profile_id}", response_model=APIResponse[dict])
async def profile_detail(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    profile = await service.profile(profile_id)
    data = profile_payload(profile)
    data["materials"] = await service.list_materials(profile_id)
    data["stage_history"] = await service.stage_history(profile_id)
    data["cultivation"] = await service.cultivation(profile_id)
    data["political_reviews"] = await service.political_reviews(profile_id)
    data["trainings"] = await service.trainings(profile_id)
    data["procedures"] = await service.procedures(profile_id)
    data["boundary"] = DECISION_BOUNDARY
    return await respond(request, service, data, "read", "member", profile_id)


@router.patch(
    "/member-full/profiles/{profile_id}",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    profile = await service.update_profile(profile_id, body)
    return await respond(request, service, profile_payload(profile), "revise", "member", profile_id)


@router.post(
    "/member-full/profiles/{profile_id}/transition",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def transition(
    profile_id: str,
    body: TransitionRequest,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    profile = await service.transition(profile_id, body)
    data = profile_payload(profile)
    data["stage_history"] = await service.stage_history(profile_id)
    data["boundary"] = DECISION_BOUNDARY
    return await respond(request, service, data, "transition", "member", profile_id)


@router.get("/member-full/profiles/{profile_id}/materials", response_model=APIResponse[dict])
async def materials(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        {"items": await service.list_materials(profile_id)},
        "read_materials",
        "member",
        profile_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/materials",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def add_material(
    profile_id: str,
    body: MaterialCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    material = await service.add_material(profile_id, body)
    return await respond(
        request,
        service,
        service.material_view(material),
        "create_material",
        "member_material",
        str(material.id),
    )


@router.post(
    "/member-full/profiles/{profile_id}/materials/preview",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def preview_development_material(
    profile_id: str,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    await service.profile(profile_id)
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(
        data=await preview_upload(file), trace_id=getattr(request.state, "trace_id", None)
    )


@router.post(
    "/member-full/profiles/{profile_id}/materials/scan",
    response_model=APIResponse[dict],
    summary="扫描件归档（组织干事代扫）",
    description=(
        "把纸质档案扫描件归到该人员档案下：影像件加密存入文件卷，可选云端识别出文字。"
        "归档只登记「组织已收到这份材料」，材料状态为待核验，是否通过仍须人工审核。"
    ),
    tags=["党员发展"],
    dependencies=[Depends(_transition)],
)
async def archive_scan(
    profile_id: str,
    request: Request,
    file: UploadFile = File(..., description="材料原件：PDF / DOCX / TXT / MD / PNG / JPG"),
    material_type: str = Form(..., description="卷内目录中的材料类型"),
    reason: str = Form(..., description="归档说明（4–200 字），写入审计"),
    note: str = Form("", description="备注，随材料保存"),
    file_version: str = Form("扫描归档", min_length=1, max_length=50),
    document_date: date | None = Form(None, description="材料落款日期；入党申请书必填"),
    submit_date: date | None = Form(None),
    cloud_ocr: bool = Form(False, description="是否允许云端识别；材料会出网，敏感级材料一律不识别"),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    await service.profile(profile_id)
    name = file.filename or ""
    if not name or len(name) > 255 or any(ord(char) < 32 or char in "/\\:" for char in name):
        raise HTTPException(422, "文件名无效")
    if not scan_supported(name):
        raise HTTPException(415, "材料支持 PDF、DOCX、TXT、MD、PNG、JPG")
    if not file_version.strip():
        raise HTTPException(422, "请填写材料版本")
    kind = material_type.strip()
    if not kind or len(kind) > 100:
        raise HTTPException(422, "请选择或填写材料类型（不超过 100 字）")
    why = reason.strip()
    if not 4 <= len(why) <= 200:
        raise HTTPException(422, "请填写 4–200 字的归档说明，会写入审计记录")
    if len(note.strip()) > 500:
        raise HTTPException(422, "备注不能超过 500 字")
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if not content:
        raise HTTPException(422, "扫描件是空文件，请重新导出")
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            413, f"扫描件超过 {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB，请降分辨率或拆分后重传"
        )

    material, notes = await service.attach_scan(
        profile_id,
        file_name=name,
        content=content,
        material_type=kind,
        note=note.strip(),
        cloud_ocr=cloud_ocr,
        file_version=file_version.strip(),
        document_date=document_date,
        submit_date=submit_date,
    )
    data = service.material_view(material)
    data["scan_notes"] = notes
    return await respond(
        request, service, data, "archive_scan", "member_material", str(material.id)
    )


@router.get("/member-full/materials/{material_id}/file", summary="下载授权发展材料原件")
async def material_original(
    material_id: str,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> Response:
    record, content = await service.material_original(material_id)
    await audit_operation(
        service.db,
        request,
        service.user,
        action="download_material",
        resource_type="member_material",
        resource_id=material_id,
        data_level=record.data_level or "sensitive",
    )
    await service.db.commit()
    encoded_name = quote(record.file_name, safe="")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/member-full/materials/{material_id}/text",
    response_model=APIResponse[dict],
    summary="查看扫描件的识别文本",
    description="识别文本只作核对辅助：身份证号、手机号已脱敏，结论仍以影像原件为准。",
    tags=["党员发展"],
)
async def material_text(
    material_id: str,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    data = await service.material_text(material_id)
    return await respond(
        request, service, data, "read_material_text", "member_material", material_id
    )


@router.post(
    "/member-full/materials/{material_id}/review",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def review_material(
    material_id: str,
    body: MaterialReview,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    material = await service.review_material(material_id, body)
    return await respond(
        request,
        service,
        service.material_view(material),
        "review_material",
        "member_material",
        material_id,
    )


@router.get(
    "/member-full/profiles/{profile_id}/political-reviews",
    response_model=APIResponse[dict],
    summary="查看政治审查结论",
    description="返回组织已登记的政审结论与历史；原始政审材料仍按涉密级单独管理。",
    tags=["党员发展"],
)
async def political_reviews(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.political_reviews(profile_id),
        "read_political_reviews",
        "member_political_review",
        profile_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/political-reviews",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
    summary="登记政治审查结论",
    description="登记组织形成的政审结论；只增不改，最新一条为当前结论，不替代组织审查。",
    tags=["党员发展"],
)
async def add_political_review(
    profile_id: str,
    body: PoliticalReviewCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    record = await service.add_political_review(profile_id, body)
    return await respond(
        request,
        service,
        row_data(record),
        "create_political_review",
        "member_political_review",
        str(record.id),
    )


@router.get(
    "/member-full/profiles/{profile_id}/trainings",
    response_model=APIResponse[dict],
    summary="查看集中培训记录",
    description="返回已登记的集中培训事实与是否达到 3 天 / 24 学时要求。",
    tags=["党员发展"],
)
async def trainings(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.trainings(profile_id),
        "read_trainings",
        "member_training",
        profile_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/trainings",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
    summary="登记集中培训",
    description="登记实际参加的天数 / 学时；是否计入发展程序仍须人工核验培训证明原件。",
    tags=["党员发展"],
)
async def add_training(
    profile_id: str,
    body: TrainingCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    record = await service.add_training(profile_id, body)
    return await respond(
        request,
        service,
        row_data(record),
        "create_training",
        "member_training",
        str(record.id),
    )


@router.get(
    "/member-full/profiles/{profile_id}/procedures",
    response_model=APIResponse[dict],
    summary="查看发展程序记录",
    description=(
        "返回培养联系人、入党介绍人、支委会审查、上级党委预审、入党志愿书和上级谈话"
        "的当前状态与历史；只登记事实，不替代组织程序。"
    ),
    tags=["党员发展"],
)
async def procedures(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.procedures(profile_id),
        "read_procedures",
        "member_procedure",
        profile_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/procedures",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
    summary="登记发展程序事实",
    description=(
        "登记培养联系人、入党介绍人、支委会审查、上级党委预审、入党志愿书或上级谈话；"
        "只增不改，最新一条为当前状态，不自动推进阶段。"
    ),
    tags=["党员发展"],
)
async def add_procedure(
    profile_id: str,
    body: ProcedureCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    record = await service.add_procedure(profile_id, body)
    return await respond(
        request,
        service,
        row_data(record),
        "create_procedure",
        "member_procedure",
        str(record.id),
    )


@router.get("/member-full/reminders", response_model=APIResponse[dict])
async def reminders(
    request: Request,
    org_unit_id: str | None = Query(None, max_length=36),
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.reminders(
            org_unit_id=org_unit_id, status=status, page=page, page_size=page_size
        ),
        "read_reminders",
        "member_reminder",
    )


@router.post(
    "/member-full/profiles/{profile_id}/sync-reminders",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def sync_reminders(
    profile_id: str, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    """按业务规则生成该对象的提醒；重复执行不重复写入。"""
    profile = await service.profile(profile_id)
    created = await service.sync_reminders(profile)
    return await respond(
        request,
        service,
        {
            "profile_id": profile_id,
            "created": len(created),
            "notice": "提醒按阶段规则生成，重复执行不重复",
        },
        "sync_reminders",
        "member_reminder",
        profile_id,
    )


@router.post("/member-full/reminders/{reminder_id}/resolve", response_model=APIResponse[dict])
async def resolve_reminder(
    reminder_id: str,
    body: ReminderResolve,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    reminder = await service.resolve_reminder(reminder_id, body)
    return await respond(
        request,
        service,
        row_data(reminder),
        "resolve_reminder",
        "member_reminder",
        reminder_id,
    )


@router.post(
    "/member-full/profiles/{profile_id}/cultivation",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def add_cultivation(
    profile_id: str,
    body: CultivationCreate,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    record = await service.add_cultivation(body, profile_id=profile_id)
    return await respond(
        request,
        service,
        row_data(record),
        "create_cultivation",
        "member_cultivation",
        str(record.id),
    )


@router.post(
    "/member-full/votes", response_model=APIResponse[dict], dependencies=[Depends(_scoring)]
)
async def submit_votes(
    body: VoteBatch, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.submit_votes(body),
        "submit_votes",
        "member_vote",
    )


@router.get("/member-full/votes/summary", response_model=APIResponse[dict])
async def vote_summary(
    request: Request,
    batch_no: str = Query(min_length=1, max_length=20),
    round_no: int = Query(ge=1, le=20),
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.vote_summary(batch_no, round_no),
        "read_vote_summary",
        "member_vote",
    )


@router.post(
    "/member-full/scoring", response_model=APIResponse[dict], dependencies=[Depends(_scoring)]
)
async def scoring(
    body: ScoringRequest, request: Request, service: MemberDevelopment = Depends(member_service)
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.scoring(body),
        "scoring",
        "member",
        body.profile_id,
    )


@router.post(
    "/member-full/archive-check",
    response_model=APIResponse[dict],
    dependencies=[Depends(_transition)],
)
async def archive_check(
    body: ArchiveCheckRun,
    request: Request,
    service: MemberDevelopment = Depends(member_service),
) -> APIResponse[dict]:
    return await respond(
        request,
        service,
        await service.archive_check(body),
        "archive_check",
        "member",
        body.profile_id,
    )
