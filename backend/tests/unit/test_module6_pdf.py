"""使用真实有效PDF字节验证已锁定的pypdf解析，不替换PDF阅读器。"""

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.rag.exceptions import ParseError
from app.rag.loader import build_default_registry


def test_actual_two_page_pdf_parses_text_and_page_count():
    writer = PdfWriter()
    for text in ["Module6 parser acceptance page one", "Evidence page two"]:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 12 Tf 50 740 Td (" + text + ") Tj ET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    parsed = build_default_registry().parse(output.getvalue(), file_name="module6.pdf")
    assert parsed.page_count == 2 and parsed.file_name == "module6.pdf"
    assert (
        "Module6 parser acceptance page one" in parsed.text and "Evidence page two" in parsed.text
    )


def test_corrupted_pdf_has_explicit_parse_error():
    with pytest.raises(ParseError):
        build_default_registry().parse(b"%PDF-1.7\ncorrupted", file_name="broken.pdf")
