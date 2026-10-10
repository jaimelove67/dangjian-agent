"""按业务编号解析文档，在当前租户内批量向量化；事务由 API 管理。"""

import math
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantIsolationError, get_tenant_id
from app.llm.base import DataLevel
from app.llm.errors import ModelUnavailableError
from app.llm.service import get_model_service
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.rag.privacy import LEVELS, content_level, require_cloud_eligible
from app.rag.retrieval.access import apply_knowledge_access


class EmbeddingService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        data_level: DataLevel = DataLevel.INTERNAL,
        batch_size: int = 32,
        tenant_id: Optional[str] = None,
        access_filters: Optional[dict] = None,
    ) -> None:
        self.db = db
        self.data_level = data_level
        self.batch_size = batch_size
        self.tenant_id = tenant_id or get_tenant_id()
        self.access_filters = access_filters or {"tenant_id": self.tenant_id}
        self._model_service = get_model_service()

    def _query(self):
        if not self.tenant_id:
            raise TenantIsolationError("向量化缺少租户上下文")
        stmt = (
            select(EmbeddingChunk.id, EmbeddingChunk.content, KnowledgeDoc.security_level)
            .join(KnowledgeDoc, EmbeddingChunk.doc_id == KnowledgeDoc.id)
            .where(
                KnowledgeDoc.tenant_id == self.tenant_id,
                EmbeddingChunk.tenant_id == self.tenant_id,
                KnowledgeDoc.is_deleted.is_(False),
                EmbeddingChunk.is_deleted.is_(False),
                KnowledgeDoc.security_level.in_(["public", "internal", "sensitive"]),
            )
        )
        return apply_knowledge_access(
            stmt, {**self.access_filters, "include_expired": True, "include_future": True}
        )

    async def embed_chunks(
        self,
        *,
        doc_id: Optional[str] = None,
        chunk_ids: Optional[list[str]] = None,
        force_update: bool = False,
    ) -> int:
        if bool(doc_id) == bool(chunk_ids):
            raise ValueError("必须且只能指定 doc_id 或 chunk_ids")
        stmt = self._query()
        if doc_id:
            stmt = stmt.where(or_(KnowledgeDoc.doc_id == doc_id, KnowledgeDoc.id == doc_id))
        else:
            stmt = stmt.where(EmbeddingChunk.chunk_id.in_(chunk_ids))
        if not force_update:
            stmt = stmt.where(EmbeddingChunk.embedding.is_(None))
        return await self._embed(stmt)

    async def embed_all_pending(self) -> int:
        return await self._embed(
            self._query().where(
                EmbeddingChunk.embedding.is_(None),
                KnowledgeDoc.security_level.in_(["public", "internal"]),
            )
        )

    async def _embed(self, stmt) -> int:
        """按主键游标分批，向量条数、维度和有限值全部校验后再写入。"""
        count, cursor = 0, None
        while True:
            batch_stmt = stmt.order_by(EmbeddingChunk.id).limit(self.batch_size)
            if cursor:
                batch_stmt = batch_stmt.where(EmbeddingChunk.id > cursor)
            rows = (await self.db.execute(batch_stmt)).fetchall()
            if not rows:
                break
            level = max(
                [self.data_level]
                + [
                    content_level(row.content, minimum=DataLevel(row.security_level))
                    for row in rows
                ],
                key=LEVELS.index,
            )
            require_cloud_eligible(level)
            response = await self._model_service.embed(
                texts=[row.content for row in rows],
                data_level=level,
            )
            vectors = response.embeddings
            if len(vectors) != len(rows) or any(
                len(vector) != 1024 or not all(math.isfinite(value) for value in vector)
                for vector in vectors
            ):
                raise ModelUnavailableError("向量模型输出条数、维度或数值不符合要求")
            for row, vector in zip(rows, vectors):
                await self.db.execute(
                    update(EmbeddingChunk)
                    .where(EmbeddingChunk.id == row.id, EmbeddingChunk.tenant_id == self.tenant_id)
                    .values(embedding=vector)
                )
            count += len(rows)
            cursor = rows[-1].id
        return count
