"""知识库接口

- ``POST  /api/v1/knowledge-docs``：文档入库（带权限控制，需院系级及以上管理员）；
- ``GET   /api/v1/knowledge-docs/{doc_id}``：查询文档；
- ``PATCH /api/v1/knowledge-docs/{doc_id}/status``：变更文档状态。

租户标识从登录态解析，不接受前端传入（框架文档 8.2）。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_safe
from app.core.config import settings
from app.core.constants import AuditAction, AuditResult
from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.models.user import User
from app.rag.exceptions import ParseError, UnsupportedFormatError
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
    get_document,
    list_documents,
)

router = APIRouter()

# 入库 / 维护需要"院系级及以上管理员"权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)
# 列表查询只需知识库查询权限（登录用户）
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)


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
    doc_status: str = Form(
        "effective", alias="status", description="effective/expired/abolished"
    ),
    doc_number: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentCreateResponse]:
    """文档入库"""
    # 文件大小限制
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB）",
            },
        )

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
    except Exception as exc:
        # 捕获其他未预期的错误
        logger.exception("document_creation_failed", extra={"doc_id": doc_id})
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": f"文档入库失败: {str(exc)}",
            },
        ) from exc

    await write_audit_safe(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        user_name=user.username,
        action=AuditAction.CREATE,
        resource_type="knowledge_doc",
        resource_id=doc_id,
        request_id=getattr(request.state, "trace_id", "-"),
        result=AuditResult.SUCCESS,
        new_value={
            "title": title,
            "status": doc_status,
            "chunk_count": chunk_count,
        },
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
    "/knowledge-docs",
    response_model=APIResponse[DocumentListResponse],
    summary="文件列表",
    description="分页查询知识库文件列表，支持按状态与关键词过滤（仅返回未删除文件）。",
    tags=["知识库"],
)
async def list_knowledge_documents(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="effective/expired/abolished"
    ),
    keyword: Optional[str] = Query(
        None, max_length=100, description="按标题/发文机关/文号/编号模糊搜索"
    ),
    user: User = Depends(_require_query),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentListResponse]:
    """分页查询知识库文件列表"""
    documents, total = await list_documents(
        db,
        tenant_id=tenant_id,
        status=status_filter,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return APIResponse(
        data=DocumentListResponse(
            total=total,
            items=[DocumentResponse.from_document(doc) for doc in documents],
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
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """查询文档"""
    document = await get_document(db, doc_id=doc_id)
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

    await db.commit()
    return APIResponse(
        data=DocumentResponse.from_document(document),
        trace_id=_trace_id(request),
    )


@router.delete(
    "/knowledge-docs/{doc_id}",
    response_model=APIResponse[DocumentResponse],
    summary="删除文件",
    description="软删除知识库文件（标记为已废止并从检索环节排除），不做物理删除。",
    tags=["知识库"],
)
async def delete_knowledge_document(
    doc_id: str,
    request: Request,
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """软删除文档"""
    try:
        document = await delete_document(db, doc_id=doc_id, deleted_by=user.username)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": str(exc)},
        ) from exc

    await db.commit()
    return APIResponse(
        data=DocumentResponse.from_document(document),
        trace_id=_trace_id(request),
    )
