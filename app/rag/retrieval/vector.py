"""向量检索模块

使用pgvector进行语义相似度检索。
"""
from typing import List, Optional
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.schemas.retrieval import RetrievalFilters, RetrievalResult
from app.llm.service import ModelService
from app.llm.base import DataLevel

logger = structlog.get_logger(__name__)


class VectorRetriever:
    """向量检索器

    使用pgvector余弦相似度进行语义检索。
    """

    def __init__(self, model_service: Optional[ModelService] = None):
        """初始化

        Args:
            model_service: 模型服务（用于向量化查询）
        """
        from app.llm.service import get_model_service
        self.model_service = model_service or get_model_service()

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        filters: RetrievalFilters,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """向量检索

        Args:
            db: 数据库会话
            query: 查询文本
            filters: 过滤条件
            top_k: 返回结果数量

        Returns:
            检索结果列表（按相似度降序）
        """
        # 1. 查询向量化
        try:
            embedding_response = await self.model_service.embed(
                texts=[query],
                data_level=filters.data_level,
                context={"action": "retrieval", "tenant_id": filters.tenant_id},
            )
            query_embedding = embedding_response.embeddings[0]
        except Exception as e:
            logger.error(
                "query_embedding_failed",
                error=str(e),
                query=query[:50],
            )
            return []

        # 2. 构建查询
        # 使用pgvector的余弦相似度运算符 <=>
        stmt = (
            select(
                EmbeddingChunk,
                KnowledgeDoc,
                EmbeddingChunk.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .join(KnowledgeDoc, KnowledgeDoc.id == EmbeddingChunk.doc_id)
            .where(
                and_(
                    # 租户隔离
                    EmbeddingChunk.tenant_id == filters.tenant_id,
                    KnowledgeDoc.tenant_id == filters.tenant_id,

                    # 可见范围过滤
                    KnowledgeDoc.visibility.in_(filters.visibility_levels),

                    # 向量不为空
                    EmbeddingChunk.embedding.isnot(None),
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

        # 按相似度排序，取top_k
        stmt = stmt.order_by("distance").limit(top_k)

        # 3. 执行查询
        result = await db.execute(stmt)
        rows = result.all()

        # 4. 转换为RetrievalResult
        results: List[RetrievalResult] = []
        for chunk, doc, distance in rows:
            # 将distance转换为score (0-1之间，越大越相似)
            score = 1.0 - float(distance) if distance is not None else 0.0

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
            "vector_retrieval_completed",
            query_length=len(query),
            top_k=top_k,
            results_count=len(results),
            tenant_id=filters.tenant_id,
        )

        return results
