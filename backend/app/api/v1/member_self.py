"""本人档案、私有材料提交及组织人员的账号关联。"""

import hashlib
from datetime import date, datetime
from pathlib import PurePath
from typing import cast
from urllib.parse import quote
from uuid import UUID

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
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.security import Permission
from app.db.session import get_db
from app.deps import require_permissions
from app.models.meeting import ContentRevision
from app.models.member import MemberMaterial, MemberMaterialReceipt, MemberProfile
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.schemas.member import MemberRosterItem
from app.schemas.member_self import (
    AccountLinkRequest,
    MaterialCategory,
    MaterialList,
    MaterialPrevious,
    MaterialReceipt,
    MaterialReviewHistory,
    MaterialReviewItem,
    MaterialReviewRequest,
    MaterialSubmission,
    PersonalArchive,
    PersonalMaterial,
)
from app.services.file_store import read_member_archive
from app.services.material_preview import preview_upload
from app.services.member_review_service import own_reviews as own_review_records
from app.services.org_scope import accessible_org_units
from app.utils.snapshot import record_snapshot as row_data

router = APIRouter()
_self_query = require_permissions(Permission.SELF_QUERY)
_self_submit = require_permissions(Permission.MATERIAL_SUBMIT)
_manage = require_permissions(Permission.STAGE_TRANSITION)
_query = require_permissions(Permission.MEMBER_QUERY)
_review = require_permissions(Permission.MATERIAL_REVIEW)


async def _own_profile(db: AsyncSession, user: User) -> MemberProfile | None:
    # 本人档案按账号直接关联，不要求账号的管理组织等于档案支部；
    # 管理账号可能管理学校/院系，但本人党员档案仍在具体支部。
    profile = (
        await db.execute(
            select(MemberProfile).where(
                MemberProfile.tenant_id == str(user.tenant_id),
                MemberProfile.user_id == str(user.id),
                MemberProfile.is_deleted.is_(False),
                MemberProfile.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        return None
    # 档案所在组织被删除或停用时，档案本身也不再作为有效本人档案展示；
    # 但账号管理组织变化不改变这层关联。
    if profile.org_unit_id:
        organization = (
            await db.execute(
                select(OrgUnit.id).where(
                    OrgUnit.id == profile.org_unit_id,
                    OrgUnit.tenant_id == str(user.tenant_id),
                    OrgUnit.is_deleted.is_(False),
                    OrgUnit.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if organization is None:
            return None
    return profile


async def _managed_profile(
    db: AsyncSession, user: User, profile_id: str, *, lock: bool = False
) -> MemberProfile:
    organizations = await accessible_org_units(db, user)
    statement = select(MemberProfile).where(
        MemberProfile.id == profile_id,
        MemberProfile.tenant_id == str(user.tenant_id),
        MemberProfile.org_unit_id.in_([org.id for org in organizations]),
        MemberProfile.is_deleted.is_(False),
        MemberProfile.is_active.is_(True),
    )
    if lock:
        statement = statement.with_for_update()
    profile = (await db.execute(statement)).scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, "档案不存在或不在授权范围内")
    return profile


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _personal_material(
    record: MemberMaterial, reviewer_name: str | None = None
) -> PersonalMaterial:
    """把 ORM 材料转成出参；审核意见在库内复用 note 列。"""
    data = PersonalMaterial.model_validate(record).model_dump()
    data.update(
        review_status=(
            record.review_status
            if record.review_status in ("pending", "approved", "returned")
            else "pending"
        ),
        review_note=record.note or "",
        reviewer_name=reviewer_name,
    )
    return PersonalMaterial(**data)


async def _reviewer_names(
    db: AsyncSession, records: list[MemberMaterial]
) -> dict[str, str]:
    """批量解析材料审核人姓名；只用于本人和授权组织查看办理记录。"""
    user_ids = {str(record.reviewed_by) for record in records if record.reviewed_by}
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.name).where(
                User.id.in_(user_ids), User.is_deleted.is_(False)
            )
        )
    ).all()
    return {str(row.id): row.name for row in rows}


async def _review_items(
    db: AsyncSession, material: MemberMaterial, names: dict[str, str]
) -> list[MaterialReviewItem]:
    """读取材料的人工审核记录；服务只追加，不覆盖旧记录。"""
    revisions = (
        (
            await db.execute(
                select(ContentRevision)
                .where(
                    ContentRevision.tenant_id == str(material.tenant_id),
                    ContentRevision.resource_type == "member_material",
                    ContentRevision.resource_id == str(material.id),
                    ContentRevision.action == "review",
                    ContentRevision.is_deleted.is_(False),
                )
                .order_by(ContentRevision.revision.asc(), ContentRevision.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    items: list[MaterialReviewItem] = []
    for revision in revisions:
        snapshot = revision.snapshot if isinstance(revision.snapshot, dict) else {}
        decision = snapshot.get("review_status")
        if decision not in ("approved", "returned"):
            decision = "returned" if snapshot.get("note") else "approved"
        items.append(
            MaterialReviewItem(
                id=str(revision.id),
                decision=decision,
                opinion=revision.reason or "",
                reviewer_name=names.get(str(revision.actor_id)) or "审核人待核对",
                created_at=revision.created_at,
            )
        )
    return items


async def _material_history(
    db: AsyncSession, material: MemberMaterial
) -> MaterialReviewHistory:
    """材料当前状态、全部审核记录以及退回前一条材料的记录。"""
    names = await _reviewer_names(db, [material])
    previous: MaterialPrevious | None = None
    if material.previous_material_id:
        prior = (
            await db.execute(
                select(MemberMaterial).where(
                    MemberMaterial.id == material.previous_material_id,
                    MemberMaterial.tenant_id == str(material.tenant_id),
                    MemberMaterial.profile_id == str(material.profile_id),
                    MemberMaterial.user_id == material.user_id,
                    MemberMaterial.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            prior_names = await _reviewer_names(db, [prior])
            previous = MaterialPrevious(
                id=str(prior.id),
                title=prior.title,
                created_at=prior.created_at,
                review_status=(
                    prior.review_status
                    if prior.review_status in ("pending", "approved", "returned")
                    else "pending"
                ),
                review_note=prior.note or "",
                reviewed_at=prior.reviewed_at,
                reviewer_name=(
                    (prior_names.get(str(prior.reviewed_by)) or "审核人待核对")
                    if prior.reviewed_by
                    else None
                ),
                reviews=await _review_items(db, prior, prior_names),
            )
    return MaterialReviewHistory(
        material=_personal_material(
            material,
            (
                (names.get(str(material.reviewed_by)) or "审核人待核对")
                if material.reviewed_by
                else None
            ),
        ),
        reviews=await _review_items(db, material, names),
        previous_material=previous,
    )


@router.get("/member/self/archive", response_model=APIResponse[PersonalArchive], summary="本人档案")
async def own_archive(
    request: Request, user: User = Depends(_self_query), db: AsyncSession = Depends(get_db)
) -> APIResponse[PersonalArchive]:
    """根据登录账号查询唯一关联档案，不接受目标人员编号。"""
    profile = await _own_profile(db, user)
    return APIResponse(
        data=PersonalArchive(
            profile=MemberRosterItem.from_profile(profile) if profile else None,
            max_upload_size=settings.MAX_UPLOAD_SIZE,
        ),
        trace_id=_trace(request),
    )


@router.get(
    "/member/self/reviews",
    response_model=APIResponse[dict],
    summary="本人民主评议结果",
)
async def own_reviews(
    request: Request,
    year: int | None = Query(None, ge=2000, le=2100),
    user: User = Depends(_self_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """只返回本人档案下、已通过审核的评议结果；不接受目标人员编号，也看不到别人的。"""
    profile = await _own_profile(db, user)
    items = await own_review_records(db, user, str(profile.id), year=year) if profile else []
    return APIResponse(
        data={
            "items": items,
            "notice": "评议结果由组织记录、经另一位有权限的人员审核后生效；未生效版本不在此显示",
        },
        trace_id=_trace(request),
    )


@router.put(
    "/member/roster/{profile_id}/account",
    response_model=APIResponse[MemberRosterItem],
    summary="关联党员登录账号",
)
async def link_account(
    profile_id: str,
    body: AccountLinkRequest,
    request: Request,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MemberRosterItem]:
    """由授权组织人员明确关联；已有不同关联时拒绝覆盖。"""
    profile = await _managed_profile(db, user, profile_id, lock=True)
    account = (
        await db.execute(
            select(User).where(
                User.username == body.username,
                User.tenant_id == str(user.tenant_id),
                User.role.in_((UserRole.MEMBER, UserRole.APPLICANT)),
                User.org_unit_id == profile.org_unit_id,
                User.is_deleted.is_(False),
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(422, "请选择同一组织内有效的党员或申请人账号")
    if profile.user_id and profile.user_id != account.id:
        raise HTTPException(409, "此档案已关联其他账号，请先由组织核实")
    profile.user_id = account.id
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "该账号已有本人档案，不能重复关联") from None
    await audit_operation(
        db,
        request,
        user,
        action="link_account",
        resource_type="member",
        resource_id=profile.id,
        data_level="sensitive",
        new_value={"user_id": account.id},
    )
    await db.commit()
    return APIResponse(data=MemberRosterItem.from_profile(profile), trace_id=_trace(request))


async def _materials(
    db: AsyncSession,
    profile: MemberProfile | None,
    user_id: str,
    tenant_id: str,
    page: int,
    page_size: int,
    *,
    viewer_id: str,
) -> MaterialList:
    if profile is None:
        return MaterialList(items=[], total=0, page=page, page_size=page_size)
    conditions = [
        MemberMaterial.tenant_id == tenant_id,
        MemberMaterial.user_id == user_id,
        MemberMaterial.profile_id == profile.id,
        MemberMaterial.is_deleted.is_(False),
    ]
    total = (
        await db.execute(select(func.count(MemberMaterial.id)).where(*conditions))
    ).scalar_one()
    records = (
        (
            await db.execute(
                select(MemberMaterial)
                .where(*conditions)
                .order_by(MemberMaterial.created_at.desc(), MemberMaterial.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    material_ids = [str(record.id) for record in records]
    receipt_rows = (
        (
            await db.execute(
                select(MemberMaterialReceipt).where(
                    MemberMaterialReceipt.tenant_id == tenant_id,
                    MemberMaterialReceipt.material_id.in_(material_ids),
                    MemberMaterialReceipt.is_deleted.is_(False),
                )
            )
        )
        .scalars()
        .all()
        if material_ids
        else []
    )
    receipts: dict[str, list[MemberMaterialReceipt]] = {}
    for receipt in receipt_rows:
        receipts.setdefault(str(receipt.material_id), []).append(receipt)
    reviewer_names = await _reviewer_names(db, list(records))
    items: list[PersonalMaterial] = []
    for record in records:
        record_receipts = receipts.get(str(record.id), [])
        mine = next(
            (receipt for receipt in record_receipts if str(receipt.viewer_id) == viewer_id),
            None,
        )
        latest = max(record_receipts, key=lambda receipt: receipt.viewed_at, default=None)
        item = _personal_material(
            record,
            (
                (reviewer_names.get(str(record.reviewed_by)) or "审核人待核对")
                if record.reviewed_by
                else None
            ),
        )
        item.my_viewed_at = mine.viewed_at if mine else None
        item.last_viewed_at = latest.viewed_at if latest else None
        item.viewer_count = len(record_receipts)
        items.append(item)
    return MaterialList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/member/self/materials", response_model=APIResponse[MaterialList], summary="本人提交材料"
)
async def own_materials(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_self_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialList]:
    """仅列出当前账号在其本人档案下的提交。"""
    return APIResponse(
        data=await _materials(
            db,
            await _own_profile(db, user),
            str(user.id),
            str(user.tenant_id),
            page,
            page_size,
            viewer_id=str(user.id),
        ),
        trace_id=_trace(request),
    )


@router.post(
    "/member/self/materials/preview", response_model=APIResponse[dict], summary="本人材料填写建议"
)
async def preview_own_material(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(_self_submit),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    if await _own_profile(db, user) is None:
        raise HTTPException(409, "账号尚未关联有效本人档案，请联系组织管理员")
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(data=await preview_upload(file), trace_id=_trace(request))


@router.post(
    "/member/self/materials", response_model=APIResponse[PersonalMaterial], summary="提交本人材料"
)
async def submit_material(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    submission_key: UUID = Form(...),
    previous_material_id: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(_self_submit),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PersonalMaterial]:
    """保存本人私有原件，不更改组织核验清单或人员阶段。"""
    profile = await _own_profile(db, user)
    if profile is None:
        raise HTTPException(409, "账号尚未关联有效本人档案，请联系组织管理员")
    profile_id = str(profile.id)
    tenant_id = str(user.tenant_id)
    user_id = str(user.id)
    try:
        # 表单字段是 str，这里只做静态收窄；取值合法性仍由 pydantic 校验并转 422。
        body = MaterialSubmission(
            title=title, category=cast(MaterialCategory, category), description=description
        )
    except ValidationError:
        raise HTTPException(422, "请检查材料标题、类型和说明长度") from None
    name = file.filename or ""
    if not name or len(name) > 255 or any(ord(char) < 32 or char in "/\\:" for char in name):
        raise HTTPException(422, "文件名无效")
    if PurePath(name).suffix.lower() not in {
        ".pdf",
        ".docx",
        ".txt",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
    }:
        raise HTTPException(415, "支持 PDF、DOCX、文本、PNG 和 JPG 文件")
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if not content:
        raise HTTPException(422, "不能提交空文件")
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(413, "文件超过上传大小限制")
    checksum = hashlib.sha256(content).hexdigest()

    async def existing_submission() -> APIResponse[PersonalMaterial] | None:
        existing = (
            await db.execute(
                select(MemberMaterial).where(
                    MemberMaterial.tenant_id == tenant_id,
                    MemberMaterial.user_id == user_id,
                    MemberMaterial.submission_key == str(submission_key),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        if (
            existing.is_deleted
            or existing.profile_id != profile_id
            or existing.content_sha256 != checksum
            or (
                existing.title,
                existing.category,
                existing.description,
                existing.file_name,
                existing.previous_material_id,
            )
            != (
                body.title,
                body.category,
                body.description,
                name,
                previous_material_id,
            )
        ):
            raise HTTPException(409, "该提交编号已用于其他材料，请重新提交")
        return APIResponse(
            data=_personal_material(existing), trace_id=_trace(request)
        )

    existing_response = await existing_submission()
    if existing_response is not None:
        return existing_response
    if previous_material_id:
        prior = (
            await db.execute(
                select(MemberMaterial).where(
                    MemberMaterial.id == previous_material_id,
                    MemberMaterial.tenant_id == tenant_id,
                    MemberMaterial.user_id == user_id,
                    MemberMaterial.profile_id == profile_id,
                    MemberMaterial.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if prior is None or prior.review_status != "returned":
            raise HTTPException(422, "前次材料不存在、尚未退回或不在本人名下")
    record = MemberMaterial(
        tenant_id=tenant_id,
        user_id=user_id,
        profile_id=profile_id,
        org_unit_id=profile.org_unit_id or "",
        stage=profile.current_stage,
        submit_date=date.today(),
        submitter_id=user_id,
        title=body.title,
        category=body.category,
        description=body.description,
        file_name=name,
        file_size=len(content),
        content=content,
        submission_key=str(submission_key),
        content_sha256=checksum,
        previous_material_id=previous_material_id or None,
        review_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        note="",
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        previous = await existing_submission()
        if previous is not None:
            return previous
        raise HTTPException(409, "提交发生冲突，请刷新后重试") from None
    await audit_operation(
        db,
        request,
        user,
        action="submit_material",
        resource_type="member_material",
        resource_id=record.id,
        data_level="sensitive",
        new_value={
            "category": record.category,
            "file_size": record.file_size,
            **(
                {"previous_material_id": record.previous_material_id}
                if record.previous_material_id
                else {}
            ),
        },
    )
    await db.commit()
    return APIResponse(data=_personal_material(record), trace_id=_trace(request))


async def _download(
    db: AsyncSession,
    profile: MemberProfile | None,
    user_id: str,
    tenant_id: str,
    material_id: str,
    request: Request,
    user: User,
) -> Response:
    if profile is None:
        raise HTTPException(404, "材料不存在")
    record = (
        await db.execute(
            select(MemberMaterial)
            .options(undefer(MemberMaterial.content))
            .where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == tenant_id,
                MemberMaterial.user_id == user_id,
                MemberMaterial.profile_id == profile.id,
                MemberMaterial.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "材料不存在")
    # 扫描归档的材料二进制在文件卷里，本人自传的小文件仍在库内 content
    body = record.content
    if body is None and record.file_path:
        body = read_member_archive(record.file_path, record.content_sha256)
    if body is None:
        raise HTTPException(404, "该材料没有原件文件，可能只是台账登记")
    await audit_operation(
        db,
        request,
        user,
        action="download_material",
        resource_type="member_material",
        resource_id=record.id,
        data_level="sensitive",
    )
    await db.commit()
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(record.file_name, safe='')}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/member/self/materials/{material_id}/file", summary="下载本人提交原件")
async def download_own_material(
    material_id: str,
    request: Request,
    user: User = Depends(_self_query),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """根据当前账号校验原件所有者。"""
    return await _download(
        db,
        await _own_profile(db, user),
        str(user.id),
        str(user.tenant_id),
        material_id,
        request,
        user,
    )


@router.get(
    "/member/self/materials/{material_id}/reviews",
    response_model=APIResponse[MaterialReviewHistory],
    summary="本人材料审核记录",
)
async def own_material_reviews(
    material_id: str,
    request: Request,
    user: User = Depends(_self_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialReviewHistory]:
    """本人查看当前材料的审核记录及退回前一条材料的记录。"""
    profile = await _own_profile(db, user)
    if profile is None:
        raise HTTPException(404, "材料不存在")
    material = (
        await db.execute(
            select(MemberMaterial).where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == str(user.tenant_id),
                MemberMaterial.profile_id == str(profile.id),
                MemberMaterial.user_id == str(user.id),
                MemberMaterial.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if material is None:
        raise HTTPException(404, "材料不存在")
    return APIResponse(data=await _material_history(db, material), trace_id=_trace(request))


@router.get(
    "/member/roster/{profile_id}/materials",
    response_model=APIResponse[MaterialList],
    summary="授权档案的提交材料",
)
async def managed_materials(
    profile_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialList]:
    """组织人员仅查询其授权档案下的材料。"""
    profile = await _managed_profile(db, user, profile_id)
    return APIResponse(
        data=await _materials(
            db,
            profile,
            str(profile.user_id),
            str(user.tenant_id),
            page,
            page_size,
            viewer_id=str(user.id),
        ),
        trace_id=_trace(request),
    )


@router.post(
    "/member/roster/{profile_id}/materials/{material_id}/receipt",
    response_model=APIResponse[MaterialReceipt],
    summary="记录个人材料查阅回执",
)
async def record_material_receipt(
    profile_id: str,
    material_id: str,
    request: Request,
    user: User = Depends(_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialReceipt]:
    """记录当前组织账号的查阅时间；只对个人提交材料生效，不改变材料核验状态。"""
    profile = await _managed_profile(db, user, profile_id)
    material = (
        await db.execute(
            select(MemberMaterial).where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == str(user.tenant_id),
                MemberMaterial.profile_id == str(profile.id),
                MemberMaterial.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if material is None:
        raise HTTPException(404, "材料不存在或不在授权范围内")
    # 发展材料由组织登记、走材料核验；查阅回执只针对本人提交的私有材料。
    if not material.user_id or not material.submission_key:
        raise HTTPException(422, "发展材料请在材料核验流程中办理")
    if str(material.user_id) == str(user.id):
        raise HTTPException(403, "本人查阅不计入组织查阅记录")
    receipt = (
        await db.execute(
            select(MemberMaterialReceipt)
            .where(
                MemberMaterialReceipt.tenant_id == str(user.tenant_id),
                MemberMaterialReceipt.material_id == str(material.id),
                MemberMaterialReceipt.viewer_id == str(user.id),
                MemberMaterialReceipt.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if receipt is None:
        receipt = MemberMaterialReceipt(
            tenant_id=str(user.tenant_id),
            material_id=str(material.id),
            viewer_id=str(user.id),
            viewed_at=now,
            view_count=1,
        )
        db.add(receipt)
        count = 1
    else:
        receipt.viewed_at = now
        receipt.view_count += 1
        count = receipt.view_count
    await db.flush()
    await audit_operation(
        db,
        request,
        user,
        action="view_member_material",
        resource_type="member_material",
        resource_id=str(material.id),
        data_level="internal",
        new_value={"view_count": count},
    )
    await db.commit()
    return APIResponse(
        data=MaterialReceipt(
            material_id=str(material.id), viewed_at=now, view_count=count
        ),
        trace_id=_trace(request),
    )


@router.get(
    "/member/roster/{profile_id}/materials/{material_id}/reviews",
    response_model=APIResponse[MaterialReviewHistory],
    summary="授权档案材料审核记录",
)
async def managed_material_reviews(
    profile_id: str,
    material_id: str,
    request: Request,
    user: User = Depends(_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialReviewHistory]:
    """组织人员查看授权档案材料的审核记录。"""
    profile = await _managed_profile(db, user, profile_id)
    material = (
        await db.execute(
            select(MemberMaterial).where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == str(user.tenant_id),
                MemberMaterial.profile_id == str(profile.id),
                MemberMaterial.user_id == profile.user_id,
                MemberMaterial.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if material is None:
        raise HTTPException(404, "材料不存在或不在授权范围内")
    if not material.user_id or not material.submission_key:
        raise HTTPException(422, "发展材料请在材料核验流程中办理")
    return APIResponse(data=await _material_history(db, material), trace_id=_trace(request))


@router.post(
    "/member/roster/{profile_id}/materials/{material_id}/review",
    response_model=APIResponse[MaterialReviewHistory],
    summary="支部书记审核个人材料",
)
async def review_personal_material(
    profile_id: str,
    material_id: str,
    body: MaterialReviewRequest,
    request: Request,
    user: User = Depends(_review),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MaterialReviewHistory]:
    """支部书记对本人提交材料作出通过或退回决定；不改发展阶段或发展材料核验。"""
    profile = await _managed_profile(db, user, profile_id)
    material = (
        await db.execute(
            select(MemberMaterial)
            .where(
                MemberMaterial.id == material_id,
                MemberMaterial.tenant_id == str(user.tenant_id),
                MemberMaterial.profile_id == str(profile.id),
                MemberMaterial.user_id == profile.user_id,
                MemberMaterial.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if material is None:
        raise HTTPException(404, "材料不存在或不在授权范围内")
    if not material.user_id or not material.submission_key:
        raise HTTPException(422, "发展材料请在材料核验流程中办理")
    if not material.file_name:
        raise HTTPException(422, "材料没有可核对的原件，不能审核")
    if str(material.user_id) == str(user.id):
        raise HTTPException(403, "不能审核本人提交的材料")
    if material.review_status == "approved":
        raise HTTPException(409, "该材料已审核通过，不能重复审核")
    if material.review_status == "returned":
        raise HTTPException(409, "该材料已退回，等待本人修改重交后再审核")
    opinion = body.opinion.strip()
    if body.decision == "returned" and len(opinion) < 2:
        raise HTTPException(422, "退回时必须填写退回原因")
    now = datetime.utcnow()
    material.review_status = body.decision
    material.note = opinion
    material.reviewed_by = str(user.id)
    material.reviewed_at = now
    latest = (
        await db.execute(
            select(func.max(ContentRevision.revision)).where(
                ContentRevision.tenant_id == str(user.tenant_id),
                ContentRevision.resource_type == "member_material",
                ContentRevision.resource_id == str(material.id),
            )
        )
    ).scalar() or 0
    db.add(
        ContentRevision(
            tenant_id=str(user.tenant_id),
            resource_type="member_material",
            resource_id=str(material.id),
            revision=latest + 1,
            action="review",
            actor_id=str(user.id),
            reason=opinion or ("审核通过" if body.decision == "approved" else "退回补充"),
            snapshot=row_data(material),
            created_at=now,
        )
    )
    await db.flush()
    history = await _material_history(db, material)
    await audit_operation(
        db,
        request,
        user,
        action="review_member_material",
        resource_type="member_material",
        resource_id=str(material.id),
        data_level="sensitive",
        new_value={"decision": body.decision, "opinion": opinion},
    )
    await db.commit()
    return APIResponse(data=history, trace_id=_trace(request))


@router.get(
    "/member/roster/{profile_id}/materials/{material_id}/file", summary="下载授权档案提交材料"
)
async def download_managed_material(
    profile_id: str,
    material_id: str,
    request: Request,
    user: User = Depends(_query),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """组织和材料所有者校验后提供私有原件。"""
    profile = await _managed_profile(db, user, profile_id)
    return await _download(
        db, profile, str(profile.user_id), str(user.tenant_id), material_id, request, user
    )
