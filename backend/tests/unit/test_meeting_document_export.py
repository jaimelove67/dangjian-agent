"""会议文书 Word 导出只使用当前登记内容。"""

from io import BytesIO

from docx import Document

from app.services.meeting_document_export import build_meeting_docx


def test_docx_contains_current_documents_without_inventing_decisions():
    data = {
        "title": "支部委员会会议",
        "activity_type": "branch_committee_meeting",
        "activity_type_label": "支委会",
        "scheduled_on": "2026-11-20",
        "host": "张书记",
        "transcript": "会议记录原文",
        "participants": [
            {"name": "张三", "attended": True},
            {"name": "李四", "attended": False},
        ],
        "context": {
            "meeting_time": "14:30",
            "location": "A301",
            "recorder": "王组织员",
            "agenda": "会议议题（草案）：\n1. 传达学习全会精神",
            "decisions": [
                {
                    "title": "审议支部工作报告",
                    "result": "approved",
                    "agree_count": 8,
                    "oppose_count": 0,
                    "abstain_count": 1,
                    "note": "同意",
                }
            ],
        },
        "documents": {
            "notice": "会议通知（草案）：\n请准时参加",
            "record_template": "会议记录（模板）",
        },
        "sources": [
            {
                "title": "把加强党性修养作为终身课题",
                "issuer": "共产党员网",
                "effective_date": "2026-11-02",
                "source_url": "https://www.12371.cn/2026/11/02/ARTI1.shtml",
            }
        ],
    }
    content = build_meeting_docx(data)
    assert content.startswith(b"PK")
    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "会议通知（草案）" in text
    assert "传达学习全会精神" in text
    assert "把加强党性修养作为终身课题" in text
    assert "会议记录原文" in text
    assert "审议支部工作报告" in text
    assert "同意 8 票；反对 0 票；弃权 1 票" in text
    assert "会议记录（模板）" not in text


def test_docx_respects_custom_section_order_and_titles():
    data = {
        "title": "支部委员会会议",
        "activity_type_label": "支委会",
        "scheduled_on": "2026-11-20",
        "host": "张书记",
        "transcript": "会议记录原文",
        "participants": [],
        "context": {"meeting_time": "14:30", "location": "A301"},
        "documents": {"notice": "会议通知原文"},
        "sources": [],
    }
    template = {
        "sections": [
            {"key": "record", "title": "会议纪要", "enabled": True},
            {"key": "notice", "title": "会议通知", "enabled": False},
            {"key": "footer", "title": "归档说明", "enabled": True},
        ],
        "labels": {"host": "主持人姓名"},
    }
    content = build_meeting_docx(data, template)
    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "会议纪要" in text
    assert "会议记录原文" in text
    assert "会议通知原文" not in text
    assert "主持人姓名：张书记" in text
