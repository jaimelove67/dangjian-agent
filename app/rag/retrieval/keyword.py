"""关键词检索器

基于 PostgreSQL 全文检索（FTS）+ pg_trgm 的混合关键词检索。
- 优先使用中文全文检索配置（chinese_zh）
- pg_trgm 用于子串模糊匹配兜底
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.retrieval.base import RetrievalResult, Retriever

logger = logging.getLogger(__name__)


class KeywordRetriever(Retriever):
    """关键词检索器（全文检索 + 模糊匹配）"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        use_fts: bool = True,
        use_trigram: bool = True,
        fts_weight: float = 0.7,
        trigram_weight: float = 0.3,
    ) -> None:
        """
        Args:
            db: 数据库会话
            use_fts: 是否使用全文检索
            use_trigram: 是否使用 pg_trgm 模糊匹配
            fts_weight: 全文检索权重
            trigram_weight: 模糊匹配权重
        """
        self.db = db
        self.use_fts = use_fts
        self.use_trigram = use_trigram
        self.fts_weight = fts_weight
        self.trigram_weight = trigram_weight

        if not (use_fts or use_trigram):
            raise ValueError("至少启用一种检索方式（use_fts 或 use_trigram）")

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """关键词检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件（同 VectorRetriever）

        Returns:
            检索结果列表，按相关度降序排列
        """
        if not query.strip():
            return []

        filters = filters or {}
        tenant_id = filters.get("tenant_id")
        doc_ids = filters.get("doc_ids")
        security_level = filters.get("security_level")
        doc_status = filters.get("status", "effective")

        # 构建查询
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
            )
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(KnowledgeDoc.status == doc_status)
        )

        # 应用过滤条件
        if tenant_id:
            stmt = stmt.where(EmbeddingChunk.tenant_id == tenant_id)
        if doc_ids:
            stmt = stmt.where(EmbeddingChunk.doc_id.in_(doc_ids))
        if security_level:
            stmt = stmt.where(KnowledgeDoc.security_level == security_level)

        # 计算相关度分数（全部使用 SQL 表达式，保证别名可被 row.score 访问）
        score_exprs = []

        if self.use_fts:
            # 全文检索排名（使用中文配置）
            ts_query = func.plainto_tsquery("chinese_zh", query)
            ts_vector = func.to_tsvector("chinese_zh", EmbeddingChunk.content)
            score_exprs.append(self.fts_weight * func.ts_rank(ts_vector, ts_query))
            stmt = stmt.where(ts_vector.op("@@")(ts_query))

        if self.use_trigram:
            # pg_trgm 相似度（0-1，越大越相似）
            trigram_sim = func.similarity(EmbeddingChunk.content, query)
            score_exprs.append(self.trigram_weight * trigram_sim)
            # 设置相似度阈值（避免无关结果）
            stmt = stmt.where(trigram_sim > 0.1)

        # 组合分数：加权求和
        score_expr = sum(score_exprs).label("score")

        stmt = stmt.add_columns(score_expr)
        stmt = stmt.order_by(text("score DESC")).limit(top_k)

        # 执行查询
        result = await self.db.execute(stmt)
        rows = result.fetchall()

        # 转换为检索结果
        results = []
        for row in rows:
            score = float(row.score) if hasattr(row, "score") else 0.0
            # 归一化分数到 0-1 范围
            score = min(1.0, max(0.0, score))

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
                        "retrieval_method": "keyword",
                    },
                )
            )

        logger.debug(
            "keyword_retrieval_completed",
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
