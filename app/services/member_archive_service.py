"""党员档案扫描件：影像件归档 + 文字识别。

与问答附件的区别决定了这里的容错方式：

- 问答要**文本才能作答**，读不出来就得让用户换文件；档案归档要**影像才能算归档**，
  识别失败不能连带丢原件，所以这里把识别结果当作附加信息记录状态，不抛异常中断。
- 识别会把页面图片发到云端视觉模型，属于材料出网：未显式同意时**不调用模型**，
  只保存影像并标记 ``skipped``，绝不"顺便识别一下"。
- 识别结果不是原件：``ocr_status=done`` 的文本一律带提示，核验仍以影像为准。

页数与像素上限复用 ``settings.OCR_MAX_PAGES`` / ``OCR_MAX_IMAGE_SIDE``，超限只读前几页
并在提示里说清楚读了哪些页。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.rag.loader import IMAGE_EXTENSIONS, default_registry
from app.services.ocr_service import normalize_ocr_text, ocr_enabled, ocr_image_file, ocr_pdf

logger = logging.getLogger(__name__)

#: 扫描仪与手机常见的输出格式；扩展名不改，识别时按内容重新编码
SCAN_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})
#: 入库文本上限：一份档案材料几十页也就几万字，超出多是识别跑飞，
#: 截断并保留提示，比整段入库把库撑大更可控
MAX_SCAN_CHARS = 200_000

TEXT_LAYER_NOTE = "正文来自文件自带的文字层，未使用云端识别。"
OCR_NOTE = "正文由云端识别（OCR）生成，可能存在识别误差，请对照原件核对。"
SKIPPED_CONSENT_NOTE = "未勾选云端识别，本次只保存了影像件。"
SKIPPED_DISABLED_NOTE = "本部署未开启文字识别，本次只保存了影像件。"
FAILED_NOTE = "云端识别失败，本次只保存了影像件；原件可正常查看。"


@dataclass
class ScanText:
    """一份扫描件的识别结果；``status`` 直接写进材料记录的 ``ocr_status``。"""

    text: str = ""
    status: str = "skipped"
    pages: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.status == "done" and bool(self.text.strip())


def scan_supported(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in SCAN_EXTENSIONS


def _clip(text: str) -> str:
    return text[:MAX_SCAN_CHARS] if len(text) > MAX_SCAN_CHARS else text


def _pdf_pages(data: bytes) -> int:
    """总页数只用于界面提示；读不出来就当 0，不影响归档。"""
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(data)
        try:
            return len(document)
        finally:
            document.close()
    except Exception:  # pragma: no cover - 损坏文件已在识别阶段报错
        return 0


def _text_layer(data: bytes, file_name: str) -> str:
    """PDF 自带的文字层：能读出来就不必花识别额度，也不必让材料出网。"""
    try:
        parsed = default_registry.parse(data, file_name=file_name)
    except Exception:  # 解析失败按扫描件处理，交给后面的识别分支
        return ""
    return normalize_ocr_text(parsed.text or "")


async def extract_scan_text(
    data: bytes, *, file_name: str, cloud_ocr: bool, context: dict | None = None
) -> ScanText:
    """抽取扫描件正文；任何失败都退回"只有影像"，不抛出。"""
    ext = Path(file_name).suffix.lower()
    pages = _pdf_pages(data) if ext == ".pdf" else (1 if ext in IMAGE_EXTENSIONS else 0)

    if ext == ".pdf":
        text = _clip(_text_layer(data, file_name))
        if text.strip():
            return ScanText(text=text, status="done", pages=pages, notes=[TEXT_LAYER_NOTE])

    if not cloud_ocr:
        return ScanText(status="skipped", pages=pages, notes=[SKIPPED_CONSENT_NOTE])
    if not ocr_enabled():
        return ScanText(status="skipped", pages=pages, notes=[SKIPPED_DISABLED_NOTE])

    ocr_context = {"scene": "member_archive", **(context or {})}
    try:
        if ext == ".pdf":
            text, read_pages, total = await ocr_pdf(data, context=ocr_context)
            pages = total or read_pages
            notes = [OCR_NOTE]
            if total > read_pages:
                notes.append(f"共 {total} 页，本次只识别了前 {read_pages} 页，后续页未识别。")
        else:
            text = await ocr_image_file(data, file_name=file_name, context=ocr_context)
            pages = 1
            notes = [OCR_NOTE]
    except Exception as exc:  # 模型不可用、被合规拦截、文件损坏都走这里
        logger.warning("档案扫描件识别失败：%s（%s）", file_name, exc)
        return ScanText(status="failed", pages=pages, notes=[FAILED_NOTE])

    text = _clip(normalize_ocr_text(text))
    if not text.strip():
        return ScanText(status="failed", pages=pages, notes=[FAILED_NOTE])
    return ScanText(text=text, status="done", pages=pages, notes=notes)
