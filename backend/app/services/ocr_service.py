"""扫描件 / 图片的文字识别（云端视觉模型）。

只在附件链路里使用：把"几乎没有文字层的材料"转成纯文本，之后完全复用附件
链路已有的截断、密级检查、暂存与提示词注入，不再另走一条问答路径。

三条边界必须同时守住：

1. **会出网**：图片连同指令会发到云端视觉模型，因此调用前要求用户显式确认
   （接口参数 ``cloud_ocr=true``），并把确认动作记进审计；
2. **只转录不解释**：提示词禁止总结、补充、推断，识别结果会被当作"用户材料"
   送进问答提示词，OCR 阶段若开始解释，后面的引用边界就没法说清；
3. **识别不是原件**：结果一律带"由云端识别、可能有误差，请对照原件"的提示。

页数与像素上限分别由 ``settings.OCR_MAX_PAGES`` 与 ``settings.OCR_MAX_IMAGE_SIDE``
控制：扫描件动辄几十页，逐页付费且单次调用可能超时，宁可只读前几页并明确告知。
"""

from __future__ import annotations

import io
import logging
import re
from typing import Sequence

from fastapi import HTTPException, status

from app.core.config import settings
from app.llm.base import DataLevel
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import GatewayError
from app.llm.service import get_model_service

logger = logging.getLogger(__name__)

#: 只转录，不解释：任何"总结/提炼"都会让下游把模型的理解当成材料原文。
#: 提示词里**不要出现"Markdown 表格"这类格式化要求**——实测会让模型把整页正文包成
#: LaTeX 公式（$\begin{aligned}& \text{…}$），文字本身没错但满是排版噪声，
#: 进提示词后既浪费额度也干扰阅读。表格只要求"按行逐条转录"。
OCR_PROMPT = (
    "请把图片中的文字逐字转录为纯文本，保留原有的段落、条款编号与分行；"
    "表格内容按行逐条转录。"
    "不要总结、不要解释、不要补充图片里没有的内容；无法辨认的字用 □ 代替。"
    "只输出转录结果本身，不要加任何前后说明。"
)

#: LaTeX 包裹的兜底清理（模型偶尔不听话时用，见 normalize_ocr_text）
_LATEX_WRAPS = ("\\begin{aligned}", "\\end{aligned}", "\\begin{array}", "\\end{array}")


def ocr_enabled() -> bool:
    """是否配置了识别模型；未配置时图片与扫描件在附件接口直接拒绝"""
    return bool(settings.VISION_OCR_MODEL.strip())


def normalize_ocr_text(raw: str) -> str:
    """把识别结果收敛成"能直接给人读、给模型读"的纯文本。

    模型输出并不总是纯文本，实测三种形态都要处理：

    1. 正常纯文本——原样返回；
    2. 结构化 JSON（``[{"text": "...", "rotate_rect": [...]}]``，部分 OCR 模型的默认
       输出）——按原顺序取 ``text`` 拼回，坐标信息对问答无用；
    3. 被包成 LaTeX 公式（``$\\begin{aligned}& \\text{…} \\\\ …$``）——剥掉包裹与
       行分隔符，恢复成逐行文本。

    这一步是**兜底**而不是主路径：提示词已经要求纯文本，但 OCR 模型对版式的
    反应不稳定，与其指望提示词，不如在出口处收敛一次，避免把排版噪声喂进问答。
    """
    text = (raw or "").strip()
    if not text:
        return ""

    # 代码块包裹
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # 结构化 OCR 输出
    if text.startswith("[") and '"text"' in text:
        try:
            import json

            items = json.loads(text)
        except ValueError:
            items = None
        if isinstance(items, list):
            joined = "\n".join(
                str(item.get("text", "")).strip()
                for item in items
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            )
            if joined.strip():
                return joined.strip()

    # LaTeX 包裹
    if "\\text" in text or "\\begin{" in text:
        for wrap in _LATEX_WRAPS:
            text = text.replace(wrap, "")
        # \text { 内容 } → 内容
        previous = None
        while previous != text:
            previous = text
            text = re.sub(r"\\text\s*\{([^{}]*)\}", r"\1", text)
            text = re.sub(r"\\mathrm\s*\{([^{}]*)\}", r"\1", text)
        text = text.replace("\\left", "").replace("\\right", "").replace("\\quad", " ")
        # 先去掉公式定界符，否则下一行"行首 &"的判断会被 $ 挡住
        text = text.replace("$", "")
        # 行分隔符 \\ 与列前导 & 都是排版符号，不是正文
        text = re.sub(r"\\\\", "\n", text)
        text = re.sub(r"^[ \t]*&[ \t]*", "", text, flags=re.MULTILINE)
        text = text.replace("{", "").replace("}", "")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _settings_hint() -> str:
    return "如需识别扫描件与图片，请在环境中配置 VISION_OCR_MODEL 并重启服务。"


def prepare_image(data: bytes) -> bytes:
    """规整成 PNG 并限制长边：手机拍照动辄 4000px，缩到上限即可，识别率基本不变"""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "图片处理组件不可用，请改用 PDF 或 Word 文件"
        ) from exc

    try:
        with Image.open(io.BytesIO(data)) as source_image:
            image = source_image.convert("RGB")
            longest = max(image.size)
            if longest > settings.OCR_MAX_IMAGE_SIDE:
                ratio = settings.OCR_MAX_IMAGE_SIDE / longest
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "这个文件不是可识别的图片（可能已损坏或被改过扩展名），请重新导出后再上传",
        ) from exc
    except Image.DecompressionBombError as exc:  # pragma: no cover - 超大图
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "图片尺寸过大，请压缩后再上传",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "图片读取失败，请重新导出后再上传"
        ) from exc


async def _ocr_one(image: bytes, *, context: dict, label: str) -> str:
    """识别一张图；单页失败要说清是哪一页，不能整份材料一起报废"""
    try:
        text = await get_model_service().vision(
            OCR_PROMPT,
            [prepare_image(image)],
            data_level=DataLevel.INTERNAL,
            context=context,
        )
    except GatewayError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{label}不能使用云端识别：{exc}；请改用带文字层的 PDF / Word，或走线下人工路径",
        ) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{label}识别失败：{exc}。{_settings_hint()}",
        ) from exc
    text = normalize_ocr_text(text or "")
    if not text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{label}没有识别出文字：图片可能过暗、过小或没有文字。请重新拍摄或导出后再上传",
        )
    return text


async def ocr_images(
    images: Sequence[bytes], *, context: dict, labels: Sequence[str] | None = None
) -> str:
    """按顺序识别多张图，拼成带页标的纯文本"""
    parts: list[str] = []
    for index, image in enumerate(images):
        label = labels[index] if labels and index < len(labels) else f"第 {index + 1} 页"
        text = await _ocr_one(image, context=context, label=label)
        parts.append(f"〔{label}〕\n{text}" if len(images) > 1 else text)
    return "\n\n".join(parts)


async def ocr_pdf(data: bytes, *, context: dict) -> tuple[str, int, int]:
    """识别扫描件 PDF，返回 (正文, 实际识别页数, 总页数)

    总页数大于识别页数时由调用方提示"只读了前 N 页"，不能假装读完了全文。
    """
    images: list[bytes] = []
    total = 0
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "PDF 渲染组件不可用，请改用 Word 文件"
        ) from exc
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "PDF 无法打开（可能已损坏或加密），请重新导出后再上传",
        ) from exc
    try:
        total = len(document)
        for index in range(min(total, settings.OCR_MAX_PAGES)):
            page = document[index]
            try:
                bitmap = page.render(scale=2)
                buffer = io.BytesIO()
                bitmap.to_pil().save(buffer, format="PNG", optimize=True)
                images.append(buffer.getvalue())
            finally:
                page.close()
    finally:
        document.close()

    if not images:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "这份 PDF 没有可渲染的页面，请重新导出后再上传"
        )
    labels = [f"第 {index + 1} 页" for index in range(len(images))]
    text = await ocr_images(images, context=context, labels=labels)
    return text, len(images), total


async def ocr_image_file(data: bytes, *, file_name: str, context: dict) -> str:
    """识别单张图片"""
    return await ocr_images([data], context=context, labels=[file_name])
