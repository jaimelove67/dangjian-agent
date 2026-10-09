"""引用核验模块

对应框架文档 5.7，核验项：

- 引用编号有效性：编号是否落在检索片段范围内 → 无效编号移除并记风险；
- 条款真实性：答案提及的条款号是否存在于被引片段 → 不存在则记风险；
- 文件时效：被引文件是否已废止 / 失效 / 即将失效 → 给出提示；
- 引用完整性：长回答是否标注来源 → 未标注则记风险；
- 无依据长回答：无引用却给出实质内容 → 标记风险。

本模块为纯逻辑，不依赖数据库 / 模型，便于单元测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from app.schemas.qa import Citation

_CITATION_RE = re.compile(r"\[(\d+)\]")
_ARTICLE_RE = re.compile(r"第\s*[一二三四五六七八九十百千零两〇0-9]+\s*条")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]")

DEFAULT_LONG_ANSWER_THRESHOLD = 80   # 超过该长度视为“长回答”
DEFAULT_EXPIRING_DAYS = 30           # 距失效多少天提示“即将失效”

_STATUS_CN = {"abolished": "已废止", "expired": "已失效", "effective": "有效"}


@dataclass
class RetrievedChunk:
    """检索片段（引用核验输入，由检索链路产出）"""
    index: int
    doc_id: str
    doc_name: str
    content: str
    article: Optional[str] = None
    doc_number: Optional[str] = None
    issuer: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    status: str = "effective"
    score: Optional[float] = None


@dataclass
class VerificationResult:
    """核验结果"""
    answer: str
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


class CitationVerifier:
    """引用核验器"""

    def __init__(
        self,
        *,
        today: Optional[date] = None,
        long_answer_threshold: int = DEFAULT_LONG_ANSWER_THRESHOLD,
        expiring_days: int = DEFAULT_EXPIRING_DAYS,
    ) -> None:
        self.today = today or date.today()
        self.long_answer_threshold = long_answer_threshold
        self.expiring_days = expiring_days

    def verify(
        self, answer: str, chunks: Sequence[RetrievedChunk]
    ) -> VerificationResult:
        """核验答案并产出清洗后的答案、引用列表与风险提示"""
        answer = answer or ""
        by_index = {chunk.index: chunk for chunk in chunks}
        referenced = self._extract_indices(answer)

        invalid = [idx for idx in referenced if idx not in by_index]
        valid_indices = [idx for idx in referenced if idx in by_index]
        warnings: list[str] = []
        for idx in invalid:
            warnings.append(f"引用[{idx}]不存在，已从答案中移除")

        # 清洗无效编号
        cleaned = answer
        for idx in invalid:
            cleaned = cleaned.replace(f"[{idx}]", "")
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        # 逐条核验（条款真实性 + 文件时效）
        for idx in valid_indices:
            chunk = by_index[idx]
            self._check_article(cleaned, idx, chunk, warnings)
            self._check_timeliness(chunk, warnings)

        # 引用完整性 / 无依据长回答
        if not referenced and len(cleaned.strip()) >= self.long_answer_threshold:
            warnings.append("长回答未标注任何来源，请谨慎采信")

        citations = [self._to_citation(by_index[idx]) for idx in valid_indices]
        return VerificationResult(
            answer=cleaned,
            citations=citations,
            warnings=self._dedup(warnings),
            valid=not invalid,
        )

    # ---------------------------------------------------------------
    @staticmethod
    def _extract_indices(answer: str) -> list[int]:
        """按出现顺序提取引用编号（去重）"""
        seen: list[int] = []
        for raw in _CITATION_RE.findall(answer):
            idx = int(raw)
            if idx not in seen:
                seen.append(idx)
        return seen

    def _check_article(
        self, answer: str, idx: int, chunk: RetrievedChunk, warnings: list[str]
    ) -> None:
        """条款真实性：包含 [idx] 的句子中提及的“第 X 条”须存在于被引片段"""
        for sentence in _SENTENCE_SPLIT_RE.split(answer):
            if f"[{idx}]" not in sentence:
                continue
            for article in _ARTICLE_RE.findall(sentence):
                normalized = article.replace(" ", "")
                if normalized not in chunk.content and (chunk.article or "") != normalized:
                    warnings.append(
                        f"引用[{idx}]提及的条款“{normalized}”在被引片段中不存在，请人工复核"
                    )

    def _check_timeliness(self, chunk: RetrievedChunk, warnings: list[str]) -> None:
        """文件时效检查"""
        if chunk.status in ("abolished", "expired"):
            label = _STATUS_CN.get(chunk.status, chunk.status)
            warnings.append(f"引用文件《{chunk.doc_name}》{label}，请注意时效")
            return
        if chunk.expiration_date is not None:
            if chunk.expiration_date < self.today:
                warnings.append(
                    f"引用文件《{chunk.doc_name}》已于 {chunk.expiration_date} 失效"
                )
            elif chunk.expiration_date <= self.today + timedelta(days=self.expiring_days):
                warnings.append(
                    f"引用文件《{chunk.doc_name}》即将于 {chunk.expiration_date} 失效"
                )

    @staticmethod
    def _to_citation(chunk: RetrievedChunk) -> Citation:
        return Citation(
            index=chunk.index,
            doc_id=chunk.doc_id,
            doc_name=chunk.doc_name,
            content=chunk.content,
            article=chunk.article,
            doc_number=chunk.doc_number,
            issuer=chunk.issuer,
            effective_date=chunk.effective_date,
        )

    @staticmethod
    def _dedup(items: list[str]) -> list[str]:
        seen: list[str] = []
        for item in items:
            if item not in seen:
                seen.append(item)
        return seen
