"""向量化管理接口"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.user import User
from app.rag.embedding_service import EmbeddingService
from app.rag.privacy import require_cloud_eligible
from app.rag.retrieval.access import knowledge_filters
from app.schemas.common import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 向量化需要管理员权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)


class EmbedRequest(BaseModel):
    """向量化请求"""

    doc_id: Optional[str] = Field(None, description="文档ID（为该文档的所有片段生成向量）")
    chunk_ids: Optional[list[str]] = Field(
        None, min_length=1, max_length=1000, description="片段ID列表"
    )
    force_update: bool = Field(False, description="是否强制更新已有向量")
    data_level: Optional[DataLevel] = Field(None, description="兼容旧客户端；实际等级由服务端决定")

    @model_validator(mode="after")
    def one_target(self) -> "EmbedRequest":
        if bool(self.doc_id) == bool(self.chunk_ids):
            raise ValueError("必须且只能指定 doc_id 或 chunk_ids")
        return self


class EmbedResponse(BaseModel):
    """向量化响应"""

    embedded_count: int = Field(..., description="成功向量化的片段数量")
    doc_id: Optional[str] = None
    chunk_ids: Optional[list[str]] = None


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


@router.post(
    "/embeddings/embed",
    response_model=APIResponse[EmbedResponse],
    summary="文档向量化",
    description="为指定文档或片段生成向量嵌入",
    tags=["向量化"],
)
async def embed_chunks(
    body: EmbedRequest,
    request: Request,
    user: User = Depends(_require_manage),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[EmbedResponse]:
    """文档向量化"""

    if body.data_level == DataLevel.CLASSIFIED:
        raise HTTPException(status_code=403, detail="涉密数据禁止向量化")
    data_level = body.data_level or DataLevel.INTERNAL
    require_cloud_eligible(data_level)

    # 创建向量化服务
    embedding_service = EmbeddingService(
        db, data_level=data_level, tenant_id=tenant_id, access_filters=knowledge_filters(user)
    )

    # 执行向量化
    embedded_count = await embedding_service.embed_chunks(
        doc_id=body.doc_id,
        chunk_ids=body.chunk_ids,
        force_update=body.force_update,
    )
    await audit_operation(
        db,
        request,
        user,
        action="embed",
        resource_type="knowledge_doc",
        data_level=data_level.value,
        new_value={"embedded_count": embedded_count},
    )
    await db.commit()

    logger.info(
        "chunks_embedded_via_api",
        extra={
            "doc_id": body.doc_id,
            "chunk_ids": body.chunk_ids,
            "embedded_count": embedded_count,
            "user": user.username,
        },
    )

    return APIResponse(
        data=EmbedResponse(
            embedded_count=embedded_count,
            doc_id=body.doc_id,
            chunk_ids=body.chunk_ids,
        ),
        trace_id=_trace_id(request),
    )


@router.post(
    "/embeddings/embed-all-pending",
    response_model=APIResponse[EmbedResponse],
    summary="向量化所有待处理片段",
    description="为所有尚未向量化的片段生成向量嵌入",
    tags=["向量化"],
)
async def embed_all_pending(
    request: Request,
    data_level: Optional[DataLevel] = None,
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_tenant),
) -> APIResponse[EmbedResponse]:
    """向量化所有待处理片段"""

    if data_level == DataLevel.CLASSIFIED:
        raise HTTPException(status_code=403, detail="涉密数据禁止向量化")
    dl = data_level or DataLevel.INTERNAL
    require_cloud_eligible(dl)

    # 创建向量化服务
    embedding_service = EmbeddingService(
        db, data_level=dl, tenant_id=tenant_id, access_filters=knowledge_filters(user)
    )

    # 执行向量化
    embedded_count = await embedding_service.embed_all_pending()
    await audit_operation(
        db,
        request,
        user,
        action="embed",
        resource_type="knowledge_doc",
        data_level=dl.value,
        new_value={"embedded_count": embedded_count},
    )
    await db.commit()

    logger.info(
        "all_pending_chunks_embedded_via_api",
        extra={
            "embedded_count": embedded_count,
            "user": user.username,
        },
    )

    return APIResponse(
        data=EmbedResponse(embedded_count=embedded_count),
        trace_id=_trace_id(request),
    )
