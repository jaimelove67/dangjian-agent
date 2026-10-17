"""党员发展接口（资格校验 / 流转建议 / 待办建议）

- ``POST /member/qualification-check``：资格校验（材料 + 时限）；
- ``POST /member/transition-suggestion``：流转建议（**不写入阶段字段**）；
- ``POST /member/todo-suggestions``：待办建议（预留接口）。
- ``GET /member/roster``：按组织范围分页查询真实台账；
- ``POST /member/roster``：组织人员人工登记台账。

权限：支部书记及以上（``member.query``）。阶段流转为人工操作，接口只给建议。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

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
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.chains.member_flow import MemberFlow
from app.core.config import settings, tenant_config
from app.core.constants import XLSX_MEDIA_TYPE
from app.core.security import BS_ALL, Permission, get_role_profile
from app.db.session import get_db
from app.deps import require_permissions
from app.models.member import MemberProfile
from app.models.user import User
from app.rules.member_stages import STAGE_LABELS, MemberStage
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.member import (
    DECISION_BOUNDARY_NOTE,
    MemberCreateRequest,
    MemberOrgOption,
    MemberRosterItem,
    MemberRosterResponse,
    QualificationCheckRequest,
    QualificationResult,
    RosterImportReport,
    RosterImportRow,
    TodoItem,
    TodoSuggestionsRequest,
    TodoSuggestionsResponse,
    TransitionSuggestion,
    TransitionSuggestionRequest,
)
from app.services.org_scope import accessible_org_units
from app.services.roster_io import (
    MAX_EXPORT_ROWS,
    RosterFormatError,
    build_roster,
    build_template,
    read_roster,
)

router = APIRouter()

# 规则加载一次（可配置）
_flow = MemberFlow()
_require_member = require_permissions(Permission.MEMBER_QUERY)
_require_member_manage = require_permissions(Permission.STAGE_TRANSITION)


def _flow_for(user: User) -> MemberFlow:
    """租户配置作用于进度提醒；资格最短时限仍由业务规则控制。"""
    tenant_id = str(user.tenant_id)
    return MemberFlow(
        _flow.rules,
        reminder_limits={
            MemberStage.ACTIVIST: tenant_config.get(tenant_id, "activist_training_days"),
            MemberStage.PROBATIONARY: tenant_config.get(tenant_id, "probationary_period_days"),
        },
    )


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _invalid_stage(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": ErrorCode.BUSINESS_ERROR, "message": f"非法阶段: {exc}"},
    )


@router.get(
    "/member/org-units",
    response_model=APIResponse[list[MemberOrgOption]],
    summary="可登记培养对象的组织",
    tags=["党员发展"],
)
async def member_org_units(
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[MemberOrgOption]]:
    organizations = await accessible_org_units(db, user)
    return APIResponse(
        data=[
            MemberOrgOption(id=str(org.id), name=org.name, org_type=org.org_type)
            for org in organizations
        ],
        trace_id=_trace_id(request),
    )


async def _roster_conditions(
    db: AsyncSession,
    user: User,
    *,
    year: int | None,
    batch_no: str | None,
    include_transferred: bool = False,
    org_unit_id: str | None = None,
) -> list[Any]:
    """名册筛选条件：租户 + 有效台账 + 年度/批次/组织 + 组织权限范围（列表与导出共用）。

    默认不列组织关系已转出的人员（T-MEM-14）：他们已经不属于本组织在册党员，
    但台账与接转记录仍在——需要查历史时显式勾选"含已转出"。

    组织筛选（T-MEM-02）只接受**权限范围内**的组织：院系 / 学校管理员能看到多个支部时，
    名册要能只按某一个支部看。传了范围外的组织一律 403，不静默忽略——"筛不筛都一样"
    会让用户以为已经筛过（假筛选比没有筛选更糟）。
    """
    conditions: list[Any] = [
        MemberProfile.tenant_id == str(user.tenant_id),
        MemberProfile.is_deleted.is_(False),
        MemberProfile.is_active.is_(True),
    ]
    if year is not None:
        conditions.append(MemberProfile.year == year)
    if batch_no is not None:
        conditions.append(MemberProfile.batch_no == batch_no)
    if not include_transferred:
        conditions.append(MemberProfile.relation_status != "transferred_out")
    if org_unit_id or get_role_profile(user.role).business_scope != BS_ALL:
        allowed = [str(org.id) for org in await accessible_org_units(db, user)]
        if org_unit_id:
            if org_unit_id not in allowed:
                raise HTTPException(403, "该组织不在你的权限范围内，不能按它筛选名册")
            conditions.append(MemberProfile.org_unit_id == org_unit_id)
        else:
            conditions.append(MemberProfile.org_unit_id.in_(allowed))
    return conditions


@router.get(
    "/member/roster",
    response_model=APIResponse[MemberRosterResponse],
    summary="培养对象名册",
    tags=["党员发展"],
)
async def member_roster(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    year: int | None = Query(None, ge=2000, le=2100),
    batch_no: str | None = Query(None, min_length=1, max_length=20),
    org_unit_id: str | None = Query(
        None, max_length=36, description="按单个组织（支部）筛选；须在权限范围内，否则 403"
    ),
    include_transferred: bool = Query(
        False, description="是否包含组织关系已转出的人员（默认不含）"
    ),
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterResponse]:
    conditions = await _roster_conditions(
        db,
        user,
        year=year,
        batch_no=batch_no,
        include_transferred=include_transferred,
        org_unit_id=org_unit_id,
    )
    total = (await db.execute(select(func.count(MemberProfile.id)).where(*conditions))).scalar_one()
    statement = (
        select(MemberProfile)
        .where(*conditions)
        .order_by(MemberProfile.created_at.desc(), MemberProfile.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    profiles = (await db.execute(statement)).scalars().all()
    await audit_operation(
        db,
        request,
        user,
        action="read_roster",
        resource_type="member",
        data_level="sensitive",
        new_value={"total": total, "page": page, "org_unit_id": org_unit_id},
    )
    await db.commit()
    return APIResponse(
        data=MemberRosterResponse(
            items=[MemberRosterItem.from_profile(profile) for profile in profiles],
            total=total,
            page=page,
            page_size=page_size,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/roster",
    response_model=APIResponse[MemberRosterItem],
    summary="登记培养对象",
    tags=["党员发展"],
)
async def create_member(
    body: MemberCreateRequest,
    request: Request,
    user: User = Depends(_require_member_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterItem]:
    org_id = body.org_unit_id or user.org_unit_id
    organizations = await accessible_org_units(db, user)
    organization = next((org for org in organizations if str(org.id) == org_id), None)
    if organization is None:
        raise HTTPException(status_code=403, detail="请选择权限范围内的有效组织")
    profile = MemberProfile(
        tenant_id=str(user.tenant_id),
        name=body.name,
        org_unit_id=str(organization.id),
        org_name=organization.name,
        current_stage=body.current_stage.value,
        stage_joined_on=body.stage_joined_on or date.today(),
        materials=body.materials,
        pending=body.pending,
    )
    db.add(profile)
    await db.flush()
    await audit_operation(
        db,
        request,
        user,
        action="create",
        resource_type="member",
        resource_id=str(profile.id),
        data_level="sensitive",
        new_value={"org_unit_id": profile.org_unit_id, "stage": profile.current_stage},
    )
    await db.commit()
    return APIResponse(data=MemberRosterItem.from_profile(profile), trace_id=_trace_id(request))


@router.get(
    "/member/roster/template",
    response_model=None,
    summary="下载名册导入模板（Excel）",
    description="模板含列说明、可用阶段与当前权限范围内的组织；填好后可原样上传导入。",
    tags=["党员发展"],
)
async def member_roster_template(
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> Response:
    organizations = await accessible_org_units(db, user)
    content = build_template([org.name for org in organizations])
    await audit_operation(
        db,
        request,
        user,
        action="read_roster_template",
        resource_type="member",
        data_level="internal",
        new_value={"org_count": len(organizations)},
    )
    await db.commit()
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="roster-template.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/member/roster/export",
    response_model=None,
    summary="导出名册（Excel）",
    description="按当前筛选与组织权限导出，附「导出说明」便于核对；不含原始材料文件。",
    tags=["党员发展"],
)
async def member_roster_export(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    batch_no: str | None = Query(None, min_length=1, max_length=20),
    org_unit_id: str | None = Query(
        None, max_length=36, description="按单个组织（支部）筛选；须在权限范围内，否则 403"
    ),
    include_transferred: bool = Query(
        False, description="是否包含组织关系已转出的人员（默认不含）"
    ),
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conditions = await _roster_conditions(
        db,
        user,
        year=year,
        batch_no=batch_no,
        include_transferred=include_transferred,
        org_unit_id=org_unit_id,
    )
    total = (await db.execute(select(func.count(MemberProfile.id)).where(*conditions))).scalar_one()
    if total > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": (
                    f"当前范围共 {total} 条，超过单次导出上限 {MAX_EXPORT_ROWS} 条："
                    "请按支部、年度或批次分批导出，避免生成打不开的大文件。"
                ),
            },
        )
    profiles = (
        (
            await db.execute(
                select(MemberProfile)
                .where(*conditions)
                .order_by(MemberProfile.org_name, MemberProfile.name, MemberProfile.id)
            )
        )
        .scalars()
        .all()
    )
    scope_note = (
        "全组织范围"
        if get_role_profile(user.role).business_scope == BS_ALL
        else "当前账号权限范围内的组织"
    )
    if org_unit_id:
        org_name = next(
            (
                org.name
                for org in await accessible_org_units(db, user)
                if str(org.id) == org_unit_id
            ),
            org_unit_id,
        )
        scope_note = f"仅限「{org_name}」"
    scope_note += (
        "（含组织关系已转出人员）"
        if include_transferred
        else "（默认不含组织关系已转出人员，如需可勾选含已转出后重新导出）"
    )
    content = build_roster(
        [
            {
                "name": profile.name,
                "org_name": profile.org_name,
                "stage": profile.current_stage,
                "stage_joined_on": (
                    profile.stage_joined_on.isoformat() if profile.stage_joined_on else ""
                ),
                "year": profile.year,
                "batch_no": profile.batch_no,
                "pending": profile.pending or 0,
            }
            for profile in profiles
        ],
        scope_note=scope_note,
    )
    await audit_operation(
        db,
        request,
        user,
        action="export_roster",
        resource_type="member",
        data_level="sensitive",
        new_value={
            "count": total,
            "year": year,
            "batch_no": batch_no,
            "org_unit_id": org_unit_id,
            "scope": scope_note,
        },
    )
    await db.commit()
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="roster-export.xlsx"',
            "Cache-Control": "no-store",
        },
    )


def _stage_label(value: str) -> str:
    """阶段显示名；台账里出现历史脏值时原样显示，不在这里改名。"""
    try:
        return STAGE_LABELS.get(MemberStage(value), value)
    except ValueError:
        return value


@router.post(
    "/member/roster/import",
    response_model=APIResponse[RosterImportReport],
    summary="按模板批量导入名册（Excel）",
    description=(
        "先以 dry_run=true 预检并逐行报告，确认后再以 dry_run=false 落库。"
        "导入只登记台账，不改动已有人员的当前阶段。"
    ),
    tags=["党员发展"],
)
async def member_roster_import(
    request: Request,
    file: UploadFile = File(..., description="按模板填写的 .xlsx"),
    source_note: str = Form(..., description="名册来源说明，例如：12371 导出 2026-10-16"),
    dry_run: bool = Form(True, description="true 只预检不落库"),
    user: User = Depends(_require_member_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[RosterImportReport]:
    note = source_note.strip()
    if not 4 <= len(note) <= 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": "请填写 4–200 字的名册来源说明（例如：12371 导出 2026-10-16）。"
                "说明会随本次导入写入审计记录（含操作人与文件摘要），用于事后核对名册来路",
            },
        )
    organizations = await accessible_org_units(db, user)
    if not organizations:
        raise HTTPException(
            status_code=403,
            detail="当前账号没有可登记的组织，请联系管理员绑定组织后再导入名册",
        )

    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB）",
            },
        )
    if not content:
        raise HTTPException(status_code=422, detail="文件为空，请选择填好的名册模板")
    try:
        sheet = read_roster(content)
    except RosterFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": str(exc)},
        ) from exc
    if sheet.data_rows == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": "表格里没有数据行：请在模板「名册」工作表从第 2 行开始填写后再导入。",
            },
        )

    by_id = {str(org.id): org for org in organizations}
    by_name: dict[str, list[Any]] = {}
    for org in organizations:
        by_name.setdefault(org.name.strip(), []).append(org)

    def resolve(ref: str) -> tuple[Any, str]:
        exact = by_id.get(ref)
        if exact is not None:
            return exact, ""
        matches = by_name.get(ref, [])
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, f"组织名称「{ref}」在你的范围内对应多个组织，请改填组织编号"
        return (
            None,
            f"组织「{ref}」不在你的权限范围内；模板「填写说明」里列出了可用的组织名称与编号",
        )

    ledger = {
        (str(profile.org_unit_id), profile.name): profile
        for profile in (
            (
                await db.execute(
                    select(MemberProfile).where(
                        MemberProfile.tenant_id == str(user.tenant_id),
                        MemberProfile.is_deleted.is_(False),
                        MemberProfile.is_active.is_(True),
                        MemberProfile.org_unit_id.in_(list(by_id)),
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    report_rows: list[RosterImportRow] = []
    seen: dict[tuple[str, str], int] = {}
    created = skipped = failed = 0
    pending_rows: list[tuple[Any, Any]] = []
    for row in sheet.rows:
        if row.error:
            failed += 1
            report_rows.append(
                RosterImportRow(row=row.row_no, name=row.name, status="error", message=row.error)
            )
            continue
        organization, org_error = resolve(row.org_ref)
        if organization is None:
            failed += 1
            report_rows.append(
                RosterImportRow(row=row.row_no, name=row.name, status="error", message=org_error)
            )
            continue
        key = (str(organization.id), row.name)
        if key in seen:
            failed += 1
            report_rows.append(
                RosterImportRow(
                    row=row.row_no,
                    name=row.name,
                    status="error",
                    message=f"与第 {seen[key]} 行的姓名与组织重复，请只保留一行",
                )
            )
            continue
        seen[key] = row.row_no
        current = ledger.get(key)
        if current is not None:
            skipped += 1
            message = "台账中已有同名同组织的记录，本次未改动"
            if current.current_stage != row.stage:
                message += (
                    f"；表中阶段「{_stage_label(row.stage)}」与台账"
                    f"「{_stage_label(current.current_stage)}」不一致，"
                    "阶段变更须走人工流转（含材料与时限校验），导入不代替这一步"
                )
            report_rows.append(
                RosterImportRow(row=row.row_no, name=row.name, status="skipped", message=message)
            )
            continue
        created += 1
        report_rows.append(RosterImportRow(row=row.row_no, name=row.name, status="created"))
        pending_rows.append((row, organization))

    if not dry_run:
        for row, organization in pending_rows:
            db.add(
                MemberProfile(
                    tenant_id=str(user.tenant_id),
                    name=row.name,
                    org_unit_id=str(organization.id),
                    org_name=organization.name,
                    current_stage=row.stage,
                    stage_joined_on=row.stage_joined_on or date.today(),
                    materials=[],
                    pending=row.pending,
                    year=row.year,
                    batch_no=row.batch_no,
                )
            )
        await db.flush()

    await audit_operation(
        db,
        request,
        user,
        action="import_roster",
        resource_type="member",
        data_level="sensitive",
        new_value={
            "dry_run": dry_run,
            "source_note": note,
            "total_rows": sheet.data_rows,
            "created": created,
            "skipped": skipped,
            "failed": failed,
        },
    )
    await db.commit()
    return APIResponse(
        data=RosterImportReport(
            dry_run=dry_run,
            source_note=note,
            total_rows=sheet.data_rows,
            created=created,
            skipped=skipped,
            failed=failed,
            rows=report_rows,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/qualification-check",
    response_model=APIResponse[QualificationResult],
    summary="资格校验",
    description="核对材料齐全性与阶段时限，输出阻断项（不修改任何阶段）。",
    tags=["党员发展"],
)
async def qualification_check(
    body: QualificationCheckRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QualificationResult]:
    try:
        outcome = _flow.check_qualification(
            current_stage=body.current_stage,
            target_stage=body.target_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="qualification_check",
        resource_type="member",
        new_value={
            "current_stage": body.current_stage,
            "target_stage": body.target_stage,
            "eligible": outcome.eligible,
            "blocker_count": len(outcome.blockers),
        },
    )
    await db.commit()
    return APIResponse(
        data=QualificationResult(
            eligible=outcome.eligible,
            blockers=outcome.blockers,
            missing_materials=outcome.missing_materials,
            present_materials=outcome.present_materials,
            min_days=outcome.min_days,
            days_in_stage=outcome.days_in_stage,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/transition-suggestion",
    response_model=APIResponse[TransitionSuggestion],
    summary="流转建议",
    description="给出拟转入阶段与应履行程序；阶段流转仍须人工接口完成。",
    tags=["党员发展"],
)
async def transition_suggestion(
    body: TransitionSuggestionRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TransitionSuggestion]:
    try:
        outcome = _flow.suggest_transition(
            current_stage=body.current_stage,
            target_stage=body.target_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="transition_suggestion",
        resource_type="member",
        new_value={
            "current_stage": body.current_stage,
            "target_stage": body.target_stage,
            "eligible": outcome.eligible,
        },
    )
    await db.commit()
    return APIResponse(
        data=TransitionSuggestion(
            current_stage=outcome.current_stage,
            suggested_target=outcome.suggested_target,
            eligible=outcome.eligible,
            procedures=outcome.procedures,
            blockers=outcome.blockers,
            note=DECISION_BOUNDARY_NOTE,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/member/todo-suggestions",
    response_model=APIResponse[TodoSuggestionsResponse],
    summary="待办建议（预留）",
    description="生成待补材料/建议安排会议等待办建议，供前端展示与后续调度接入。",
    tags=["党员发展"],
)
async def todo_suggestions(
    body: TodoSuggestionsRequest,
    request: Request,
    user: User = Depends(_require_member),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TodoSuggestionsResponse]:
    try:
        todos = _flow_for(user).generate_todos(
            current_stage=body.current_stage,
            materials=body.materials,
            days_in_stage=body.days_in_stage,
        )
    except ValueError as exc:
        raise _invalid_stage(exc) from exc

    await audit_operation(
        db,
        request,
        user,
        action="todo_suggestions",
        resource_type="member",
        new_value={"current_stage": body.current_stage, "todo_count": len(todos)},
    )
    await db.commit()
    return APIResponse(
        data=TodoSuggestionsResponse(
            todos=[TodoItem(category=category, content=content) for category, content in todos],
            note=DECISION_BOUNDARY_NOTE,
        ),
        trace_id=_trace_id(request),
    )
