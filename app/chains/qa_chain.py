"""LangChain 问答链框架（六阶段，框架文档 5.6）

阶段契约固定：

1. 预处理   追问改写为独立问题（``rewrite_question``）
2. 检索     混合召回 + 强制过滤（``Retriever``，由检索链路实现）
3. 重排判定 重排并判定是否有依据（阈值可配；无依据直接拒答）
4. 生成     依据片段生成回答（``Generator``，由模型接入实现）
5. 引用核验 核验引用编号 / 条款真实性 / 时效（``CitationVerifier``）
6. 输出     组装统一响应（回答 + 引用 + 风险 + 免责声明）

检索与生成以协议（Protocol）注入，便于开发者B接入真实实现，也便于单测替换。
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, Sequence

from app.chains.rewrite import LLMCall, rewrite_question
from app.chains.session import QATurn, SessionStore
from app.core.config import settings
from app.rag.verifier import CitationVerifier, RetrievedChunk, VerificationResult
from app.schemas.qa import DEFAULT_DISCLAIMER, REFUSAL_ANSWER, QAResponse

logger = logging.getLogger(__name__)


class Retriever(Protocol):
    """检索器协议（阶段 2）"""
    async def retrieve(
        self, *, question: str, tenant_id: str, include_expired: bool = False
    ) -> list[RetrievedChunk]: ...


class Generator(Protocol):
    """生成器协议（阶段 4）"""
    async def generate(
        self, *, question: str, chunks: Sequence[RetrievedChunk]
    ) -> str: ...


class QAChain:
    """六阶段问答链"""

    def __init__(
        self,
        *,
        retriever: Retriever,
        generator: Generator,
        verifier: Optional[CitationVerifier] = None,
        session: Optional[SessionStore] = None,
        llm_call: Optional[LLMCall] = None,
        no_evidence_threshold: Optional[float] = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.verifier = verifier or CitationVerifier()
        self.session = session
        self.llm_call = llm_call
        self.no_evidence_threshold = (
            settings.NO_EVIDENCE_THRESHOLD
            if no_evidence_threshold is None
            else no_evidence_threshold
        )

    async def ask(
        self,
        *,
        question: str,
        tenant_id: str,
        session_id: Optional[str] = None,
        include_expired: bool = False,
    ) -> QAResponse:
        """执行六阶段问答链"""
        # 阶段 1：预处理（追问改写）
        history = []
        if self.session and session_id:
            history = await self.session.get_history(tenant_id, session_id)
        standalone_question = await rewrite_question(
            question, history, llm_call=self.llm_call
        )
        logger.info(
            "qa_stage_rewrite",
            extra={
                "tenant_id": tenant_id,
                "session_id": session_id,
                "original_question": question,
                "rewritten_question": standalone_question,
            },
        )

        # 阶段 2：检索
        try:
            chunks = await self.retriever.retrieve(
                question=standalone_question,
                tenant_id=tenant_id,
                include_expired=include_expired,
            )
            logger.info(
                "qa_stage_retrieve",
                extra={
                    "tenant_id": tenant_id,
                    "chunk_count": len(chunks),
                    "has_scores": any(c.score is not None for c in chunks),
                },
            )
        except Exception as e:
            logger.exception(
                "qa_retrieval_failed",
                extra={"tenant_id": tenant_id, "error": str(e)},
            )
            raise

        # 阶段 3：重排判定（无依据则直接拒答，跳过生成）
        if self._is_no_evidence(chunks):
            response = QAResponse(
                answer=REFUSAL_ANSWER,
                citations=[],
                warnings=["未检索到满足依据的片段，已拒答"],
                disclaimer=DEFAULT_DISCLAIMER,
                refused=True,
            )
            await self._persist(tenant_id, session_id, question, response)
            return response

        # 阶段 4：生成
        try:
            draft = await self.generator.generate(
                question=standalone_question, chunks=chunks
            )
            logger.info(
                "qa_stage_generate",
                extra={
                    "tenant_id": tenant_id,
                    "draft_length": len(draft),
                    "chunk_count": len(chunks),
                },
            )
        except Exception as e:
            logger.exception(
                "qa_generation_failed",
                extra={"tenant_id": tenant_id, "error": str(e)},
            )
            raise

        # 阶段 5：引用核验
        verification: VerificationResult = self.verifier.verify(draft, chunks)
        logger.info(
            "qa_stage_verify",
            extra={
                "tenant_id": tenant_id,
                "citation_count": len(verification.citations),
                "warning_count": len(verification.warnings),
                "is_valid": verification.valid,
            },
        )

        # 阶段 6：统一响应组装
        response = QAResponse(
            answer=verification.answer,
            citations=verification.citations,
            warnings=verification.warnings,
            disclaimer=DEFAULT_DISCLAIMER,
            refused=False,
        )
        await self._persist(tenant_id, session_id, question, response)
        return response

    # ---------------------------------------------------------------
    def _is_no_evidence(self, chunks: Sequence[RetrievedChunk]) -> bool:
        """无依据判定：无片段，或全部带分数且最高分低于阈值"""
        if not chunks:
            return True
        scores = [c.score for c in chunks if c.score is not None]
        if scores and len(scores) == len(chunks):
            return max(scores) < self.no_evidence_threshold
        return False

    async def _persist(
        self, tenant_id: str, session_id: Optional[str], question: str, response: QAResponse
    ) -> None:
        """写入会话（仅问答与引用摘要）"""
        if not (self.session and session_id):
            return
        summaries = SessionStore.summarize_citations(
            [c.model_dump() for c in response.citations]
        )
        await self.session.append_turn(
            tenant_id,
            session_id,
            QATurn.create(question=question, answer=response.answer, citations=summaries),
        )
