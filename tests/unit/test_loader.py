"""文档解析器与注册机制测试（框架文档 5.2.2）"""

import io

import pytest

from app.rag.exceptions import ParseError, UnsupportedFormatError
from app.rag.loader import (
    ParsedDocument,
    ParserRegistry,
    PdfParser,
    PlainTextParser,
    build_default_registry,
    empty_text_reason,
    unsupported_reason,
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


def blank_pdf(pages: int) -> bytes:
    """生成"有页面但没有文字层"的 PDF，即扫描件/图片型 PDF 的字节特征。"""
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestParseFailureDiagnosis:
    """T-WF01-04：解析失败要有明确提示并可重试，不能只回一句"没有可解析文本"。"""

    def test_scanned_pdf_reports_page_count_and_ocr_paths(self):
        parsed = PdfParser().parse(blank_pdf(3), file_name="scan.pdf")
        reason = empty_text_reason(parsed)
        # 说清"文件读到了但只有图片"：带上页数，用户才知道不是文件坏了
        assert "3 页" in reason
        assert "文字层" in reason and "OCR" in reason
        assert "另存为 .docx 或 .txt" in reason
        assert "附件留存" in reason

    def test_scanned_pdf_hint_differs_from_empty_template_hint(self):
        scanned = empty_text_reason(PdfParser().parse(blank_pdf(3), file_name="scan.pdf"))
        blank = empty_text_reason(ParsedDocument(text="", file_name="template.docx"))
        # 扫描件要从原文件重新导出文字层，空模板只要换个文件：两者不能是同一句话
        assert "3 页" in scanned and "3 页" not in blank
        assert "OCR" in scanned and "OCR" not in blank
        assert scanned != blank
        assert ".docx" in blank

    def test_pdf_without_pages_points_at_broken_file(self):
        buffer = io.BytesIO()
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        PdfWriter().write(buffer)
        parsed = PdfParser().parse(buffer.getvalue(), file_name="empty.pdf")
        assert parsed.page_count == 0
        assert "损坏" in empty_text_reason(parsed)

    def test_image_upload_explains_ocr_gap_and_alternatives(self):
        registry = build_default_registry()
        with pytest.raises(UnsupportedFormatError) as err:
            registry.get("photo.JPG")
        message = str(err.value)
        assert "图片" in message and "OCR" in message
        assert "提取文字" in message and "图片转文字" in message

    def test_legacy_word_and_table_formats_give_conversion_steps(self):
        registry = build_default_registry()
        with pytest.raises(UnsupportedFormatError) as legacy:
            registry.get("notice.doc")
        assert "另存为 .docx" in str(legacy.value)
        with pytest.raises(UnsupportedFormatError) as table:
            registry.get("roster.xlsx")
        assert "不能作为制度正文入库" in str(table.value)

    def test_unknown_format_lists_supported_ones(self):
        message = unsupported_reason(".xyz", supported=[".docx", ".pdf"])
        assert "不支持的文件格式: .xyz" in message
        assert ".docx / .pdf" in message
