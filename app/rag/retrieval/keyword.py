"""关键词检索模块

使用PostgreSQL全文检索功能。
"""
from typing import List
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.schemas.retrieval import RetrievalFilters, RetrievalResult

logger = structlog.get_logger(__name__)


class KeywordRetriever:
    """关键词检索器

    使用PostgreSQL全文检索（基于search_vector生成列）。
    """

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        filters: RetrievalFilters,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """关键词检索

        Args:
            db: 数据库会话
            query: 查询文本
            filters: 过滤条件
            top_k: 返回结果数量

        Returns:
            检索结果列表（按相关度降序）
        """
        # 1. 构建tsquery（使用中文分词配置）
        # 注意：需要对查询进行分词和转义
        tsquery = func.plainto_tsquery("chinese_zh", query)

        # 2. 构建查询
        # 使用ts_rank计算相关度分数
        rank = func.ts_rank(KnowledgeDoc.search_vector, tsquery).label("rank")

        stmt = (
            select(
                EmbeddingChunk,
                KnowledgeDoc,
                rank,
            )
            .join(KnowledgeDoc, KnowledgeDoc.id == EmbeddingChunk.doc_id)
            .where(
                and_(
                    # 租户隔离
                    EmbeddingChunk.tenant_id == filters.tenant_id,
                    KnowledgeDoc.tenant_id == filters.tenant_id,

                    # 可见范围过滤
                    KnowledgeDoc.visibility.in_(filters.visibility_levels),

                    # 全文检索匹配
                    KnowledgeDoc.search_vector.op("@@")(tsquery),
                )
            )
        )

        # 时效过滤
        if filters.exclude_expired:
            stmt = stmt.where(KnowledgeDoc.status == "effective")

        # 保密级别过滤
        if filters.security_levels:
            stmt = stmt.where(KnowledgeDoc.security_level.in_(filters.security_levels))

        # 文档层级过滤
        if filters.doc_levels:
            stmt = stmt.where(KnowledgeDoc.level.in_(filters.doc_levels))

        # 按相关度排序，取top_k
        stmt = stmt.order_by(rank.desc()).limit(top_k)

        # 3. 执行查询
        result = await db.execute(stmt)
        rows = result.all()

        # 4. 转换为RetrievalResult
        results: List[RetrievalResult] = []
        for chunk, doc, rank_score in rows:
            # ts_rank返回的分数通常在0-1之间
            score = float(rank_score) if rank_score is not None else 0.0

            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=doc.doc_id,
                    content=chunk.content,
                    score=score,
                    article=chunk.article,
                    sequence=chunk.sequence,
                    doc_title=doc.title,
                    doc_number=doc.doc_number,
                    issuer=doc.issuer,
                    effective_date=str(doc.effective_date) if doc.effective_date else None,
                    metadata={
                        "level": doc.level,
                        "visibility": doc.visibility,
                        "security_level": doc.security_level,
                        "tags": list(doc.tags or []),
                    },
                )
            )

        logger.info(
            "keyword_retrieval_completed",
            query_length=len(query),
            top_k=top_k,
            results_count=len(results),
            tenant_id=filters.tenant_id,
        )

        return results
