"""三会一课会议文书的 Word 导出。

导出的是当前会议记录和已登记文书，不生成或补写真实发言、表决结果和决议。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

DECISION_LABELS = {
    "approved": "同意",
    "principled": "原则同意",
    "rejected": "不同意",
    "not_voted": "未表决",
}


def _set_run_font(run, size: int | None = None, bold: bool = False) -> None:
    run.font.name = "宋体"
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    if size:
        run.font.size = Pt(size)
    run.bold = bold


def _paragraph(document: Document, text: str, *, bold: bool = False, size: int = 11):
    paragraph = document.add_paragraph()
    run = paragraph.add_run(str(text or ""))
    _set_run_font(run, size=size, bold=bold)
    return paragraph


def _lines(document: Document, text: str) -> None:
    for line in str(text or "").splitlines() or [""]:
        _paragraph(document, line)


def build_meeting_docx(data: dict[str, Any]) -> bytes:
    """把当前会议记录渲染为可下载的 Word 文书。"""
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(11)
    normal._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(1.6)
    section.right_margin = Cm(1.6)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(data.get("title") or "会议文书")
    _set_run_font(run, size=18, bold=True)
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(subtitle.add_run("会议文书"), size=12, bold=False)

    context = data.get("context") or {}
    documents = data.get("documents") or {}
    _paragraph(
        document,
        f"会议类型：{data.get('activity_type_label') or data.get('activity_type') or '待补'}",
    )
    _paragraph(
        document,
        f"会议时间：{data.get('scheduled_on') or '待补'} {context.get('meeting_time') or ''}".rstrip(),
    )
    _paragraph(document, f"会议地点：{context.get('location') or '待补'}")
    _paragraph(document, f"主持人：{data.get('host') or '待补'}")
    _paragraph(document, f"记录人：{context.get('recorder') or '待补'}")
    participants = data.get("participants") or []
    attended = sum(1 for person in participants if person.get("attended"))
    _paragraph(
        document,
        f"应到人数：{len(participants) or '待补'}；实到人数：{attended if participants else '待补'}",
    )

    _paragraph(document, "一、会议通知", bold=True, size=14)
    _lines(document, documents.get("notice") or context.get("notice") or "尚未生成会议通知")

    _paragraph(document, "二、会议议题", bold=True, size=14)
    _lines(document, context.get("agenda") or "尚未登记会议议题")

    _paragraph(document, "三、学习资料", bold=True, size=14)
    sources = data.get("sources") or []
    if not sources:
        _paragraph(document, "暂无学习资料")
    for index, source in enumerate(sources, 1):
        _paragraph(document, f"{index}. {source.get('title') or '标题待补'}")
        _paragraph(
            document,
            f"来源：{source.get('issuer') or '待补'}；发布日期：{source.get('effective_date') or '待补'}",
        )
        if source.get("source_url"):
            _paragraph(document, f"原文：{source['source_url']}")

    _paragraph(document, "四、会议记录", bold=True, size=14)
    _lines(document, data.get("transcript") or "会议尚未召开，暂无会议记录")

    _paragraph(document, "五、决议与表决", bold=True, size=14)
    decisions = context.get("decisions") or []
    if not decisions:
        _paragraph(document, "尚未登记决议或表决结果")
    for index, item in enumerate(decisions, 1):
        result = DECISION_LABELS.get(item.get("result"), item.get("result") or "未表决")
        _paragraph(document, f"{index}. {item.get('title') or '事项待补'}（{result}）", bold=True)
        _paragraph(
            document,
            f"同意 {item.get('agree_count', 0)} 票；反对 {item.get('oppose_count', 0)} 票；"
            f"弃权 {item.get('abstain_count', 0)} 票",
        )
        if item.get("note"):
            _paragraph(document, f"说明：{item['note']}")

    _paragraph(
        document,
        "说明：本文件由系统按当前登记内容生成，不替代真实会议记录；正式效力以学校审核和归档结果为准。",
        size=9,
    )
    output = BytesIO()
    document.save(output)
    return output.getvalue()
