"""知识文档解析器与注册机制

对应框架文档 5.2.2："文件解析器按格式注册，新增格式只需注册解析器，不改动入库流程"。

用法::

    registry = build_default_registry()
    parsed = registry.parse(data, file_name="a.pdf")
    parsed.text  # 抽取出的纯文本
"""
from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """不支持的文件格式"""


class ParseError(Exception):
    """文件解析失败"""


@dataclass
class ParsedDocument:
    """解析结果"""
    text: str
    file_name: str = ""
    page_count: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentParser(ABC):
    """文档解析器基类"""
    name: str = "base"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, data: bytes, *, file_name: str = "") -> ParsedDocument:
        """解析文件字节流"""
        raise NotImplementedError


class PlainTextParser(DocumentParser):
    """纯文本解析器（.txt / .md）"""
    name = "plain_text"
    extensions = (".txt", ".md")

    def parse(self, data: bytes, *, file_name: str = "") -> ParsedDocument:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # 兼容 GBK 编码的中文文本
            text = data.decode("gbk", errors="ignore")
        return ParsedDocument(text=text, file_name=file_name)


class PdfParser(DocumentParser):
    """PDF 解析器（基础版，基于 pypdf）"""
    name = "pdf"
    extensions = (".pdf",)

    def parse(self, data: bytes, *, file_name: str = "") -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise ParseError("未安装 pypdf，无法解析 PDF") from exc

        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise ParseError(f"PDF 解析失败: {exc}") from exc

        return ParsedDocument(
            text="\n".join(pages), file_name=file_name, page_count=len(pages)
        )


class DocxParser(DocumentParser):
    """Word 解析器（.docx，基于 python-docx）"""
    name = "docx"
    extensions = (".docx",)

    def parse(self, data: bytes, *, file_name: str = "") -> ParsedDocument:
        try:
            import docx
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise ParseError("未安装 python-docx，无法解析 DOCX") from exc

        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(f"DOCX 解析失败: {exc}") from exc

        text = "\n".join(p.text for p in document.paragraphs)
        return ParsedDocument(text=text, file_name=file_name)


class ParserRegistry:
    """解析器注册表（按扩展名路由）"""

    def __init__(self) -> None:
        self._by_extension: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        """注册解析器"""
        for ext in parser.extensions:
            self._by_extension[ext.lower()] = parser

    def get(self, file_name: str) -> DocumentParser:
        """按文件名获取解析器"""
        ext = Path(file_name).suffix.lower()
        parser = self._by_extension.get(ext)
        if parser is None:
            raise UnsupportedFormatError(f"不支持的文件格式: {ext or '(无扩展名)'}")
        return parser

    def parse(self, data: bytes, *, file_name: str) -> ParsedDocument:
        """解析文件（自动选择解析器）"""
        return self.get(file_name).parse(data, file_name=file_name)

    @property
    def supported_extensions(self) -> list[str]:
        """已注册的扩展名"""
        return sorted(self._by_extension)


def build_default_registry() -> ParserRegistry:
    """构建默认注册表（txt/md、pdf、docx）"""
    registry = ParserRegistry()
    for parser in (PlainTextParser(), PdfParser(), DocxParser()):
        registry.register(parser)
    return registry


# 全局默认注册表
default_registry = build_default_registry()
