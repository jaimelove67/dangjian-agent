"""本人档案、私有材料提交及组织人员的账号关联。"""

import hashlib
from datetime import date
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
from app.models.member import MemberMaterial, MemberProfile
from app.models.org import OrgUnit
from app.models.user import User, UserRole
from app.schemas.common import APIResponse
from app.schemas.member import MemberRosterItem
from app.schemas.member_self import (
    AccountLinkRequest,
    MaterialCategory,
    MaterialList,
    MaterialSubmission,
    PersonalArchive,
    PersonalMaterial,
)
from app.services.member_review_service import own_reviews as own_review_records
from app.services.org_scope import accessible_org_units

router = APIRouter()
_self_query = require_permissions(Permission.SELF_QUERY)
_self_submit = require_permissions(Permission.MATERIAL_SUBMIT)
_manage = require_permissions(Permission.STAGE_TRANSITION)
_query = require_permissions(Permission.MEMBER_QUERY)


async def _own_profile(db: AsyncSession, user: User) -> MemberProfile | None:
    if not user.org_unit_id:
        return None
    return (
        await db.execute(
            select(MemberProfile)
            .join(OrgUnit, OrgUnit.id == MemberProfile.org_unit_id)
            .where(
                MemberProfile.tenant_id == str(user.tenant_id),
                MemberProfile.user_id == str(user.id),
                MemberProfile.org_unit_id == str(user.org_unit_id),
                MemberProfile.is_deleted.is_(False),
                MemberProfile.is_active.is_(True),
                OrgUnit.tenant_id == str(user.tenant_id),
                OrgUnit.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


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
    return MaterialList(
        items=[PersonalMaterial.model_validate(record) for record in records],
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
            db, await _own_profile(db, user), str(user.id), str(user.tenant_id), page, page_size
        ),
        trace_id=_trace(request),
    )


@router.post(
    "/member/self/materials", response_model=APIResponse[PersonalMaterial], summary="提交本人材料"
)
async def submit_material(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    submission_key: UUID = Form(...),
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
            or (existing.title, existing.category, existing.description, existing.file_name)
            != (body.title, body.category, body.description, name)
        ):
            raise HTTPException(409, "该提交编号已用于其他材料，请重新提交")
        return APIResponse(data=PersonalMaterial.model_validate(existing), trace_id=_trace(request))

    previous = await existing_submission()
    if previous is not None:
        return previous
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
        new_value={"category": record.category, "file_size": record.file_size},
    )
    await db.commit()
    return APIResponse(data=PersonalMaterial.model_validate(record), trace_id=_trace(request))


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
        content=record.content,
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
            db, profile, str(profile.user_id), str(user.tenant_id), page, page_size
        ),
        trace_id=_trace(request),
    )


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
