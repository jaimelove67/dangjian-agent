"""学校上传 Word 模板的占位符校验与渲染。"""

from io import BytesIO

import pytest
from docx import Document

from app.services.meeting_word_template import (
    render_word_template,
    validate_word_template,
)


def _template(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_valid_docx_template_renders_known_placeholders():
    content = _template("{{会议名称}}", "时间：{{会议时间}}", "{{会议记录}}")
    validate_word_template(content, "meeting.docx")
    rendered = render_word_template(
        content,
        {
            "title": "合成会议",
            "scheduled_on": "2026-11-20",
            "context": {"meeting_time": "14:30", "agenda": "议题"},
            "documents": {"notice": "通知"},
            "transcript": "真实记录",
            "participants": [],
        },
    )
    text = "\n".join(paragraph.text for paragraph in Document(BytesIO(rendered)).paragraphs)
    assert "合成会议" in text
    assert "2026-11-20 14:30" in text
    assert "真实记录" in text


def test_word_template_rejects_unknown_placeholders_and_macros():
    with pytest.raises(ValueError, match="不支持"):
        validate_word_template(_template("{{不存在的字段}}"), "meeting.docx")
    with pytest.raises(ValueError, match="未发现占位符"):
        validate_word_template(_template("普通正文"), "meeting.docx")
    with pytest.raises(ValueError, match="docx"):
        validate_word_template(b"not a docx", "meeting.docm")
