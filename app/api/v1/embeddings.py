"""向量化管理接口"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission
from app.db.session import get_db
from app.deps import get_current_tenant, require_permissions
from app.llm.base import DataLevel
from app.models.user import User
from app.rag.embedding_service import EmbeddingService
from app.schemas.common import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 向量化需要管理员权限
_require_manage = require_permissions(Permission.KNOWLEDGE_MANAGE)


class EmbedRequest(BaseModel):
    """向量化请求"""

    doc_id: Optional[str] = Field(None, description="文档ID（为该文档的所有片段生成向量）")
    chunk_ids: Optional[list[str]] = Field(None, description="片段ID列表")
    force_update: bool = Field(False, description="是否强制更新已有向量")
    data_level: str = Field("public", description="数据级别：public/internal/sensitive")


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

    # 解析数据级别
    data_level_map = {
        "public": DataLevel.PUBLIC,
        "internal": DataLevel.INTERNAL,
        "sensitive": DataLevel.SENSITIVE,
    }
    data_level = data_level_map.get(body.data_level.lower(), DataLevel.PUBLIC)

    # 创建向量化服务
    embedding_service = EmbeddingService(db, data_level=data_level)

    # 执行向量化
    embedded_count = await embedding_service.embed_chunks(
        doc_id=body.doc_id,
        chunk_ids=body.chunk_ids,
        force_update=body.force_update,
    )

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
    data_level: str = "public",
    user: User = Depends(_require_manage),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[EmbedResponse]:
    """向量化所有待处理片段"""

    # 解析数据级别
    data_level_map = {
        "public": DataLevel.PUBLIC,
        "internal": DataLevel.INTERNAL,
        "sensitive": DataLevel.SENSITIVE,
    }
    dl = data_level_map.get(data_level.lower(), DataLevel.PUBLIC)

    # 创建向量化服务
    embedding_service = EmbeddingService(db, data_level=dl)

    # 执行向量化
    embedded_count = await embedding_service.embed_all_pending()

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
