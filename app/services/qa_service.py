"""问答服务

整合检索、生成、核验的完整问答流程。
"""
from typing import Optional, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.services.retrieval_service import get_retrieval_service
from app.llm.service import get_model_service
from app.llm.base import DataLevel, TaskType
from app.schemas.qa import QAResponse, Citation
from app.schemas.retrieval import RetrievalResult
from app.rag.verifier import CitationVerifier
from app.core.config import settings
from app.models.user import UserRole

logger = structlog.get_logger(__name__)


class QAService:
    """问答服务

    完整流程：检索 → 无依据判定 → 生成 → 引用核验 → 返回
    """

    def __init__(self):
        """初始化问答服务"""
        self.retrieval_service = get_retrieval_service()
        self.model_service = get_model_service()
        self.verifier = CitationVerifier()

    async def answer(
        self,
        db: AsyncSession,
        question: str,
        tenant_id: str,
        data_level: DataLevel,
        user_role: Optional[UserRole] = None,
        session_id: Optional[str] = None,
    ) -> QAResponse:
        """回答问题

        Args:
            db: 数据库会话
            question: 问题文本
            tenant_id: 租户ID
            data_level: 数据级别
            user_role: 用户角色
            session_id: 会话ID（用于多轮对话）

        Returns:
            问答响应
        """
        # 1. 检索相关文档
        retrieval_response = await self.retrieval_service.retrieve(
            db=db,
            query=question,
            tenant_id=tenant_id,
            data_level=data_level,
            user_role=user_role,
            use_rerank=True,
        )

        # 2. 无依据判定
        if not retrieval_response.has_evidence:
            logger.info(
                "qa_no_evidence",
                question_length=len(question),
                tenant_id=tenant_id,
                results_count=len(retrieval_response.results),
            )
            return QAResponse(
                answer="抱歉，我无法根据现有知识库回答这个问题。知识库中可能没有相关内容，或相关度过低。",
                citations=[],
                has_evidence=False,
                warnings=[],
                disclaimer="本回答基于知识库内容生成，仅供参考。",
            )

        # 3. 构建提示词
        context_text = self._build_context(retrieval_response.results)
        prompt = self._build_prompt(question=question, context=context_text)

        # 4. 调用LLM生成答案
        try:
            model_response = await self.model_service.generate(
                prompt=prompt,
                data_level=data_level,
                task_type=TaskType.QA,
                context={"tenant_id": tenant_id, "action": "qa"},
            )
            answer_text = model_response.content
        except Exception as e:
            logger.error(
                "qa_generation_failed",
                error=str(e),
                question_length=len(question),
            )
            return QAResponse(
                answer="抱歉，生成答案时出现错误，请稍后重试。",
                citations=[],
                has_evidence=True,
                warnings=["生成失败"],
                disclaimer="本回答基于知识库内容生成，仅供参考。",
            )

        # 5. 提取引用
        citations = self._extract_citations(retrieval_response.results)

        # 6. 引用核验（可选，取决于是否有引用）
        warnings = []
        if citations:
            verification_result = await self.verifier.verify_citations(
                db=db,
                answer=answer_text,
                citations=citations,
            )
            warnings = verification_result.get("warnings", [])

        logger.info(
            "qa_completed",
            question_length=len(question),
            answer_length=len(answer_text),
            citations_count=len(citations),
            warnings_count=len(warnings),
            tenant_id=tenant_id,
        )

        return QAResponse(
            answer=answer_text,
            citations=citations,
            has_evidence=True,
            warnings=warnings,
            disclaimer="本回答基于知识库内容生成，仅供参考。具体执行请以最新正式文件为准。",
        )

    def _build_context(self, results: list[RetrievalResult]) -> str:
        """构建上下文文本

        Args:
            results: 检索结果列表

        Returns:
            格式化的上下文文本
        """
        context_parts = []
        for idx, result in enumerate(results, 1):
            # 格式：[序号] 文档标题 (文号)
            # 条款：第X条
            # 内容：...
            doc_info = f"{result.doc_title}"
            if result.doc_number:
                doc_info += f" ({result.doc_number})"

            article_info = f"，{result.article}" if result.article else ""

            context_parts.append(
                f"[{idx}] {doc_info}{article_info}\n{result.content}\n"
            )

        return "\n".join(context_parts)

    def _build_prompt(self, question: str, context: str) -> str:
        """构建问答提示词

        Args:
            question: 问题
            context: 上下文

        Returns:
            完整提示词
        """
        prompt = f"""你是一个党建工作智能助手。请根据以下知识库内容回答用户问题。

## 知识库内容
{context}

## 用户问题
{question}

## 回答要求
1. 严格基于知识库内容回答，不要编造信息
2. 如果知识库内容不足以回答问题，请明确说明
3. 引用具体文档时，注明文档标题和条款编号
4. 语言简洁专业，结构清晰
5. 如有多个相关规定，请分条列出

请回答："""
        return prompt

    def _extract_citations(self, results: list[RetrievalResult]) -> list[Citation]:
        """从检索结果提取引用

        Args:
            results: 检索结果列表

        Returns:
            引用列表
        """
        citations = []
        for idx, result in enumerate(results, 1):
            citations.append(
                Citation(
                    doc_id=result.doc_id,
                    doc_title=result.doc_title or "未知文档",
                    doc_number=result.doc_number,
                    article=result.article,
                    excerpt=result.content[:200] + "..." if len(result.content) > 200 else result.content,
                    relevance_score=result.score,
                )
            )
        return citations


# 全局问答服务实例
_qa_service: Optional[QAService] = None


def get_qa_service() -> QAService:
    """获取问答服务单例

    Returns:
        问答服务实例
    """
    global _qa_service
    if _qa_service is None:
        _qa_service = QAService()
    return _qa_service
