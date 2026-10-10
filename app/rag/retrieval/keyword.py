"""FTS 与 pg_trgm 分别召回；全文未命中时仍能使用模糊匹配。"""

from typing import Any, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.retrieval.access import (
    apply_knowledge_access,
    execute_knowledge_query,
    source_columns,
    source_metadata,
)
from app.rag.retrieval.base import RetrievalResult, Retriever


class KeywordRetriever(Retriever):
    def __init__(
        self,
        db: AsyncSession,
        *,
        use_fts: bool = True,
        use_trigram: bool = True,
        fts_weight: float = 0.7,
        trigram_weight: float = 0.3,
    ) -> None:
        if not (use_fts or use_trigram):
            raise ValueError("至少启用一种检索方式（use_fts 或 use_trigram）")
        self.db = db
        self.use_fts = use_fts
        self.use_trigram = use_trigram
        self.fts_weight = fts_weight
        self.trigram_weight = trigram_weight

    async def retrieve(
        self, query: str, *, top_k: int = 10, filters: Optional[dict[str, Any]] = None
    ) -> list[RetrievalResult]:
        query = query.strip()
        if not query:
            return []
        conditions, scores = [], []
        if self.use_fts:
            ts_query = func.plainto_tsquery("chinese_zh", query)
            ts_vector = func.to_tsvector("chinese_zh", EmbeddingChunk.content)
            conditions.append(ts_vector.op("@@")(ts_query))
            scores.append(func.ts_rank(ts_vector, ts_query, 32))
        if self.use_trigram:
            similarity = func.similarity(EmbeddingChunk.content, query)
            exact = EmbeddingChunk.content.contains(query, autoescape=True)
            conditions.append(or_(similarity > 0.1, exact))
            scores.append(case((exact, 1.0), else_=similarity))
        score = (func.greatest(*scores) if len(scores) > 1 else scores[0]).label("score")
        stmt = (
            select(*source_columns(), score)
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(or_(*conditions))
        )
        stmt = apply_knowledge_access(stmt, filters or {}).order_by(score.desc()).limit(top_k)
        rows = (await execute_knowledge_query(self.db, stmt)).fetchall()
        return [
            RetrievalResult(
                chunk_id=row.chunk_id,
                content=row.content,
                doc_id=row.doc_id,
                article=row.article,
                sequence=row.sequence,
                doc_status=row.status,
                effective_date=row.effective_date,
                expiration_date=row.expiration_date,
                score=min(1.0, max(0.0, float(row.score))),
                metadata=source_metadata(row, "keyword"),
            )
            for row in rows
        ]
