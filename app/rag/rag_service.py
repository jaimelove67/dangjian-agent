"""RAG 问答服务

提供完整的检索增强生成（RAG）流程：
1. 检索相关文档片段（混合检索）
2. 构建提示词
3. 调用 LLM 生成答案
4. 引用核验
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel, TaskType
from app.llm.service import get_model_service
from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.verifier import CitationVerifier, RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """引用"""

    # 文档标题
    title: str

    # 发文单位
    issuer: str

    # 文号
    doc_number: Optional[str] = None

    # 条款编号
    article: Optional[str] = None

    # 引用内容
    content: str = ""

    # 相关度分数
    score: float = 0.0


@dataclass
class RAGResponse:
    """RAG 问答响应"""

    # 生成的答案
    answer: str

    # 引用列表
    citations: list[Citation]

    # 检索到的片段数量
    retrieved_count: int

    # 使用的片段数量
    used_count: int

    # 是否有足够的依据
    has_sufficient_evidence: bool

    # 元数据
    metadata: dict[str, Any]

    # 引用核验风险提示
    warnings: list[str] = field(default_factory=list)


class RAGService:
    """RAG 问答服务"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        data_level: DataLevel = DataLevel.PUBLIC,
        retrieval_top_k: int = 10,
        context_top_k: int = 5,
        use_reranker: bool = True,
    ) -> None:
        """
        Args:
            db: 数据库会话
            data_level: 数据级别
            retrieval_top_k: 检索返回结果数量
            context_top_k: 用于构建上下文的片段数量
            use_reranker: 是否使用重排模型
        """
        self.db = db
        self.data_level = data_level
        self.retrieval_top_k = retrieval_top_k
        self.context_top_k = context_top_k

        self.retriever = HybridRetriever(
            db, data_level=data_level, use_reranker=use_reranker
        )
        self._model_service = get_model_service()
        self.verifier = CitationVerifier()

    async def ask(
        self,
        question: str,
        *,
        filters: Optional[dict[str, Any]] = None,
        temperature: float = 0.3,
    ) -> RAGResponse:
        """问答

        Args:
            question: 用户问题
            filters: 检索过滤条件
            temperature: LLM 温度参数（越低越保守）

        Returns:
            RAG 响应
        """
        if not question.strip():
            return RAGResponse(
                answer="请输入您的问题。",
                citations=[],
                retrieved_count=0,
                used_count=0,
                has_sufficient_evidence=False,
                metadata={"error": "empty_question"},
            )

        # 1. 检索相关文档片段
        retrieved_results = await self.retriever.retrieve(
            question,
            top_k=self.retrieval_top_k,
            filters=filters,
        )

        logger.debug(
            "retrieval_completed",
            extra={
                "question": question[:50],
                "retrieved_count": len(retrieved_results),
            },
        )

        # 2. 检查是否有足够的依据
        if not retrieved_results:
            return RAGResponse(
                answer="抱歉，我在知识库中没有找到相关信息来回答您的问题。",
                citations=[],
                retrieved_count=0,
                used_count=0,
                has_sufficient_evidence=False,
                metadata={"reason": "no_retrieval_results"},
            )

        # 3. 选取 top-k 片段构建上下文
        context_results = retrieved_results[: self.context_top_k]

        # 4. 构建提示词
        prompt = self._build_prompt(question, context_results)

        # 5. 调用 LLM 生成答案
        try:
            llm_response = await self._model_service.generate(
                prompt=prompt,
                data_level=self.data_level,
                task_type=TaskType.QA,
                temperature=temperature,
            )
            answer = llm_response.content
        except Exception as exc:
            logger.error(
                "llm_generation_failed",
                extra={"question": question[:50], "error": str(exc)},
            )
            return RAGResponse(
                answer="抱歉，生成答案时出现错误，请稍后重试。",
                citations=[],
                retrieved_count=len(retrieved_results),
                used_count=0,
                has_sufficient_evidence=False,
                metadata={"error": str(exc)},
            )

        # 6. 引用核验：清洗无效引用，逐条核验条款真伪与文件时效，产出风险提示
        chunks = [
            RetrievedChunk(
                index=i + 1,
                doc_id=r.doc_id,
                doc_name=r.metadata.get("title", "未知文档"),
                content=r.content,
                article=r.article,
                doc_number=r.metadata.get("doc_number"),
                issuer=r.metadata.get("issuer"),
                effective_date=r.effective_date,
                expiration_date=r.expiration_date,
                status=r.doc_status or "effective",
                score=r.score,
            )
            for i, r in enumerate(context_results)
        ]
        verification = self.verifier.verify(answer, chunks)

        # 用核验后的答案与引用（无效编号已清洗）
        answer = verification.answer
        citations = [
            Citation(
                title=c.doc_name,
                issuer=c.issuer or "",
                doc_number=c.doc_number,
                article=c.article,
                content=(c.content[:200] + "..." if len(c.content) > 200 else c.content),
                score=chunks[c.index - 1].score,
            )
            for c in verification.citations
        ]
        warnings = verification.warnings

        # 7. 判断是否有足够依据（引用编号无效时不下"依据充分"结论）
        has_sufficient_evidence = self._check_evidence_sufficiency(
            answer, context_results
        )
        if not verification.valid:
            has_sufficient_evidence = False

        logger.info(
            "rag_answer_generated",
            extra={
                "question": question[:50],
                "retrieved_count": len(retrieved_results),
                "used_count": len(context_results),
                "citations_count": len(citations),
                "warnings_count": len(warnings),
                "has_sufficient_evidence": has_sufficient_evidence,
            },
        )

        return RAGResponse(
            answer=answer,
            citations=citations,
            retrieved_count=len(retrieved_results),
            used_count=len(context_results),
            has_sufficient_evidence=has_sufficient_evidence,
            warnings=warnings,
            metadata={
                "retrieval_method": context_results[0].metadata.get("retrieval_method")
                if context_results
                else None,
                "avg_score": sum(r.score for r in context_results) / len(context_results)
                if context_results
                else 0.0,
            },
        )

    def _build_prompt(
        self, question: str, context_results: list[RetrievalResult]
    ) -> str:
        """构建 RAG 提示词

        Args:
            question: 用户问题
            context_results: 检索到的上下文片段

        Returns:
            完整的提示词
        """
        # 构建上下文
        context_parts = []
        for idx, result in enumerate(context_results, start=1):
            title = result.metadata.get("title", "未知文档")
            issuer = result.metadata.get("issuer", "")
            doc_number = result.metadata.get("doc_number", "")
            article = result.article or ""

            # 文档信息
            doc_info = f"【文档{idx}】{title}"
            if issuer:
                doc_info += f" - {issuer}"
            if doc_number:
                doc_info += f"（{doc_number}）"
            if article:
                doc_info += f" {article}"

            context_parts.append(f"{doc_info}\n{result.content}")

        context = "\n\n".join(context_parts)

        # 构建提示词
        prompt = f"""你是一个党建工作智能助手，负责根据提供的知识库内容回答用户问题。

【重要原则】
1. 只根据下面提供的参考资料回答问题，不要编造或推测
2. 如果参考资料中没有相关信息，请明确说明"根据现有资料无法回答"
3. 凡引用参考资料之处，必须在相应句末用方括号数字角标标注来源，例如 [1]、[2]；角标编号必须对应【文档N】中的 N，且每个结论性表述都要有角标，不得省略
4. 保持回答准确、简洁、专业

【参考资料】
{context}

【用户问题】
{question}

【回答】
"""

        return prompt

    def _build_citations(
        self, results: list[RetrievalResult]
    ) -> list[Citation]:
        """构建引用列表

        Args:
            results: 检索结果列表

        Returns:
            引用列表
        """
        citations = []
        for result in results:
            citation = Citation(
                title=result.metadata.get("title", "未知文档"),
                issuer=result.metadata.get("issuer", ""),
                doc_number=result.metadata.get("doc_number"),
                article=result.article,
                content=result.content[:200] + "..." if len(result.content) > 200 else result.content,
                score=result.score,
            )
            citations.append(citation)
        return citations

    def _check_evidence_sufficiency(
        self, answer: str, context_results: list[RetrievalResult]
    ) -> bool:
        """判断是否有足够的依据

        依据充分性采用"重排分优先、降级按引用判定"的分流策略：
        - 重排生效（结果带 ``rerank_score``，0-1 相关度）→ 沿用 0.5 强相关阈值；
        - 重排失败降级（RRF/融合分，数量级 ~0.01，是排名权重而非相关度）
          → 不适用绝对阈值，改为"有检索结果 + 回答非拒答"即视为有依据，
          与界面「命中片段 / 实际引用」明细保持一致，避免把有效回答误报为无依据。

        Args:
            answer: 生成的答案
            context_results: 上下文片段

        Returns:
            是否有足够依据
        """
        if not context_results:
            return False

        # 检查答案是否为拒答
        refuse_keywords = ["无法回答", "没有找到", "没有相关信息", "不清楚", "不知道"]
        if any(keyword in answer for keyword in refuse_keywords):
            return False

        # 重排分存在时（0-1 相关度），沿用 0.5 强相关阈值
        rerank_scores = [
            r.metadata["rerank_score"]
            for r in context_results
            if isinstance(r.metadata.get("rerank_score"), (int, float))
        ]
        if rerank_scores:
            return any(s >= 0.5 for s in rerank_scores)

        # 降级路径（重排不可用，RRF/融合分）：有检索结果且回答未拒答，即认定引用成立
        return True
