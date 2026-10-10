"""知识库接口

- ``POST  /api/v1/knowledge-docs``：文档入库（带权限控制，需院系级及以上管理员）；
- ``GET   /api/v1/knowledge-docs/{doc_id}``：查询文档；
- ``PATCH /api/v1/knowledge-docs/{doc_id}/status``：变更文档状态。
- ``DELETE /api/v1/knowledge-docs/{doc_id}``：按管理范围软删除文档及片段。

租户标识从登录态解析，不接受前端传入（框架文档 8.2）。
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Any
from urllib.parse import quote as url_quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.config import settings
from app.core.security import BS_ALL, Permission, get_role_profile, has_permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.user import User, UserRole
from app.rag.exceptions import ParseError, UnsupportedFormatError
from app.rag.privacy import content_level, require_cloud_eligible
from app.rag.retrieval.access import (
    apply_knowledge_access,
    execute_knowledge_query,
    knowledge_filters,
)
from app.rag.retrieval.hybrid import HybridRetriever
from app.rules.document_metadata import MetadataValidationError, validate_document_metadata
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.knowledge import (
    DocumentCreateResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusUpdate,
)
from app.services.file_store import read_original, save_original, validate_identifier
from app.services.knowledge_service import (
    DocumentConflictError,
    DocumentNotFoundError,
    change_document_status,
    create_document,
    delete_document,
    replace_document_content,
)
from app.services.org_scope import accessible_org_units

router = APIRouter()
logger = logging.getLogger(__name__)

# 入库 / 维护需要"院系级及以上管理员"权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)


class KnowledgeSearch(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(10, ge=1, le=50)
    use_reranker: bool = True
    include_expired: bool = False
    data_level: DataLevel | None = None


@router.post("/knowledge/search", response_model=APIResponse[dict], summary="授权范围内检索知识")
async def search_knowledge(
    body: KnowledgeSearch,
    request: Request,
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
):
    level = content_level(body.query, body.data_level)
    require_cloud_eligible(level)
    retriever = HybridRetriever(db, data_level=level, use_reranker=body.use_reranker)
    results = await retriever.retrieve(
        body.query,
        top_k=body.top_k,
        filters=knowledge_filters(user, include_expired=body.include_expired),
    )
    await audit_operation(
        db,
        request,
        user,
        action="query",
        resource_type="knowledge_doc",
        data_level=level.value,
        new_value={"result_count": len(results)},
    )
    await db.commit()
    return APIResponse(
        data={
            "items": [
                {
                    "doc_id": r.doc_id,
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "article": r.article,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in results
            ],
            "warnings": retriever.warnings,
        },
        trace_id=_trace_id(request),
    )


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _split_tags(raw: str) -> list[str]:
    """解析逗号分隔的主题标签（兼容中英文逗号）"""
    normalized = raw.replace("，", ",")
    return [tag.strip() for tag in normalized.split(",") if tag.strip()]


@router.post(
    "/knowledge-docs",
    response_model=APIResponse[DocumentCreateResponse],
    summary="文档入库",
    description="上传文档并携带完整元数据；必填项缺失将拒绝入库。文件大小限制：10MB。",
    tags=["知识库"],
)
async def create_knowledge_document(
    request: Request,
    file: UploadFile = File(..., description="待入库文件"),
    doc_id: str = Form(..., description="文档标识（全局唯一）"),
    file_name: str = Form(...),
    title: str = Form(...),
    issuer: str = Form(...),
    level: str = Form(..., description="central/provincial/school/department"),
    visibility: str = Form(..., description="public/school/department/branch"),
    effective_date: str = Form(..., description="YYYY-MM-DD"),
    tags: str = Form(..., description="主题标签，逗号分隔"),
    security_level: str = Form("public", description="public/internal/sensitive/classified"),
    expiration_date: str | None = Form(None, description="YYYY-MM-DD，空表示长期有效"),
    doc_status: str = Form("effective", alias="status", description="effective/expired/abolished"),
    doc_number: str | None = Form(None),
    summary: str | None = Form(None),
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentCreateResponse]:
    """文档入库"""
    try:
        validate_identifier(doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 文件大小限制
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
        raise HTTPException(status_code=422, detail="不能上传空文件")
    if file_name != file.filename:
        raise HTTPException(status_code=422, detail="文件名必须与上传文件一致")
    if (
        level in ("central", "provincial")
        and visibility == "public"
        and user.role != UserRole.SYSTEM_ADMIN
    ):
        raise HTTPException(status_code=403, detail="共享公共库只能由系统管理员维护")
    if visibility in ("department", "branch") and not user.org_unit_id:
        raise HTTPException(status_code=422, detail="此可见范围需要账号关联组织单元")

    metadata: dict[str, Any] = {
        "doc_id": doc_id,
        "file_name": file_name,
        "title": title,
        "issuer": issuer,
        "doc_number": doc_number,
        "level": level,
        "visibility": visibility,
        "security_level": security_level,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "status": doc_status,
        "tags": _split_tags(tags),
        "summary": summary,
        "org_unit_id": user.org_unit_id,
    }

    try:
        document, chunk_count, page_count = await create_document(
            db,
            metadata=metadata,
            content=content,
            file_name=file_name,
            tenant_id=tenant_id,
        )
    except MetadataValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "errors": exc.errors},
        ) from exc
    except DocumentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.CONFLICT, "message": str(exc)},
        ) from exc
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": str(exc)},
        ) from exc
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": f"文档解析失败: {str(exc)}"},
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="文档编号已被使用，请更换编号") from exc
    except Exception as exc:
        # 捕获其他未预期的错误
        logger.exception("document_creation_failed", extra={"doc_id": doc_id})
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": "文档入库失败，请凭请求 ID 查看服务日志",
            },
        ) from exc

    await audit_operation(
        db,
        request,
        user,
        action="create",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        new_value={"doc_id": document.doc_id, "chunk_count": chunk_count},
    )
    # 留存原始文件与完整性标识；存储不可用时不阻断入库，下载时明确提示。
    try:
        original_version = (document.doc_metadata or {}).get("content_revision", 1)
        stored = save_original(str(tenant_id), doc_id, original_version, content, file_name)
        document.doc_metadata = {**(document.doc_metadata or {}), "original_file": stored}
    except OSError:
        logger.warning("original_file_save_failed", extra={"doc_id": doc_id})
    await db.commit()
    return APIResponse(
        data=DocumentCreateResponse(
            document=DocumentResponse.from_document(document, page_count=page_count),
            chunk_count=chunk_count,
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/knowledge-docs", response_model=APIResponse[DocumentListResponse], summary="知识文档列表"
)
async def list_knowledge_documents(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    q: str = Query("", max_length=200),
    doc_status: str | None = Query(None, alias="status"),
    level: str | None = Query(None),
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentListResponse]:
    filters = knowledge_filters(user, include_expired=True)
    filters["include_future"] = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    stmt = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False)
    if q.strip():
        stmt = stmt.where(
            or_(
                KnowledgeDoc.title.contains(q.strip(), autoescape=True),
                KnowledgeDoc.issuer.contains(q.strip(), autoescape=True),
                KnowledgeDoc.doc_id.contains(q.strip(), autoescape=True),
                KnowledgeDoc.doc_number.contains(q.strip(), autoescape=True),
            )
        )
    if level:
        stmt = stmt.where(KnowledgeDoc.level == level)
    counts_query = stmt.with_only_columns(KnowledgeDoc.status, func.count()).group_by(
        KnowledgeDoc.status
    )
    counts = dict((await execute_knowledge_query(db, counts_query)).all())
    if doc_status:
        stmt = stmt.where(KnowledgeDoc.status == doc_status)
    total = counts.get(doc_status, 0) if doc_status else sum(counts.values())
    documents = (
        (
            await execute_knowledge_query(
                db,
                stmt.order_by(KnowledgeDoc.created_at.desc(), KnowledgeDoc.id)
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        )
        .scalars()
        .all()
    )
    return APIResponse(
        data=DocumentListResponse(
            items=[DocumentResponse.from_document(doc) for doc in documents],
            total=total,
            page=page,
            page_size=page_size,
            counts={"all": sum(counts.values()), **counts},
        ),
        trace_id=_trace_id(request),
    )


async def _readable_document(
    db: AsyncSession, user: User, doc_id: str, *, lock: bool = False
) -> KnowledgeDoc | None:
    filters = knowledge_filters(user, include_expired=True)
    filters["include_future"] = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    stmt = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False).where(
        KnowledgeDoc.doc_id == doc_id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await execute_knowledge_query(db, stmt)).scalar_one_or_none()


@router.put(
    "/knowledge-docs/{doc_id}/content",
    response_model=APIResponse[DocumentCreateResponse],
    summary="更新文件内容",
)
async def replace_knowledge_content(
    doc_id: str,
    request: Request,
    file: UploadFile = File(...),
    expected_revision: int = Form(..., ge=1),
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件大小超过限制")
    if not content or not file.filename or len(file.filename) > 255:
        raise HTTPException(status_code=422, detail="文件为空或文件名无效")
    readable = await _readable_document(db, user, doc_id)
    if readable is None or readable.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        document, count, old_revision = await replace_document_content(
            db,
            doc_id=doc_id,
            tenant_id=tenant_id,
            content=content,
            file_name=file.filename,
            expected_revision=expected_revision,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在") from None
    except DocumentConflictError:
        raise HTTPException(status_code=409, detail="文件已被更新，请刷新后再试") from None
    except UnsupportedFormatError:
        raise HTTPException(status_code=415, detail="不支持的文件格式") from None
    except ParseError:
        raise HTTPException(status_code=422, detail="文档解析失败或不含可解析文本") from None
    except MetadataValidationError:
        raise HTTPException(
            status_code=422, detail="更新内容与原文档分级不符，请按保密要求分类归档"
        ) from None
    await audit_operation(
        db,
        request,
        user,
        action="update_content",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value={"revision": old_revision},
        new_value={"revision": old_revision + 1, "chunk_count": count},
    )
    try:
        stored = save_original(str(tenant_id), doc_id, old_revision + 1, content, file.filename)
        document.doc_metadata = {**(document.doc_metadata or {}), "original_file": stored}
    except OSError:
        logger.warning("original_file_save_failed", extra={"doc_id": doc_id})
    await db.commit()
    return APIResponse(
        data=DocumentCreateResponse(
            document=DocumentResponse.from_document(document), chunk_count=count
        ),
        trace_id=_trace_id(request),
    )


@router.get(
    "/knowledge-docs/{doc_id}",
    response_model=APIResponse[DocumentResponse],
    summary="查询文档",
    tags=["知识库"],
)
async def read_knowledge_document(
    doc_id: str,
    request: Request,
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """查询文档"""
    document = await _readable_document(db, user, doc_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": "文档不存在"},
        )
    return APIResponse(
        data=DocumentResponse.from_document(document),
        trace_id=_trace_id(request),
    )


@router.patch(
    "/knowledge-docs/{doc_id}/status",
    response_model=APIResponse[DocumentResponse],
    summary="变更文档状态",
    description="状态取值：effective / expired / abolished。",
    tags=["知识库"],
)
async def update_knowledge_document_status(
    doc_id: str,
    body: DocumentStatusUpdate,
    request: Request,
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """变更文档状态"""
    original = await _readable_document(db, user, doc_id)
    if original is None or original.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    old_status = original.status
    try:
        document = await change_document_status(
            db,
            doc_id=doc_id,
            new_status=body.status,
            changed_by=user.username,
            reason=getattr(body, "reason", None),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": str(exc)},
        ) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": str(exc)},
        ) from exc

    await audit_operation(
        db,
        request,
        user,
        action="update",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value={"status": old_status},
        new_value={"status": document.status, "reason": body.reason},
    )
    await db.commit()
    return APIResponse(
        data=DocumentResponse.from_document(document),
        trace_id=_trace_id(request),
    )


@router.delete(
    "/knowledge-docs/{doc_id}",
    response_model=APIResponse[DocumentResponse],
    summary="软删除知识文档",
    tags=["知识库"],
)
async def delete_knowledge_document(
    doc_id: str,
    request: Request,
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    original = await _readable_document(db, user, doc_id)
    if original is None or original.tenant_id != str(user.tenant_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    if get_role_profile(user.role).business_scope != BS_ALL:
        organizations = await accessible_org_units(db, user)
        allowed_orgs = {str(org.id) for org in organizations}
        if (original.doc_metadata or {}).get("org_unit_id") not in allowed_orgs:
            raise HTTPException(status_code=404, detail="文档不存在")
    old_status = original.status
    try:
        document = await delete_document(db, doc_id=doc_id, tenant_id=str(user.tenant_id))
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在") from None
    await audit_operation(
        db,
        request,
        user,
        action="delete",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value={"status": old_status},
        new_value={"is_deleted": True, "status": document.status},
    )
    await db.commit()
    return APIResponse(data=DocumentResponse.from_document(document), trace_id=_trace_id(request))


@router.get(
    "/knowledge-docs/{doc_id}/chunks",
    response_model=APIResponse[list[dict]],
    summary="文档原文片段",
)
async def read_document_chunks(
    doc_id: str,
    request: Request,
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[dict]]:
    document = await _readable_document(db, user, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    stmt = select(EmbeddingChunk).join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
    filters = knowledge_filters(user, include_expired=True)
    filters["include_future"] = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    stmt = (
        apply_knowledge_access(stmt, filters)
        .where(KnowledgeDoc.id == document.id)
        .order_by(EmbeddingChunk.sequence)
    )
    chunks = (await execute_knowledge_query(db, stmt)).scalars().all()
    return APIResponse(
        data=[
            {
                "chunk_id": c.chunk_id,
                "sequence": c.sequence,
                "article": c.article,
                "content": c.content,
                "doc_id": document.doc_id,
            }
            for c in chunks
        ],
        trace_id=_trace_id(request),
    )


class DocumentMetadataPatch(BaseModel):
    """授权人员修正元数据；分级与范围变更记录审计。"""

    title: str | None = Field(None, min_length=1, max_length=500)
    issuer: str | None = Field(None, min_length=1, max_length=200)
    doc_number: str | None = Field(None, max_length=100)
    level: str | None = Field(None, pattern="^(central|provincial|school|department)$")
    visibility: str | None = Field(None, pattern="^(public|school|department|branch)$")
    security_level: str | None = Field(None, pattern="^(public|internal|sensitive|classified)$")
    effective_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expiration_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    tags: str | None = Field(None, max_length=500)
    summary: str | None = Field(None, max_length=2000)
    reason: str = Field(..., min_length=1, max_length=2000)


@router.patch(
    "/knowledge-docs/{doc_id}/metadata",
    response_model=APIResponse[DocumentResponse],
    summary="修正文档元数据",
    description="由授权人员修正来源、标签、时效与可见范围；变更记录审计，历史版本不受影响。",
    tags=["知识库"],
)
async def patch_knowledge_document_metadata(
    doc_id: str,
    body: DocumentMetadataPatch,
    request: Request,
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """修正元数据并保留变更审计；不重建片段（检索时实时应用文档级属性）。"""
    document = await _readable_document(db, user, doc_id, lock=True)
    if document is None or str(document.tenant_id) != str(user.tenant_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    if not changes:
        raise HTTPException(status_code=422, detail="没有需要修正的元数据")
    old_value: dict[str, Any] = {
        "title": document.title,
        "issuer": document.issuer,
        "doc_number": document.doc_number,
        "level": document.level,
        "visibility": document.visibility,
        "security_level": document.security_level,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "expiration_date": (
            document.expiration_date.isoformat() if document.expiration_date else None
        ),
        "tags": list(document.tags or []),
        "summary": document.summary,
    }
    new_value = dict(old_value)
    for key, value in changes.items():
        if key in ("effective_date", "expiration_date"):
            new_value[key] = value or None
            continue
        if key == "tags":
            new_value[key] = _split_tags(value) if value else []
            continue
        new_value[key] = value
    try:
        validate_document_metadata(
            {
                "doc_id": document.doc_id,
                "file_name": document.file_name,
                "status": document.status,
                **new_value,
            }
        )
    except MetadataValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    if (
        new_value["level"] in ("central", "provincial")
        and new_value["visibility"] == "public"
        and user.role != UserRole.SYSTEM_ADMIN
    ):
        raise HTTPException(status_code=403, detail="共享公共库只能由系统管理员维护")
    if new_value["visibility"] in ("department", "branch") and not (
        document.doc_metadata or {}
    ).get("org_unit_id"):
        raise HTTPException(status_code=422, detail="此可见范围需要文档关联组织单元")
    # 下载旧版本也使用当前密级，因此改动分级或描述时检查所有留存版本的正文。
    declared_level = DataLevel(new_value["security_level"])
    chunks = (
        (
            await db.execute(
                select(EmbeddingChunk.content).where(
                    EmbeddingChunk.doc_id == document.id,
                    EmbeddingChunk.tenant_id == document.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    inspected = "\n".join(
        [str(text) for text in chunks]
        + [document.file_name]
        + [str(new_value.get(key) or "") for key in ("title", "issuer", "doc_number", "summary")]
    )
    detected_level = content_level(inspected, minimum=declared_level)
    if detected_level != declared_level:
        raise HTTPException(
            status_code=422, detail=f"文件内容至少需要标注为 {detected_level.value}"
        )
    for key, value in new_value.items():
        if key in ("effective_date", "expiration_date"):
            setattr(document, key, date_type.fromisoformat(value) if value else None)
        elif key == "tags":
            setattr(document, key, value)
        else:
            setattr(document, key, value)
    await audit_operation(
        db,
        request,
        user,
        action="update_metadata",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value=old_value,
        new_value=dict(new_value),
    )
    await db.commit()
    return APIResponse(
        data=DocumentResponse.from_document(document),
        trace_id=_trace_id(request),
    )


@router.get(
    "/knowledge-docs/{doc_id}/processing-status",
    response_model=APIResponse[dict],
    summary="向量化处理状态",
    description="待处理/处理中/可检索/失败 状态与数量；重试走既有受权限控制的向量化接口。",
    tags=["知识库"],
)
async def knowledge_processing_status(
    doc_id: str,
    request: Request,
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """按片段向量是否存在计算处理状态，失败原因来自最近一次处理记录。"""
    document = await _readable_document(db, user, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    count_stmt = select(
        func.count(EmbeddingChunk.id),
        func.count(EmbeddingChunk.id).filter(EmbeddingChunk.embedding.is_not(None)),
    ).where(EmbeddingChunk.doc_id == document.id, EmbeddingChunk.is_deleted.is_(False))
    total, embedded = (await execute_knowledge_query(db, count_stmt)).one()
    total, embedded = int(total or 0), int(embedded or 0)
    error = (document.doc_metadata or {}).get("vector_error")
    if total == 0:
        status_label = "failed" if error else "no_chunks"
    elif embedded == total:
        status_label = "ready"
    elif embedded > 0:
        status_label = "partial"
    else:
        status_label = "pending"
    await audit_operation(
        db,
        request,
        user,
        action="read_processing_status",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        new_value={"status": status_label, "total": total, "embedded": embedded},
    )
    await db.commit()
    return APIResponse(
        data={
            "doc_id": document.doc_id,
            "status": status_label,
            "total_chunks": total,
            "embedded_chunks": embedded,
            "pending_chunks": total - embedded,
            "error": error,
            "content_revision": (document.doc_metadata or {}).get("content_revision", 1),
            "retry_endpoint": (
                "/embeddings/embed" if status_label in ("pending", "partial", "failed") else None
            ),
        },
        trace_id=_trace_id(request),
    )


@router.get(
    "/knowledge-docs/{doc_id}/file",
    response_model=None,
    summary="下载授权原始文件",
    description="按当前权限下载对应版本原始文件；未留存或无权时明确拒绝。",
    tags=["知识库"],
)
async def download_original_file(
    doc_id: str,
    request: Request,
    revision: int | None = Query(None, ge=1),
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """下载与引用一致的版本原文；下载行为与旧版本访问遵守同一组织与分级控制。"""
    document = await _readable_document(db, user, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    stored = (document.doc_metadata or {}).get("original_file")
    target_revision = revision or (stored.get("revision") if isinstance(stored, dict) else None)
    if not target_revision or not stored:
        raise HTTPException(status_code=404, detail="原始文件未留存，暂无版本可下载")
    import asyncio

    try:
        content = await asyncio.to_thread(
            read_original, str(document.tenant_id), doc_id, int(target_revision)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="原始文件标识无效") from exc
    if content is None:
        raise HTTPException(status_code=404, detail="原始文件未留存，暂无版本可下载")
    file_name = stored.get("file_name") or document.file_name
    await audit_operation(
        db,
        request,
        user,
        action="download",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        new_value={"revision": int(target_revision), "size": len(content)},
    )
    await db.commit()
    disposition = f"attachment; filename*=UTF-8''{url_quote(file_name)}"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )
