"""知识文档切分策略

对应框架文档 5.3：

- 优先"章—条"结构切分，保持条款完整；
- 单条超长时按中文标点层级二次切分，并保留重叠区；
- 片段携带条款编号（引用核验依据）与顺序；
- 可配置：片段长度上限、重叠长度、是否启用二次切分。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# 中文数字（含阿拉伯数字）
_CN_NUM = "一二三四五六七八九十百千零两〇0-9"
_ARTICLE_RE = re.compile(rf"第\s*[{_CN_NUM}]+\s*条")
_CHAPTER_RE = re.compile(rf"第\s*[{_CN_NUM}]+\s*章")
# 中文句末标点，用于超长二次切分
_SENTENCE_END = "。！？；"


@dataclass
class TextChunk:
    """切分片段"""
    content: str
    sequence: int
    article: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChapterArticleSplitter:
    """按章—条结构切分的策略"""

    def __init__(
        self,
        max_chunk_size: int = 800,
        overlap: int = 100,
        enable_secondary_split: bool = True,
    ) -> None:
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size 必须为正数")
        if overlap < 0 or overlap >= max_chunk_size:
            raise ValueError("overlap 必须满足 0 <= overlap < max_chunk_size")
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.enable_secondary_split = enable_secondary_split

    def split(self, text: str) -> list[TextChunk]:
        """切分文本为片段列表"""
        if not text or not text.strip():
            return []

        chunks: list[TextChunk] = []
        sequence = 0
        for label, block in self._split_blocks(text):
            block = block.strip()
            if not block:
                continue
            if self.enable_secondary_split and len(block) > self.max_chunk_size:
                parts = self._secondary_split(block)
                for index, part in enumerate(parts):
                    article = None
                    if label:
                        article = label if index == 0 else f"{label}-{index + 1}"
                    chunks.append(TextChunk(content=part, sequence=sequence, article=article))
                    sequence += 1
            else:
                chunks.append(TextChunk(content=block, sequence=sequence, article=label))
                sequence += 1
        return chunks

    # ---------------------------------------------------------------
    def _split_blocks(self, text: str) -> list[tuple[Optional[str], str]]:
        """按"条"（优先）或"章"切块；无结构时整体返回"""
        matches = list(_ARTICLE_RE.finditer(text))
        if not matches:
            matches = list(_CHAPTER_RE.finditer(text))
        if not matches:
            return [(None, text)]

        blocks: list[tuple[Optional[str], str]] = []
        preface = text[: matches[0].start()].strip()
        if preface:
            blocks.append((None, preface))

        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            blocks.append((match.group(0).strip(), text[start:end].strip()))
        return blocks

    def _secondary_split(self, content: str) -> list[str]:
        """按中文句末标点二次切分，保留重叠区"""
        units = [u for u in re.split(rf"(?<=[{_SENTENCE_END}])", content) if u]
        if not units:
            return [content]

        # 先对超长单元做硬切分
        normalized: list[str] = []
        step = max(1, self.max_chunk_size - self.overlap)
        for unit in units:
            if len(unit) <= self.max_chunk_size:
                normalized.append(unit)
            else:
                for i in range(0, len(unit), step):
                    normalized.append(unit[i : i + self.max_chunk_size])

        # 贪心合并
        parts: list[str] = []
        current = ""
        for unit in normalized:
            if not current:
                current = unit
            elif len(current) + len(unit) <= self.max_chunk_size:
                current += unit
            else:
                parts.append(current)
                if self.overlap:
                    allow = max(0, self.max_chunk_size - len(unit))
                    overlap_text = current[-min(self.overlap, allow):] if allow else ""
                    current = overlap_text + unit
                else:
                    current = unit
        if current:
            parts.append(current)
        return parts
