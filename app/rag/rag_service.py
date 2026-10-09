"""RAG 问答服务

提供完整的检索增强生成（RAG）流程：
1. 检索相关文档片段（混合检索）
2. 构建提示词
3. 调用 LLM 生成答案
4. 引用核验
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import DataLevel, TaskType
from app.llm.service import get_model_service
from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever

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

        # 6. 构建引用列表
        citations = self._build_citations(context_results)

        # 7. 判断是否有足够依据
        has_sufficient_evidence = self._check_evidence_sufficiency(
            answer, context_results
        )

        logger.info(
            "rag_answer_generated",
            extra={
                "question": question[:50],
                "retrieved_count": len(retrieved_results),
                "used_count": len(context_results),
                "citations_count": len(citations),
                "has_sufficient_evidence": has_sufficient_evidence,
            },
        )

        return RAGResponse(
            answer=answer,
            citations=citations,
            retrieved_count=len(retrieved_results),
            used_count=len(context_results),
            has_sufficient_evidence=has_sufficient_evidence,
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
3. 回答时要引用具体的文档和条款
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

        简单启发式规则：
        1. 有检索结果
        2. 答案不是拒答（不包含"无法回答"、"没有找到"等）
        3. 至少一个片段的相关度 >= 0.5

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

        # 检查是否有高相关度片段
        has_high_relevance = any(r.score >= 0.5 for r in context_results)

        return has_high_relevance
