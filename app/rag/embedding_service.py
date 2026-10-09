"""向量化服务

负责为已入库的文档片段生成向量嵌入。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.llm.service import get_model_service
from app.models.knowledge import EmbeddingChunk

logger = logging.getLogger(__name__)


class EmbeddingService:
    """向量化服务"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        data_level: DataLevel = DataLevel.PUBLIC,
        batch_size: int = 32,
    ) -> None:
        """
        Args:
            db: 数据库会话
            data_level: 数据级别
            batch_size: 批处理大小
        """
        self.db = db
        self.data_level = data_level
        self.batch_size = batch_size
        self._model_service = get_model_service()

    async def embed_chunks(
        self,
        *,
        doc_id: Optional[str] = None,
        chunk_ids: Optional[list[str]] = None,
        force_update: bool = False,
    ) -> int:
        """为片段生成向量嵌入

        Args:
            doc_id: 文档ID（为该文档的所有片段生成向量）
            chunk_ids: 片段ID列表（为指定片段生成向量）
            force_update: 是否强制更新已有向量

        Returns:
            成功向量化的片段数量
        """
        # 构建查询条件
        stmt = select(EmbeddingChunk.id, EmbeddingChunk.chunk_id, EmbeddingChunk.content)

        if doc_id:
            stmt = stmt.where(EmbeddingChunk.doc_id == doc_id)
        elif chunk_ids:
            stmt = stmt.where(EmbeddingChunk.chunk_id.in_(chunk_ids))
        else:
            raise ValueError("必须指定 doc_id 或 chunk_ids")

        # 如果不强制更新，只处理未向量化的片段
        if not force_update:
            stmt = stmt.where(EmbeddingChunk.embedding.is_(None))

        result = await self.db.execute(stmt)
        chunks = result.fetchall()

        if not chunks:
            logger.info(
                "no_chunks_to_embed",
                extra={"doc_id": doc_id, "chunk_ids": chunk_ids},
            )
            return 0

        # 批量向量化
        total_embedded = 0
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            batch_texts = [chunk.content for chunk in batch]

            # 调用向量化模型
            embed_response = await self._model_service.embed(
                texts=batch_texts,
                data_level=self.data_level,
            )

            # 更新数据库
            for chunk, embedding in zip(batch, embed_response.embeddings):
                await self.db.execute(
                    update(EmbeddingChunk)
                    .where(EmbeddingChunk.id == chunk.id)
                    .values(embedding=embedding)
                )

            total_embedded += len(batch)
            logger.debug(
                "batch_embedded",
                extra={
                    "batch_size": len(batch),
                    "total_embedded": total_embedded,
                    "total_chunks": len(chunks),
                },
            )

        await self.db.commit()

        logger.info(
            "chunks_embedded",
            extra={
                "doc_id": doc_id,
                "total_embedded": total_embedded,
            },
        )

        return total_embedded

    async def embed_all_pending(self) -> int:
        """向量化所有待处理的片段

        Returns:
            成功向量化的片段数量
        """
        stmt = select(EmbeddingChunk.id, EmbeddingChunk.content).where(
            EmbeddingChunk.embedding.is_(None)
        )
        result = await self.db.execute(stmt)
        chunks = result.fetchall()

        if not chunks:
            logger.info("no_pending_chunks_to_embed")
            return 0

        # 批量向量化
        total_embedded = 0
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            batch_texts = [chunk.content for chunk in batch]

            # 调用向量化模型
            embed_response = await self._model_service.embed(
                texts=batch_texts,
                data_level=self.data_level,
            )

            # 更新数据库
            for chunk, embedding in zip(batch, embed_response.embeddings):
                await self.db.execute(
                    update(EmbeddingChunk)
                    .where(EmbeddingChunk.id == chunk.id)
                    .values(embedding=embedding)
                )

            total_embedded += len(batch)
            logger.debug(
                "batch_embedded",
                extra={
                    "batch_size": len(batch),
                    "total_embedded": total_embedded,
                    "total_chunks": len(chunks),
                },
            )

        await self.db.commit()

        logger.info(
            "all_pending_chunks_embedded",
            extra={"total_embedded": total_embedded},
        )

        return total_embedded
