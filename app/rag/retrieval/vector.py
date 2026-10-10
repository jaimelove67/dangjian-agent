"""基于 pgvector 的向量召回，授权过滤与关键词召回共用。"""

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.llm.service import get_model_service
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.privacy import content_level, require_cloud_eligible
from app.rag.retrieval.access import (
    apply_knowledge_access,
    execute_knowledge_query,
    source_columns,
    source_metadata,
)
from app.rag.retrieval.base import RetrievalResult, Retriever


class VectorRetriever(Retriever):
    def __init__(self, db: AsyncSession, *, data_level: DataLevel = DataLevel.PUBLIC) -> None:
        self.db = db
        self.data_level = data_level
        self._model_service = get_model_service()

    async def retrieve(
        self, query: str, *, top_k: int = 10, filters: Optional[dict[str, Any]] = None
    ) -> list[RetrievalResult]:
        if not query.strip():
            return []
        level = content_level(query, minimum=self.data_level)
        require_cloud_eligible(level)
        response = await self._model_service.embed(texts=[query], data_level=level)
        if len(response.embeddings) != 1 or len(response.embeddings[0]) != 1024:
            raise ValueError("向量模型必须输出 1024 维向量")
        distance = EmbeddingChunk.embedding.cosine_distance(response.embeddings[0]).label(
            "distance"
        )
        stmt = (
            select(*source_columns(), distance)
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(EmbeddingChunk.embedding.isnot(None))
        )
        stmt = apply_knowledge_access(stmt, filters or {}).order_by(distance).limit(top_k)
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
                score=min(1.0, max(0.0, 1.0 - float(row.distance))),
                metadata=source_metadata(row, "vector"),
            )
            for row in rows
        ]
