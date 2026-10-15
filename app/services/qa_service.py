"""兼容旧问答入口，使用正式六阶段问答链与同一资料/出网权限。"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel
from app.models.user import UserRole
from app.rag.rag_service import RAGService
from app.schemas.qa import Citation, QAResponse
from app.services.retrieval_service import authorized_filters


class QAService:
    async def answer(
        self,
        db: AsyncSession,
        question: str,
        tenant_id: str,
        data_level: DataLevel,
        user_role: UserRole | None = None,
        session_id: str | None = None,
    ) -> QAResponse:
        filters = await authorized_filters(db, tenant_id)
        response = await RAGService(db, data_level=data_level).ask(question, filters=filters)
        return QAResponse(
            answer=response.answer,
            refused=response.refused,
            warnings=response.warnings,
            disclaimer=response.disclaimer,
            citations=[
                Citation(
                    index=row.index,
                    doc_id=row.doc_id,
                    doc_name=row.title,
                    content=row.content,
                    article=row.article,
                    doc_number=row.doc_number,
                    issuer=row.issuer,
                    effective_date=row.effective_date,
                    expiration_date=row.expiration_date,
                    file_name=row.file_name,
                    visibility=row.visibility,
                    level=row.level,
                    security_level=row.security_level,
                    chunk_id=row.chunk_id,
                    score=row.score,
                    authority=row.authority,
                    validity=row.validity,
                )
                for row in response.citations
            ],
        )


@lru_cache
def get_qa_service() -> QAService:
    return QAService()
