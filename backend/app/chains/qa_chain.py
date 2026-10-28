"""LangChain 问答链框架（六阶段，框架文档 5.6）

阶段契约固定：

1. 预处理   追问改写为独立问题（``rewrite_question``）
2. 检索     混合召回 + 强制过滤（``Retriever``，由检索链路实现）
3. 重排判定 重排并判定是否有依据（阈值可配；无依据转办理参考或拒答）
4. 生成     依据片段生成回答（``Generator``，由模型接入实现）
5. 引用核验 核验引用编号 / 条款真实性 / 时效（经 WF-03 标准入口，见 T-WF02-13）
6. 输出     组装统一响应（回答 + 引用 + 风险 + 免责声明）

检索与生成以协议（Protocol）注入，便于开发者B接入真实实现，也便于单测替换。
引用核验与敏感检查（WF-03 / WF-04）经 ``app/chains/workflow_interfaces.py`` 的标准
入口调用，实现可替换而契约不变，便于后续拆分独立工作流。
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Protocol, Sequence

from app.chains.rewrite import LLMCall, rewrite_question
from app.chains.session import QATurn, SessionStore
from app.chains.workflow_interfaces import citation_check, to_citation_input
from app.core.config import settings
from app.rag.verifier import CitationVerifier, RetrievedChunk, has_authoritative_basis
from app.schemas.qa import DEFAULT_DISCLAIMER, REFUSAL_ANSWER, Citation, QAResponse
from app.schemas.wf import CitationCheckRequest

logger = logging.getLogger(__name__)

NO_EVIDENCE_ANSWER = (
    "知识库中未检索到与这个问题直接相关的现行制度原文。"
    "你可以补充文件名称或文号、上传材料后再问，或向组织部门确认具体口径。"
)
ADVISORY_PREFIX = "未检索到可引用的制度依据，以下为办理参考："
#: 办理参考里一旦出现“具体条款/文号”就说明模型在冒充制度原文；这类句子必须移除，
#: 不能靠提示词“请勿编造”兜底。保留普通文件名（如“可学习《党章》”）不拦。
_POLICY_REFERENCE = re.compile(
    r"(?:根据|依据|按照|参照)\s*《[^》]+》"
    r"|《[^》]+》\s*第[一二三四五六七八九十百千0-9]+条"
    r"|第[一二三四五六七八九十百千0-9]+条"
    r"|[〔\[]\d{4}[〕\]]\s*\d+\s*号"
)


class Retriever(Protocol):
    """检索器协议（阶段 2）"""

    async def retrieve(
        self, *, question: str, tenant_id: str, include_expired: bool = False
    ) -> list[RetrievedChunk]: ...


class Generator(Protocol):
    """生成器协议（阶段 4）"""

    async def generate(self, *, question: str, chunks: Sequence[RetrievedChunk]) -> str: ...


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
        supplemental_material: Optional[str] = None,
        advisory_generator: Optional[Generator] = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.verifier = verifier or CitationVerifier()
        self.session = session
        self.llm_call = llm_call
        # 无依据时不直接拒答，而是用独立的办理参考提示词生成通用思路。
        # 独立注入而不是复用 generator，确保“可引用回答”和“无依据办理参考”
        # 不会共用同一套提示词，也不会把无引用内容混进引用核验。
        self.advisory_generator = advisory_generator
        self.no_evidence_threshold = (
            settings.NO_EVIDENCE_THRESHOLD
            if no_evidence_threshold is None
            else no_evidence_threshold
        )
        # 提问人自己上传的材料（已拼成材料块）。它不能替代制度依据，但制度库确实
        # 没有可引片段时，用户要的是"就我这份材料看看怎么办"，此时直接拒答等于
        # 什么都没帮到——改为"仅依据材料作答 + 明示不构成依据"。
        self.supplemental_material = supplemental_material

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
        standalone_question = await rewrite_question(question, history, llm_call=self.llm_call)
        logger.info(
            "qa_stage_rewrite",
            extra={
                "tenant_id": tenant_id,
                "session_id": session_id,
                "original_length": len(question),
                "rewritten_length": len(standalone_question),
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

        # 阶段 3：重排判定（无依据转办理参考或拒答，跳过引用核验）
        from app.core.metrics import RETRIEVAL_SCORE

        top_score = max((c.score or 0 for c in chunks), default=0)
        RETRIEVAL_SCORE.observe(top_score)
        if self._is_no_evidence(chunks):
            logger.info(
                "qa_no_evidence",
                extra={
                    "tenant_id": tenant_id,
                    "top_score": round(top_score, 4),
                    "threshold": self.no_evidence_threshold,
                    "chunk_count": len(chunks),
                    "advisory_enabled": self.advisory_generator is not None,
                },
            )
            if self.supplemental_material:
                return await self._answer_from_material(
                    question=standalone_question,
                    tenant_id=tenant_id,
                    session_id=session_id,
                )
            if self.advisory_generator is not None:
                return await self._answer_advisory(
                    question=standalone_question,
                    tenant_id=tenant_id,
                    session_id=session_id,
                )
            response = QAResponse(
                answer=NO_EVIDENCE_ANSWER,
                citations=[],
                warnings=["未检索到满足依据的片段，已停止生成"],
                disclaimer=DEFAULT_DISCLAIMER,
                refused=True,
            )
            await self._persist(tenant_id, session_id, question, response)
            return response

        # 阶段 4：生成
        try:
            draft = await self.generator.generate(question=standalone_question, chunks=chunks)
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

        # 阶段 5：引用核验（WF-03 标准入口，T-WF02-13）
        verification = citation_check(
            CitationCheckRequest(
                answer=draft,
                citations=[to_citation_input(chunk) for chunk in chunks],
            ),
            verifier=self.verifier,
        )
        logger.info(
            "qa_stage_verify",
            extra={
                "tenant_id": tenant_id,
                "workflow": verification.workflow,
                "workflow_version": verification.version,
                "citation_count": len(verification.citations),
                "warning_count": len(verification.warnings),
                "is_valid": verification.valid,
            },
        )

        # 阶段 6：统一响应组装
        # 依据权威性判定（FR-KB-10 / T-KB-12）：被引来源全部为非权威（参考资料）或
        # 非现行有效（尚未生效 / 已被替代 / 已废止）时，不能作为唯一依据输出。
        cited_chunks = self._cited_chunks(verification.citations, chunks)
        sole_weak_basis = bool(cited_chunks) and not has_authoritative_basis(cited_chunks)
        unsupported = not verification.valid or not verification.citations or sole_weak_basis
        warnings = list(verification.warnings)
        if sole_weak_basis:
            warnings.append("被引来源均非权威或已失效，不能作为依据，已拒答，请核对权威原文")
            logger.info(
                "qa_sole_weak_basis_refused",
                extra={"tenant_id": tenant_id, "citation_count": len(verification.citations)},
            )
        elif unsupported:
            warnings.append("生成内容未通过引用核验，已拒答")
        response = QAResponse(
            answer=REFUSAL_ANSWER if unsupported else verification.answer,
            citations=[] if unsupported else verification.citations,
            warnings=warnings,
            disclaimer=DEFAULT_DISCLAIMER,
            refused=unsupported,
        )
        await self._persist(tenant_id, session_id, question, response)
        return response

    # ---------------------------------------------------------------
    async def _answer_advisory(
        self, *, question: str, tenant_id: str, session_id: Optional[str]
    ) -> QAResponse:
        """制度库没有可引片段、需要给通用办理参考时的作答路径。

        与正常作答的边界：

        1. 不产生引用，也不进入引用核验——没有原文就不能宣称“依据某条”；
        2. 开头固定写明未检索到制度依据，界面据此显示“办理参考”；
        3. 提示词只允许通用工作思路，不允许编造条款、文号、时限或组织结论。
        """
        assert self.advisory_generator is not None
        try:
            draft = await self.advisory_generator.generate(question=question, chunks=[])
        except Exception:
            logger.exception("qa_advisory_generation_failed", extra={"tenant_id": tenant_id})
            raise
        answer = re.sub(r"\s*\[\d+\]", "", draft or "").strip()
        warnings = [
            "未检索到可引用的制度依据：以下内容为办理参考，不构成政策依据；"
            "涉及具体政策口径请以正式文件和组织意见为准。"
        ]
        # 提示词之外的第二道边界：模型仍可能写出“根据《…》第X条”或文号。
        # 按句移除这类内容，保留其余通用思路；整段都被移除时退回固定说明。
        if _POLICY_REFERENCE.search(answer):
            parts = re.split(r"(?<=[。；\n])", answer)
            answer = "".join(
                part for part in parts if not _POLICY_REFERENCE.search(part)
            ).strip()
            warnings.append("办理参考中涉及具体条款或文号的内容已移除，请以正式文件为准。")
        if not answer:
            answer = (
                f"{ADVISORY_PREFIX}\n\n"
                "暂时无法生成具体内容。请补充文件名称、文号或上传材料，"
                "也可向组织部门确认具体口径。"
            )
        elif not answer.startswith("未检索到可引用的制度依据"):
            answer = f"{ADVISORY_PREFIX}\n\n{answer}"
        response = QAResponse(
            answer=answer,
            citations=[],
            warnings=warnings,
            disclaimer=DEFAULT_DISCLAIMER,
            refused=False,
        )
        logger.info(
            "qa_advisory_answer",
            extra={"tenant_id": tenant_id, "answer_length": len(answer)},
        )
        await self._persist(tenant_id, session_id, question, response)
        return response

    async def _answer_from_material(
        self, *, question: str, tenant_id: str, session_id: Optional[str]
    ) -> QAResponse:
        """制度库没有可引片段、但用户上传了材料时的作答路径。

        与正常作答的两点差别必须同时成立，否则就退化成"假装有依据"：

        1. 没有引用：材料是提问人自己给的，不是可核对的制度来源，因此答案里
           不能出现 [n] 编号（模型仍可能照着模板写，这里统一清掉，避免界面上
           出现点了没反应的空角标）；
        2. 回答前明示依据来源：界面据此显示"依据不充分"，不给这条答案盖章。
        """
        try:
            draft = await self.generator.generate(question=question, chunks=[])
        except Exception:
            logger.exception("qa_material_only_generation_failed", extra={"tenant_id": tenant_id})
            raise
        answer = re.sub(r"\s*\[\d+\]", "", draft or "").strip()
        response = QAResponse(
            answer=answer,
            citations=[],
            warnings=[
                "制度库未检索到可引用的片段：以下内容仅依据你上传的材料整理，"
                "不作为制度依据，请以正式文件与组织意见为准。"
            ],
            disclaimer=DEFAULT_DISCLAIMER,
            refused=False,
        )
        logger.info(
            "qa_material_only_answer",
            extra={"tenant_id": tenant_id, "answer_length": len(answer)},
        )
        await self._persist(tenant_id, session_id, question, response)
        return response

    @staticmethod
    def _cited_chunks(
        citations: Sequence[Citation], chunks: Sequence[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """取回被引用到的片段（优先按片段主键匹配，退化为按引用编号匹配）"""
        cited_ids = {c.chunk_id for c in citations if c.chunk_id}
        if cited_ids:
            matched = [c for c in chunks if c.chunk_id in cited_ids]
            if matched:
                return matched
        indices = {c.index for c in citations}
        return [c for c in chunks if c.index in indices]

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
        summaries = SessionStore.summarize_citations([c.model_dump() for c in response.citations])
        try:
            await self.session.append_turn(
                tenant_id,
                session_id,
                QATurn.create(question=question, answer=response.answer, citations=summaries),
            )
        except Exception:
            logger.exception("qa_session_persistence_failed")
            response.warnings.append("本次会话历史未能保存，请稍后重试")
