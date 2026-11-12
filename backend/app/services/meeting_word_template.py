"""学校上传 Word 模板的校验与占位符渲染。

只接受 .docx，不接受宏、外部链接和未知占位符。占位符只映射现有登记内容，
不会根据文本自动生成会议决议或组织结论。
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any, Iterable, Iterator

from docx import Document

PLACEHOLDERS = {
    "会议名称",
    "会议类型",
    "会议时间",
    "会议地点",
    "主持人",
    "记录人",
    "参加人数",
    "会议通知",
    "会议议题",
    "学习资料",
    "会议记录",
    "决议与表决",
    "说明",
}
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
DISCLAIMER = (
    "本文件由系统按当前登记内容生成，不替代真实会议记录；正式效力以学校审核和归档结果为准。"
)
DECISION_LABELS = {
    "approved": "同意",
    "principled": "原则同意",
    "rejected": "不同意",
    "not_voted": "未表决",
}


def _xml_parts(archive: zipfile.ZipFile) -> Iterable[bytes]:
    for name in archive.namelist():
        if name in {"word/document.xml"} or re.fullmatch(r"word/(header|footer)\d+\.xml", name):
            yield archive.read(name)


def validate_word_template(content: bytes, file_name: str) -> None:
    """拒绝宏、外部链接、未知占位符和没有占位符的模板。"""
    if not file_name.lower().endswith(".docx"):
        raise ValueError("只支持 .docx 格式的 Word 模板")
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise ValueError("文件不是有效的 Word 文档")
            if "word/vbaProject.bin" in names:
                raise ValueError("Word 模板不能包含宏")
            for name in names:
                if name.endswith(".rels"):
                    text = archive.read(name).decode("utf-8", errors="ignore")
                    if 'TargetMode="External"' in text:
                        raise ValueError("Word 模板不能包含外部链接")
            found: set[str] = set()
            for raw in _xml_parts(archive):
                text = raw.decode("utf-8", errors="ignore")
                # Word 可能把占位符拆到多个 run 中，校验前先去掉 XML 标签。
                plain = re.sub(r"<[^>]+>", "", text)
                found.update(match.group(1).strip() for match in PLACEHOLDER.finditer(plain))
            if not found:
                raise ValueError("Word 模板未发现占位符，请先插入 {{会议名称}} 等字段")
            unknown = sorted(item for item in found if item not in PLACEHOLDERS)
            if unknown:
                raise ValueError(f"Word 模板包含不支持的占位符：{'、'.join(unknown)}")
    except zipfile.BadZipFile as exc:
        raise ValueError("文件不是有效的 Word 文档") from exc


def _source_text(data: dict[str, Any]) -> str:
    lines = []
    for index, source in enumerate(data.get("sources") or [], 1):
        line = f"{index}. {source.get('title') or '标题待补'}"
        detail = "；".join(
            item
            for item in (
                source.get("issuer"),
                str(source.get("effective_date") or "")[:10] or None,
                source.get("source_url"),
            )
            if item
        )
        lines.append(line + (f"\n{detail}" if detail else ""))
    return "\n".join(lines) or "暂无学习资料"


def _decision_text(context: dict[str, Any]) -> str:
    lines = []
    for index, item in enumerate(context.get("decisions") or [], 1):
        result = DECISION_LABELS.get(item.get("result"), item.get("result") or "未表决")
        lines.append(f"{index}. {item.get('title') or '事项待补'}（{result}）")
        lines.append(
            f"同意 {item.get('agree_count', 0)} 票；反对 {item.get('oppose_count', 0)} 票；"
            f"弃权 {item.get('abstain_count', 0)} 票"
        )
        if item.get("note"):
            lines.append(f"说明：{item['note']}")
    return "\n".join(lines) or "尚未登记决议或表决结果"


def template_values(data: dict[str, Any]) -> dict[str, str]:
    context = data.get("context") or {}
    documents = data.get("documents") or {}
    participants = data.get("participants") or []
    attended = sum(1 for person in participants if person.get("attended"))
    return {
        "会议名称": str(data.get("title") or "会议文书"),
        "会议类型": str(data.get("activity_type_label") or data.get("activity_type") or "待补"),
        "会议时间": f"{data.get('scheduled_on') or '待补'} {context.get('meeting_time') or ''}".rstrip(),
        "会议地点": str(context.get("location") or "待补"),
        "主持人": str(data.get("host") or "待补"),
        "记录人": str(context.get("recorder") or "待补"),
        "参加人数": (
            f"应到 {len(participants) or '待补'} 人；实到 {attended if participants else '待补'} 人"
        ),
        "会议通知": str(documents.get("notice") or context.get("notice") or "尚未生成会议通知"),
        "会议议题": str(context.get("agenda") or "尚未登记会议议题"),
        "学习资料": _source_text(data),
        "会议记录": str(data.get("transcript") or "会议尚未召开，暂无会议记录"),
        "决议与表决": _decision_text(context),
        "说明": DISCLAIMER,
    }


def _paragraphs(document: Any) -> Iterator[Any]:
    def walk(paragraphs: Iterable[Any]) -> Iterator[Any]:
        for paragraph in paragraphs:
            yield paragraph

    yield from walk(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from walk(cell.paragraphs)
                for nested in cell.tables:
                    for nested_row in nested.rows:
                        for nested_cell in nested_row.cells:
                            yield from walk(nested_cell.paragraphs)
    for section in document.sections:
        yield from walk(section.header.paragraphs)
        yield from walk(section.footer.paragraphs)


def _replace_paragraph(paragraph: Any, mapping: dict[str, str]) -> None:
    if "{{" not in paragraph.text:
        return
    replaced = PLACEHOLDER.sub(
        lambda match: mapping.get(match.group(1).strip(), ""), paragraph.text
    )
    for run in list(paragraph.runs):
        run.text = ""
    run = paragraph.add_run()
    for index, line in enumerate(replaced.splitlines()):
        if index:
            run.add_break()
        run.add_text(line)


def render_word_template(content: bytes, data: dict[str, Any]) -> bytes:
    document = Document(BytesIO(content))
    mapping = template_values(data)
    for paragraph in _paragraphs(document):
        _replace_paragraph(paragraph, mapping)
    output = BytesIO()
    document.save(output)
    return output.getvalue()
