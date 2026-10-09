"""知识库接口

- ``POST  /api/v1/knowledge-docs``：文档入库（带权限控制，需院系级及以上管理员）；
- ``GET   /api/v1/knowledge-docs/{doc_id}``：查询文档；
- ``PATCH /api/v1/knowledge-docs/{doc_id}/status``：变更文档状态。

租户标识从登录态解析，不接受前端传入（框架文档 8.2）。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.models.user import User
from app.rules.document_metadata import MetadataValidationError
from app.schemas.common import APIResponse, ErrorCode
from app.schemas.knowledge import (
    DocumentCreateResponse,
    DocumentResponse,
    DocumentStatusUpdate,
)
from app.services.knowledge_service import (
    DocumentConflictError,
    DocumentNotFoundError,
    change_document_status,
    create_document,
    get_document,
)

router = APIRouter()

# 入库 / 维护需要"院系级及以上管理员"权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)


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
    description="上传文档并携带完整元数据；必填项缺失将拒绝入库。",
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
    content = await file.read()

    try:
        document, chunk_count = await create_document(
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

    await db.commit()
    return APIResponse(
        data=DocumentCreateResponse(
            document=DocumentResponse.from_document(document),
            chunk_count=chunk_count,
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
        document = await change_document_status(db, doc_id=doc_id, new_status=body.status)
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
