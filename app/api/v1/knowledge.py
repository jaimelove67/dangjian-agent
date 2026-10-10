"""知识库接口

- ``POST  /api/v1/knowledge-docs``：文档入库（带权限控制，需院系级及以上管理员）；
- ``GET   /api/v1/knowledge-docs/{doc_id}``：查询文档；
- ``PATCH /api/v1/knowledge-docs/{doc_id}/status``：变更文档状态。
- ``DELETE /api/v1/knowledge-docs/{doc_id}``：按管理范围软删除文档及片段。

租户标识从登录态解析，不接受前端传入（框架文档 8.2）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

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
from app.rules.document_metadata import MetadataValidationError
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.knowledge import (
    DocumentCreateResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusUpdate,
)
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
    data_level: Optional[DataLevel] = None


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


def _trace_id(request: Request) -> Optional[str]:
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
    expiration_date: Optional[str] = Form(None, description="YYYY-MM-DD，空表示长期有效"),
    doc_status: str = Form("effective", alias="status", description="effective/expired/abolished"),
    doc_number: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentCreateResponse]:
    """文档入库"""
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
    doc_status: Optional[str] = Query(None, alias="status"),
    level: Optional[str] = Query(None),
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


async def _readable_document(db: AsyncSession, user: User, doc_id: str) -> Optional[KnowledgeDoc]:
    filters = knowledge_filters(user, include_expired=True)
    filters["include_future"] = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    stmt = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False).where(
        KnowledgeDoc.doc_id == doc_id
    )
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
