"""兼容旧服务入口，复用正式检索器及当前数据库身份的资料授权。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenant import TenantIsolationError, current_user_id, get_tenant_id
from app.llm.base import DataLevel
from app.models.user import User, UserRole
from app.rag.retrieval.access import knowledge_filters
from app.rag.retrieval.base import Retriever
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever
from app.schemas.retrieval import RetrievalResponse, RetrievalResult
from app.services.identity_guard import ensure_active_identity


async def authorized_filters(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    if tenant_id != get_tenant_id():
        raise TenantIsolationError("检索租户必须匹配服务器上下文")
    actor = current_user_id.get()
    if actor:
        user = (
            await db.execute(select(User).where(User.id == actor, User.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if user is None:
            raise TenantIsolationError("检索缺少有效服务端身份")
        await ensure_active_identity(db, user)
        return knowledge_filters(user)
    # 未绑定人员的内部公开检索不能升级为校内/院系权限。
    return {
        "tenant_id": tenant_id,
        "role": UserRole.MEMBER.value,
        "org_unit_ids": [],
        "data_level": DataLevel.PUBLIC.value,
        "security_level": "public",
    }


class RetrievalService:
    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        tenant_id: str,
        data_level: DataLevel,
        user_role: UserRole | None = None,
        top_k: int | None = None,
        use_rerank: bool = True,
        retrieval_method: str = "hybrid",
    ) -> RetrievalResponse:
        filters = await authorized_filters(db, tenant_id)
        filters["include_expired"] = not settings.EXCLUDE_EXPIRED_BY_DEFAULT
        limit = top_k or (settings.RERANK_TOP_K if use_rerank else settings.RETRIEVAL_TOP_K)
        retriever: Retriever
        if retrieval_method == "vector":
            retriever = VectorRetriever(db, data_level=data_level)
        elif retrieval_method == "keyword":
            retriever = KeywordRetriever(db)
        elif retrieval_method == "hybrid":
            retriever = HybridRetriever(db, data_level=data_level, use_reranker=use_rerank)
        else:
            raise ValueError("未知检索方法")
        rows = await retriever.retrieve(query, top_k=limit, filters=filters)
        result = [
            RetrievalResult(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                content=row.content,
                score=row.score,
                article=row.article,
                sequence=row.sequence or 0,
                doc_title=row.metadata.get("title"),
                doc_number=row.metadata.get("doc_number"),
                issuer=row.metadata.get("issuer"),
                effective_date=str(row.effective_date) if row.effective_date else None,
                metadata=row.metadata,
            )
            for row in rows
        ]
        return RetrievalResponse(
            results=result,
            has_evidence=any(row.score >= settings.NO_EVIDENCE_THRESHOLD for row in rows),
            total_count=len(result),
            retrieval_method=retrieval_method,
            metadata={"threshold": settings.NO_EVIDENCE_THRESHOLD, "top_k": limit},
        )


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
