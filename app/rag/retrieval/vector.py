"""向量检索器

基于 pgvector 的语义相似度检索。使用余弦相似度（<=>）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.llm.service import get_model_service
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.retrieval.base import RetrievalResult, Retriever

logger = logging.getLogger(__name__)


class VectorRetriever(Retriever):
    """向量检索器（基于语义相似度）"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        data_level: DataLevel = DataLevel.PUBLIC,
    ) -> None:
        """
        Args:
            db: 数据库会话
            data_level: 数据级别（用于模型路由）
        """
        self.db = db
        self.data_level = data_level
        self._model_service = get_model_service()

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """向量检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件
                - tenant_id: 租户ID
                - doc_ids: 文档ID列表
                - security_level: 保密级别
                - status: 文档状态

        Returns:
            检索结果列表，按相似度降序排列
        """
        if not query.strip():
            return []

        # 1. 查询文本向量化
        embed_response = await self._model_service.embed(
            texts=[query],
            data_level=self.data_level,
        )
        query_vector = embed_response.embeddings[0]

        # 2. 构建查询条件
        filters = filters or {}
        tenant_id = filters.get("tenant_id")
        doc_ids = filters.get("doc_ids")
        security_level = filters.get("security_level")
        doc_status = filters.get("status", "effective")

        # 3. 向量相似度检索（使用余弦距离 <=>）
        # 注意：<=> 返回距离（越小越相似），需要转换为分数（1 - distance）
        stmt = (
            select(
                EmbeddingChunk.chunk_id,
                EmbeddingChunk.content,
                EmbeddingChunk.doc_id,
                EmbeddingChunk.article,
                EmbeddingChunk.sequence,
                KnowledgeDoc.title,
                KnowledgeDoc.issuer,
                KnowledgeDoc.doc_number,
                KnowledgeDoc.level,
                KnowledgeDoc.security_level,
                KnowledgeDoc.status.label("doc_status"),
                KnowledgeDoc.effective_date,
                KnowledgeDoc.expiration_date,
                # 余弦距离
                literal_column(f"embedding <=> ARRAY{query_vector}::vector").label("distance"),
            )
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(EmbeddingChunk.embedding.isnot(None))  # 只检索已向量化的片段
            .where(KnowledgeDoc.status == doc_status)
        )

        # 应用过滤条件
        if tenant_id:
            stmt = stmt.where(EmbeddingChunk.tenant_id == tenant_id)
        if doc_ids:
            stmt = stmt.where(EmbeddingChunk.doc_id.in_(doc_ids))
        if security_level:
            stmt = stmt.where(KnowledgeDoc.security_level == security_level)

        # 按距离排序并限制结果数量
        stmt = stmt.order_by(text("distance")).limit(top_k)

        result = await self.db.execute(stmt)
        rows = result.fetchall()

        # 4. 转换为检索结果
        results = []
        for row in rows:
            # 余弦距离转换为相似度分数（1 - distance）
            distance = float(row.distance)
            score = max(0.0, 1.0 - distance)

            results.append(
                RetrievalResult(
                    chunk_id=row.chunk_id,
                    content=row.content,
                    score=score,
                    doc_id=row.doc_id,
                    article=row.article,
                    sequence=row.sequence,
                    doc_status=row.doc_status,
                    effective_date=row.effective_date,
                    expiration_date=row.expiration_date,
                    metadata={
                        "title": row.title,
                        "issuer": row.issuer,
                        "doc_number": row.doc_number,
                        "level": row.level,
                        "security_level": row.security_level,
                        "retrieval_method": "vector",
                    },
                )
            )

        logger.debug(
            "vector_retrieval_completed",
            extra={
                "query": query[:50],
                "top_k": top_k,
                "result_count": len(results),
                "avg_score": sum(r.score for r in results) / len(results)
                if results
                else 0.0,
            },
        )

        return results
