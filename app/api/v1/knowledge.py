"""知识库接口

- ``POST  /api/v1/knowledge-docs``：文档入库（带权限控制，需院系级及以上管理员）；
- ``GET   /api/v1/knowledge-docs/{doc_id}``：查询文档；
- ``PATCH /api/v1/knowledge-docs/{doc_id}/status``：变更文档状态。
- ``DELETE /api/v1/knowledge-docs/{doc_id}``：按管理范围软删除文档及片段。

租户标识从登录态解析，不接受前端传入（框架文档 8.2）。
"""

from __future__ import annotations

import json
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
from app.core.constants import AuditAction, DocumentStatus, DocumentValidity
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
    DocumentMaintenanceRequest,
    DocumentResponse,
    DocumentReviewRequest,
    DocumentStatusUpdate,
)
from app.services.file_store import read_original, save_original, validate_identifier
from app.services.governance_service import supply_rules
from app.services.knowledge_service import (
    DocumentConflictError,
    DocumentMaintenanceError,
    DocumentNotFoundError,
    DocumentReviewError,
    change_document_status,
    confirm_maintenance,
    create_document,
    delete_document,
    reopen_review,
    replace_document_content,
    review_document,
    supply_cycle,
    sync_review_schedule,
)
from app.services.org_scope import accessible_org_units

router = APIRouter()
logger = logging.getLogger(__name__)

# 入库 / 维护需要"院系级及以上管理员"权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)
_require_query = require_permissions(Permission.KNOWLEDGE_QUERY)
# 公共库内容审核发布：知识库审核权限（T-KB-12）
_require_knowledge_review = require_permissions(Permission.KNOWLEDGE_REVIEW)
_AUTHORITY_PATTERN = (
    "^(party_constitution|party_regulation|superior_document|school_policy|reference)$"
)
_VALIDITY_PATTERN = "^(effective|pending|superseded|repealed)$"


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
) -> APIResponse[dict[str, Any]]:
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


def _parse_field_levels(raw: str | None) -> dict[str, str] | None:
    """解析字段级敏感等级 JSON（T-DATA-05）；空值表示不标注。

    取值合法性（字段名、等级、与文档密级的关系）统一由元数据校验规则负责，
    这里只负责拒绝无法解析的报文。
    """
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": ErrorCode.BUSINESS_ERROR,
                "message": f"字段级敏感等级不是合法 JSON: {exc}",
            },
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": "字段级敏感等级必须是 JSON 对象"},
        )
    return {str(key): value for key, value in parsed.items()}


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
    authority: str = Form(
        "", description="权威来源：党章/党内法规/上级文件/学校制度/参考资料；空=按层级推定"
    ),
    validity: str = Form(
        "effective", description="效力状态：effective/pending/superseded/repealed"
    ),
    field_levels: str | None = Form(
        None, description='字段级敏感等级 JSON，如 {"summary":"internal"}'
    ),
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
        "authority": authority or None,
        "validity": validity,
        "field_levels": _parse_field_levels(field_levels),
        "tags": _split_tags(tags),
        "summary": summary,
        "org_unit_id": user.org_unit_id,
        # 供给责任人（T-KB-13）：记录入库账号，便于内容维护与审核追溯。
        "uploaded_by": str(user.id),
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
        document.doc_metadata = {
            **(document.doc_metadata or {}),
            "original_file": stored,
            "original_versions": {str(original_version): stored},
        }
    except OSError:
        if settings.ENV == "production":
            raise HTTPException(503, "加密原件保存失败，入库未提交") from None
        # 非生产环境不阻断入库，但必须留下可诊断的堆栈：否则原件静默缺失，
        # 直到用户点"下载原件"才以 404 暴露，且现场已无从查证。
        logger.warning("original_file_save_failed", extra={"doc_id": doc_id}, exc_info=True)
    await db.commit()
    return APIResponse(
        data=DocumentCreateResponse(
            document=DocumentResponse.from_document(
                document,
                page_count=page_count,
                supply=await _supply_rule(db, document),
            ),
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
    review_status: str | None = Query(None, description="pending/published/rejected（需维护权限）"),
    due_for_review: bool | None = Query(
        None, description="true=只看已到复核期限且仍现行有效的条目（T-KB-13）"
    ),
    user: User = Depends(_require_query),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentListResponse]:
    can_manage = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    filters = knowledge_filters(user, include_expired=True, include_unpublished=can_manage)
    filters["include_future"] = can_manage
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
    if review_status:
        # 待审队列只对维护人员开放，否则未发布内容会经列表页泄露给普通党员。
        if not can_manage:
            raise HTTPException(status_code=403, detail="无权查看审核状态筛选结果")
        stmt = stmt.where(KnowledgeDoc.review_status == review_status)
    if due_for_review:
        # 与 DocumentResponse.review_due 同口径：有日程、仍在现行有效、且已到期。
        stmt = stmt.where(
            KnowledgeDoc.next_review_at.isnot(None),
            KnowledgeDoc.next_review_at <= date_type.today(),
            KnowledgeDoc.status == DocumentStatus.EFFECTIVE.value,
            KnowledgeDoc.validity == DocumentValidity.EFFECTIVE.value,
        )
    counts_query = stmt.with_only_columns(KnowledgeDoc.status, func.count()).group_by(
        KnowledgeDoc.status
    )
    counts = {
        status: count for status, count in (await execute_knowledge_query(db, counts_query)).all()
    }
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
    # 供给机制按租户读取（管理端可能跨租户查看），每个租户只查一次（T-KB-13）。
    supply_cache: dict[str, dict[str, Any]] = {}
    items: list[DocumentResponse] = []
    for doc in documents:
        tenant_key = str(doc.tenant_id)
        if tenant_key not in supply_cache:
            supply_cache[tenant_key] = await supply_rules(db, tenant_key)
        items.append(
            DocumentResponse.from_document(doc, supply=supply_cache[tenant_key].get(doc.authority))
        )
    return APIResponse(
        data=DocumentListResponse(
            items=items,
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
    can_manage = has_permission(user.role, Permission.KNOWLEDGE_MANAGE)
    filters = knowledge_filters(user, include_expired=True, include_unpublished=can_manage)
    filters["include_future"] = can_manage
    stmt = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False).where(
        KnowledgeDoc.doc_id == doc_id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await execute_knowledge_query(db, stmt)).scalar_one_or_none()


async def _supply_rule(db: AsyncSession, document: KnowledgeDoc) -> dict[str, Any] | None:
    """按条目的权威来源解析供给机制（T-KB-13）

    责任部门 / 责任人与更新周期由学校「供给机制」按权威来源统一给出，条目本身
    不复制一份，机制调整后立刻对所有条目生效。未登记该类别时返回 ``None``，
    出参对应字段为空，前端据此提示「尚未登记供给责任人」。
    """
    rules = await supply_rules(db, str(document.tenant_id))
    rule = rules.get(document.authority)
    return dict(rule) if rule else None


async def _document_response(db: AsyncSession, document: KnowledgeDoc) -> DocumentResponse:
    """单条文档出参：并入该条目权威来源的供给责任与复核日程"""
    return DocumentResponse.from_document(document, supply=await _supply_rule(db, document))


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
) -> APIResponse[DocumentCreateResponse]:
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
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": str(exc)},
        ) from None
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": f"文档解析失败: {str(exc)}"},
        ) from None
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
        metadata = dict(document.doc_metadata or {})
        versions = dict(metadata.get("original_versions", {}))
        previous = metadata.get("original_file")
        if isinstance(previous, dict):
            versions[str(previous["revision"])] = previous
        versions[str(old_revision + 1)] = stored
        document.doc_metadata = {**metadata, "original_file": stored, "original_versions": versions}
    except OSError:
        if settings.ENV == "production":
            raise HTTPException(503, "加密原件保存失败，更新未提交") from None
        # 非生产环境不阻断入库，但必须留下可诊断的堆栈：否则原件静默缺失，
        # 直到用户点"下载原件"才以 404 暴露，且现场已无从查证。
        logger.warning("original_file_save_failed", extra={"doc_id": doc_id}, exc_info=True)
    await db.commit()
    return APIResponse(
        data=DocumentCreateResponse(
            document=await _document_response(db, document), chunk_count=count
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
        data=await _document_response(db, document),
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
        data=await _document_response(db, document),
        trace_id=_trace_id(request),
    )


@router.post(
    "/knowledge-docs/{doc_id}/review",
    response_model=APIResponse[DocumentResponse],
    summary="审核发布公共库内容",
    description=(
        "公共可见内容入库后为待审，批准后才进入检索范围；退回须填写审核意见。"
        "审核留痕记录审核人、时间与意见（T-KB-12）。"
    ),
    tags=["知识库"],
)
async def review_knowledge_document(
    doc_id: str,
    body: DocumentReviewRequest,
    request: Request,
    user: User = Depends(_require_knowledge_review),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """审核公共库内容：批准发布或退回修正"""
    try:
        document = await review_document(
            db,
            doc_id=doc_id,
            tenant_id=tenant_id,
            decision=body.decision,
            reviewer_id=str(user.id),
            note=body.note,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": str(exc)},
        ) from exc
    except DocumentReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": ErrorCode.BUSINESS_ERROR, "message": str(exc)},
        ) from exc

    await audit_operation(
        db,
        request,
        user,
        action="review",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        new_value={
            "decision": body.decision,
            "review_status": document.review_status,
            "note": document.review_note,
        },
    )
    await db.commit()
    return APIResponse(
        data=await _document_response(db, document),
        trace_id=_trace_id(request),
    )


@router.post(
    "/knowledge-docs/{doc_id}/maintenance",
    response_model=APIResponse[DocumentResponse],
    summary="登记供给复核确认",
    description=(
        "确认条目仍现行有效或已随法规修订同步更新，并按学校「供给机制」的更新周期"
        "重排下次复核日程；非现行有效的条目不予复核。复核留痕记录复核人与说明"
        "（T-KB-13）。"
    ),
    tags=["知识库"],
)
async def confirm_knowledge_maintenance(
    doc_id: str,
    body: DocumentMaintenanceRequest,
    request: Request,
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DocumentResponse]:
    """登记一次复核确认：核对现行有效并重排下次复核日程"""
    original = await _readable_document(db, user, doc_id)
    if original is None or str(original.tenant_id) != str(user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": "文档不存在"},
        )
    previous_maintained = original.maintained_at
    previous_next_review = original.next_review_at
    try:
        document = await confirm_maintenance(
            db,
            doc_id=doc_id,
            tenant_id=tenant_id,
            reviewer_id=str(user.id),
            note=body.note,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": str(exc)},
        ) from exc
    except DocumentMaintenanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def stamp(value: Any) -> str | None:
        return value.isoformat() if value else None

    await audit_operation(
        db,
        request,
        user,
        action=AuditAction.MAINTAIN.value,
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value={
            "maintained_at": stamp(previous_maintained),
            "next_review_at": stamp(previous_next_review),
        },
        new_value={
            "maintained_at": stamp(document.maintained_at),
            "next_review_at": stamp(document.next_review_at),
            "note": body.note,
        },
    )
    await db.commit()
    return APIResponse(
        data=await _document_response(db, document),
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
    return APIResponse(data=await _document_response(db, document), trace_id=_trace_id(request))


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
    authority: str | None = Field(None, pattern=_AUTHORITY_PATTERN)
    validity: str | None = Field(None, pattern=_VALIDITY_PATTERN)
    field_levels: dict[str, str] | None = Field(
        None, description="字段级敏感等级，置 null 表示清除"
    )
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
    # 复核日程不参与元数据修正循环（那是 date 列，不能当字符串写回），
    # 只在下面「生效日期 / 权威来源变更」时重排，审计单独记录前后值。
    previous_next_review = document.next_review_at
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
        "authority": document.authority,
        "validity": document.validity,
        "field_levels": dict(document.field_levels or {}),
    }
    new_value = dict(old_value)
    for key, value in changes.items():
        if key in ("effective_date", "expiration_date"):
            new_value[key] = value or None
            continue
        if key == "field_levels":
            new_value[key] = dict(value) if value else None
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
        else:
            setattr(document, key, value)
    # 效力状态与运行状态在「废止」处对齐（T-DATA-05）：标为已废止即退出运行有效；
    # 把效力状态显式恢复为现行有效时，运行状态也从「已废止」恢复。
    if new_value.get("validity") == DocumentValidity.REPEALED.value:
        document.status = DocumentStatus.ABOLISHED.value
    elif (
        new_value.get("validity") == DocumentValidity.EFFECTIVE.value
        and document.status == DocumentStatus.ABOLISHED.value
    ):
        document.status = DocumentStatus.EFFECTIVE.value
    # 可见范围从非公共提升为公共=进入公共库，必须重新审核（T-KB-12）。
    if new_value["visibility"] == "public" and old_value["visibility"] != "public":
        if reopen_review(document):
            logger.info("knowledge_document_review_reopened", extra={"doc_id": doc_id})
    # 生效日期或权威来源变了，复核日程的基准与周期随之改变（T-KB-13）。
    if "effective_date" in changes or "authority" in changes:
        sync_review_schedule(
            document,
            review_cycle_days=await supply_cycle(
                db, tenant_id=str(document.tenant_id), authority=document.authority
            ),
        )
    await audit_operation(
        db,
        request,
        user,
        action="update_metadata",
        resource_type="knowledge_doc",
        resource_id=str(document.id),
        data_level=document.security_level,
        old_value={
            **old_value,
            "next_review_at": (previous_next_review.isoformat() if previous_next_review else None),
        },
        new_value={
            **new_value,
            "next_review_at": (
                document.next_review_at.isoformat() if document.next_review_at else None
            ),
        },
    )
    await db.commit()
    return APIResponse(
        data=await _document_response(db, document),
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

    versions = (document.doc_metadata or {}).get("original_versions", {})
    stored_version = versions.get(str(target_revision)) or (
        stored if stored.get("revision") == target_revision else {}
    )

    try:
        content = await asyncio.to_thread(
            read_original,
            str(document.tenant_id),
            doc_id,
            int(target_revision),
            stored_version.get("sha256"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="原始文件标识无效") from exc
    if content is None:
        raise HTTPException(status_code=404, detail="原始文件未留存，暂无版本可下载")
    file_name = stored_version.get("file_name") or stored.get("file_name") or document.file_name
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
