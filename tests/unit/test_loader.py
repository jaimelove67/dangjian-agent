"""文档解析器与注册机制测试（框架文档 5.2.2）"""
import io

import pytest

from app.rag.exceptions import ParseError, UnsupportedFormatError
from app.rag.loader import (
    ParsedDocument,
    PdfParser,
    PlainTextParser,
    ParserRegistry,
    build_default_registry,
)


class TestRegistry:
    def test_default_registry_extensions(self):
        registry = build_default_registry()
        assert {".txt", ".md", ".pdf", ".docx"} <= set(registry.supported_extensions)

    def test_parse_text_file(self):
        registry = build_default_registry()
        parsed = registry.parse("第一条 内容".encode("utf-8"), file_name="doc.md")
        assert "第一条" in parsed.text

    def test_unsupported_format_raises(self):
        registry = build_default_registry()
        with pytest.raises(UnsupportedFormatError):
            registry.parse(b"x", file_name="a.xyz")

    def test_custom_parser_registration(self):
        class DummyParser:
            name = "dummy"
            extensions = (".foo",)

            def parse(self, data: bytes, *, file_name: str = "") -> ParsedDocument:
                return ParsedDocument(text="FOO", file_name=file_name)

        registry = ParserRegistry()
        registry.register(DummyParser())
        assert registry.parse(b"", file_name="x.foo").text == "FOO"


class TestPlainTextParser:
    def test_utf8(self):
        parsed = PlainTextParser().parse("你好，世界".encode("utf-8"), file_name="a.txt")
        assert parsed.text == "你好，世界"

    def test_gbk_fallback(self):
        parsed = PlainTextParser().parse("中文内容".encode("gbk"), file_name="a.txt")
        assert "中文" in parsed.text


class TestPdfParser:
    def test_blank_pdf_page_count(self):
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)

        parsed = PdfParser().parse(buffer.getvalue(), file_name="blank.pdf")
        assert parsed.page_count == 1
        assert isinstance(parsed.text, str)
