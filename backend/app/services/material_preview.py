"""不落库、不出网的材料预填建议；仅识别明确标题和标签，并返回原文依据。"""

import io
import re
import zipfile
from datetime import date
from pathlib import PurePath

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.desensitization import mask_text
from app.services.member_archive_service import ARCHIVE_MATERIAL_TYPES

MAX_TEXT = 80000
MAX_PAGES = 40
MAX_DOCX_EXPANDED = 16 * 1024 * 1024
EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"}


def local_text(content: bytes, filename: str) -> tuple[str, list[str]]:
    """限定解压量、页数和文字量；无法读取的原件仍可通过原有流程保存。"""
    ext = PurePath(filename).suffix.lower()
    notes: list[str] = []
    if ext in {".png", ".jpg", ".jpeg"}:
        return "", ["图片暂不提取文字，请对照原件手动填写。"]
    try:
        if ext in {".txt", ".md"}:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("gb18030")
        elif ext == ".docx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > MAX_DOCX_EXPANDED:
                    return "", ["文档解压内容过大，请手动填写或上传精简副本。"]
                if any(e.file_size > max(e.compress_size, 1) * 200 for e in entries):
                    return "", ["文档压缩比例异常，请手动填写或重新导出。"]
            from docx import Document
            from docx.oxml.ns import qn

            document = Document(io.BytesIO(content))
            # 按原文顺序读取段落及表格单元格。
            lines = []
            size = 0
            for paragraph in document.element.body.iter(qn("w:p")):
                line = "".join(node.text or "" for node in paragraph.iter(qn("w:t")))
                lines.append(line)
                size += len(line) + 1
                if size > MAX_TEXT:
                    break
            text = "\n".join(lines)
        elif ext == ".pdf":
            from pypdf import PdfReader

            chunks = []
            size = 0
            with io.BytesIO(content) as stream:
                document = PdfReader(stream)
                if len(document.pages) > MAX_PAGES:
                    notes.append(f"仅提取前 {MAX_PAGES} 页，请同时核对其余页面。")
                for index in range(min(len(document.pages), MAX_PAGES)):
                    page = document.pages[index]
                    page_content = page.get_contents()
                    # 在解释页面指令前限制内容流；沿用 pypdf 自带的解压上限。
                    if page_content and len(page_content.get_data()) > MAX_DOCX_EXPANDED:
                        notes.append(f"第 {index + 1} 页内容过大，后续页面未提取，请对照原件填写。")
                        break
                    chunk = (page.extract_text() or "")[: MAX_TEXT - size + 1]
                    chunks.append(chunk)
                    size += len(chunk) + 1
                    if size > MAX_TEXT:
                        break
            text = "\n".join(chunks)
        else:
            return "", ["此格式请手动填写。"]
    except Exception:
        return "", ["未能读取文档正文，请手动填写；仍可提交原件。"]
    if len(text) > MAX_TEXT:
        notes.append(f"正文仅提取前 {MAX_TEXT} 字，请对照完整原件核对。")
    text = text[:MAX_TEXT]
    if not text.strip():
        notes.append("未读到可用文字；扫描 PDF 请手动填写或提供含文字的副本。")
    return text, notes


def suggest_fields(text: str) -> tuple[dict[str, str], dict[str, str]]:
    lines = [line.strip().strip("# ") for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}

    def put(key: str, candidates: list[tuple[str, str]]) -> None:
        unique = {value for value, _ in candidates if value}
        if len(unique) == 1:
            fields[key] = next(iter(unique))
            evidence[key] = mask_text(next(source for value, source in candidates if value))[:200]

    def labelled(labels: str, limit: int = 100) -> list[tuple[str, str]]:
        result = []
        for line in lines:
            match = re.fullmatch(rf"(?:{labels})\s*[:：]\s*(.{{1,{limit}}})", line)
            if match:
                result.append((match[1].strip(), line))
        return result

    titles = labelled("材料标题|文档标题|标题", 120)
    kinds = labelled("材料类型", 50)
    for line in lines[:12]:
        for kind in ARCHIVE_MATERIAL_TYPES:
            if re.fullmatch(r"(?:20\d{2}年(?:\d{1,2}月)?\s*)?" + re.escape(kind), line):
                titles.append((line, line))
                kinds.append((kind, line))
    put("title", titles)
    put(
        "material_type",
        [(value, source) for value, source in kinds if value in ARCHIVE_MATERIAL_TYPES],
    )
    category = {"思想汇报": "thought_report", "党课培训证明": "certificate"}.get(
        fields.get("material_type", "")
    )
    if not category and any(line in {"学习心得", "学习笔记"} for line in lines[:3]):
        category = "study_note"
        if "title" not in fields:
            put("title", [(line, line) for line in lines[:3] if line in {"学习心得", "学习笔记"}])
    if category:
        fields["category"] = category
        evidence["category"] = evidence.get("material_type", evidence.get("title", ""))
    put(
        "subject_name",
        [
            (v, s)
            for v, s in labelled("姓名|申请人|汇报人|署名", 30)
            if re.fullmatch(r"[\u4e00-\u9fffA-Za-z· ]{2,30}", v)
        ],
    )
    put("issuer", labelled("出具单位|出具组织|签发单位", 100))
    put("description", labelled("摘要|内容摘要|材料说明", 500))
    dates = labelled("文档日期|落款日期|日期", 30)
    dates += [
        (line, line) for line in lines[-8:] if re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", line)
    ]
    valid = []
    for value, source in dates:
        match = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", value)
        if match:
            try:
                parsed = date(*map(int, match.groups()))
                if date(1900, 1, 1) <= parsed <= date.today():
                    valid.append((parsed.isoformat(), source))
            except ValueError:
                pass
    put("doc_date", valid)
    return fields, evidence


def preview(content: bytes, filename: str) -> dict:
    text, notes = local_text(content, filename)
    fields, evidence = suggest_fields(text)
    return {
        "status": "parsed" if text.strip() else "manual",
        "fields": fields,
        "evidence": evidence,
        "notes": notes,
        "boundary": "仅提供明确原文的填写建议；未识别项请手填，确认提交后才保存材料。",
    }


async def preview_upload(file: UploadFile) -> dict:
    name = file.filename or ""
    if not name or len(name) > 255 or any(ord(c) < 32 or c in "/\\:" for c in name):
        raise HTTPException(422, "文件名无效")
    if PurePath(name).suffix.lower() not in EXTENSIONS:
        raise HTTPException(415, "支持 PDF、DOCX、文本、PNG 和 JPG 文件")
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    if not content:
        raise HTTPException(422, "不能提取空文件")
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(413, "文件超过上传大小限制")
    return await run_in_threadpool(preview, content, name)
