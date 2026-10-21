"""问答附件的临时材料暂存与正文抽取。

为什么附件不进知识库：用户上传的是**本次提问的补充材料**（一份细则草稿、一张
时间表、一段上级通知），它既不是经审核入库的制度正文，也不应参与租户共享检索。
因此这里的定位是"会话内的临时材料"：

1. 上传即抽取正文，正文按 租户 + 用户 + 附件编号 暂存到 Redis，2 小时过期；
2. 提问时只按当前用户自己的编号取回，取不到就明确要求重新上传，绝不跨用户复用；
3. 材料只进生成提示词，**不参与检索、不占引用编号**——引用编号 [n] 只能指向
   检索到的制度片段，这是"每条结论都能溯源到正式文件"的底线。

解析器复用 ``app.rag.loader`` 的注册表，所以支持格式（.txt / .md / .pdf / .docx）
与知识库入库完全一致，提示语也复用同一套"为什么读不出来、该怎么办"的说法。

扫描件与图片走 ``app.services.ocr_service`` 的云端识别：因为要出网，必须由用户
显式确认（``cloud_ocr=true``）才处理，未确认时返回 428 与可执行的两条出路。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from fastapi import HTTPException, status

from app.chains.workflow_interfaces import sensitive_check
from app.core.cache import CacheService
from app.core.config import settings
from app.rag.exceptions import ParseError, UnsupportedFormatError
from app.rag.loader import IMAGE_EXTENSIONS, default_registry, empty_text_reason
from app.schemas.wf import SensitiveCheckRequest
from app.services.ocr_service import ocr_enabled, ocr_image_file, ocr_pdf

#: 一次提问最多携带的附件份数（再多模型上下文也读不完，界面上限同此值）
MAX_ATTACHMENTS = 3
#: 单份附件参与生成的最大字数：超出部分截断，并在回答里明确提示"只读了前 N 字"
MAX_ATTACHMENT_CHARS = 6000
#: 附件暂存有效期（秒）：够把问题问完，又不至于长期留着用户材料
ATTACHMENT_TTL_SECONDS = 2 * 60 * 60
#: 需要用户确认"允许云端识别"时返回的错误码，前端据此弹确认而不是直接报错
OCR_CONSENT_CODE = "OCR_CONSENT_REQUIRED"

_KEY_PREFIX = "qa:attachment"

OCR_NOTE = "《{name}》的文字由云端识别（OCR）生成，可能存在识别误差，请对照原件核对。"


@dataclass
class QAAttachment:
    """一份已解析的问答附件（正文随对象返回，不再二次取 Redis）"""

    id: str
    file_name: str
    size: int
    chars: int
    truncated: bool
    ocr: bool = False
    notes: list[str] = field(default_factory=list)
    text: str = field(default="", repr=False)

    def summary(self) -> dict[str, Any]:
        """对外契约：不回传正文，避免把整份材料塞进响应与前端日志"""
        return {
            "id": self.id,
            "file_name": self.file_name,
            "size": self.size,
            "chars": self.chars,
            "truncated": self.truncated,
            "ocr": self.ocr,
            "notes": list(self.notes),
        }


def supported_extensions() -> list[str]:
    """当前部署接受的附件格式：开启云端识别后，图片也纳入可接受范围"""
    exts = list(default_registry.supported_extensions)
    if ocr_enabled():
        exts.extend(ext for ext in IMAGE_EXTENSIONS if ext not in exts)
    return sorted(exts)


def _key(tenant_id: str, user_id: str, attachment_id: str) -> str:
    return f"{_KEY_PREFIX}:{tenant_id}:{user_id}:{attachment_id}"


def _squeeze(text: str) -> str:
    """压掉解析产生的连续空行：PDF 抽取常留下成片空白，白占上下文额度"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _consent_required(file_name: str, reason: str, *, supported: list[str]) -> HTTPException:
    """需要用户先确认"允许把这批图片发到云端识别"。

    用 428（前置条件未满足）而不是 4xx 里更笼统的 400/422：前端据此弹确认框、
    用户回心转意后带 ``cloud_ocr=true`` 重传一次即可，其他错误不会被误当成"要确认"。
    """
    return HTTPException(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        detail={
            "code": OCR_CONSENT_CODE,
            "message": f"《{file_name}》{reason}如需处理，请确认该材料不含涉密内容与身份证、"
            "手机号等个人身份信息后，允许使用云端文字识别（OCR）重新上传。",
            "supported": supported,
        },
    )


def extract_text(data: bytes, *, file_name: str) -> tuple[str, bool]:
    """抽取有文字层文件的正文，返回 (正文, 是否被截断)。

    格式不支持、解析失败、没有文字层三种情况分别给出可执行的出路
    （与知识库入库共用同一套提示语，避免同一件事两种说法）。
    """
    ext = Path(file_name).suffix.lower()
    try:
        parsed = default_registry.parse(data, file_name=file_name)
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_FORMAT",
                "message": str(exc),
                "supported": supported_extensions(),
            },
        ) from exc
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PARSE_FAILED",
                "message": f"《{file_name}》解析失败：{exc}",
                "supported": supported_extensions(),
            },
        ) from exc

    text = _squeeze(parsed.text or "")
    if not text:
        raise _NoTextLayer(parsed)
    if ext not in supported_extensions():  # pragma: no cover - 注册表已拦截
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文件格式")

    truncated = len(text) > MAX_ATTACHMENT_CHARS
    return (text[:MAX_ATTACHMENT_CHARS] if truncated else text), truncated


class _NoTextLayer(Exception):
    """内部信号：文件读得到、但没有文字层（扫描件/纯图片），等待上层决定是否 OCR"""

    def __init__(self, parsed: Any) -> None:
        super().__init__(empty_text_reason(parsed))
        self.parsed = parsed


async def _text_of(
    data: bytes, *, file_name: str, cloud_ocr: bool, context: dict
) -> tuple[str, list[str], bool]:
    """统一入口：先按文字层解析，读不出来再（经用户确认）走云端识别。

    返回 (正文, 提示列表, 是否使用过 OCR)。提示会随回答一起呈现，让"这段文字是
    识别出来的、可能有误差"始终可见。
    """
    ext = Path(file_name).suffix.lower()
    notes: list[str] = []

    if ext in IMAGE_EXTENSIONS:
        if not ocr_enabled():
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={
                    "code": "UNSUPPORTED_FORMAT",
                    "message": (
                        f"图片文件（{ext}）需要文字识别才能读取，本部署尚未开启该能力；"
                        "请把图片里的文字转成可复制的文本（.docx / .txt / 带文字层的 PDF）后上传。"
                    ),
                    "supported": supported_extensions(),
                },
            )
        if not cloud_ocr:
            raise _consent_required(
                file_name,
                "是图片，读取其中的文字需要把图片发送到云端识别；",
                supported=supported_extensions(),
            )
        text = await ocr_image_file(data, file_name=file_name, context=context)
        notes.append(OCR_NOTE.format(name=file_name))
        return text, notes, True

    try:
        text, _ = extract_text(data, file_name=file_name)
        return text, notes, False
    except _NoTextLayer as exc:
        if ext != ".pdf":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "EMPTY_TEXT",
                    "message": str(exc),
                    "supported": supported_extensions(),
                },
            ) from exc
        if not ocr_enabled():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "EMPTY_TEXT",
                    "message": str(exc),
                    "supported": supported_extensions(),
                },
            ) from exc
        if not cloud_ocr:
            raise _consent_required(
                file_name,
                "是扫描件（PDF 里没有文字层），读取其中文字需要把页面图片发送到云端识别；",
                supported=supported_extensions(),
            ) from exc

        text, pages_read, pages_total = await ocr_pdf(data, context=context)
        notes.append(OCR_NOTE.format(name=file_name))
        if pages_total > pages_read:
            notes.append(
                f"《{file_name}》共 {pages_total} 页，本次只识别了前 {pages_read} 页；"
                "后续页面的内容未参与作答。"
            )
        return text, notes, True


async def store_attachment(
    cache: CacheService,
    *,
    tenant_id: str,
    user_id: str,
    file_name: str,
    data: bytes,
    cloud_ocr: bool = False,
    context: Optional[dict] = None,
) -> QAAttachment:
    """解析并暂存一份附件；正文只在 Redis 里停留 ``ATTACHMENT_TTL_SECONDS``

    ``cloud_ocr`` 是用户对"允许把图片发到云端识别"的显式确认，默认拒绝：
    这是一次真实的出网动作，不能由服务端替用户决定。
    """
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "不能上传空文件")
    if len(data) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": (
                    f"《{file_name}》超过单份上限 "
                    f"{settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB，请压缩或拆分后再上传"
                ),
            },
        )

    text, notes, used_ocr = await _text_of(
        data, file_name=file_name, cloud_ocr=cloud_ocr, context=context or {}
    )
    text = _squeeze(text)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "EMPTY_TEXT", "message": f"《{file_name}》没有读到任何文字，请重新导出后再上传"},
        )

    # 材料最终会随提示词出网，与提问走同一条 WF-04 边界：宁可在上传时说清楚，
    # 也别让用户写完问题才在生成阶段被拦下来。
    decision = sensitive_check(SensitiveCheckRequest(text=text))
    if not decision.cloud_allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"《{file_name}》不能用于 AI 处理：{decision.guidance}",
        )

    truncated = len(text) > MAX_ATTACHMENT_CHARS
    if truncated:
        text = text[:MAX_ATTACHMENT_CHARS]
    attachment = QAAttachment(
        id=uuid.uuid4().hex,
        file_name=file_name,
        size=len(data),
        chars=len(text),
        truncated=truncated,
        ocr=used_ocr,
        notes=notes,
        text=text,
    )
    stored = await cache.set(
        _key(tenant_id, user_id, attachment.id),
        {
            "id": attachment.id,
            "file_name": attachment.file_name,
            "size": attachment.size,
            "chars": attachment.chars,
            "truncated": attachment.truncated,
            "ocr": attachment.ocr,
            "notes": attachment.notes,
            "text": attachment.text,
        },
        ttl=ATTACHMENT_TTL_SECONDS,
    )
    if not stored:
        # 暂存失败还返回成功，会让用户在提问时才发现材料丢了，损失一次输入
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "附件暂存服务暂不可用，请稍后重试（不影响文字提问）",
        )
    return attachment


async def load_attachments(
    cache: CacheService,
    *,
    tenant_id: str,
    user_id: str,
    attachment_ids: Sequence[str],
) -> list[QAAttachment]:
    """按当前用户取回附件正文：只认本人编号，过期即失效"""
    ids = [value for value in dict.fromkeys(attachment_ids) if value]
    if len(ids) > MAX_ATTACHMENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"一次提问最多携带 {MAX_ATTACHMENTS} 个附件，请分批提问",
        )
    items: list[QAAttachment] = []
    for attachment_id in ids:
        payload: Optional[Any] = await cache.get(_key(tenant_id, user_id, attachment_id))
        if not isinstance(payload, dict) or not payload.get("text"):
            raise HTTPException(
                status.HTTP_410_GONE,
                "附件已过期或已失效，请重新上传后再提问（文字提问不受影响）",
            )
        items.append(
            QAAttachment(
                id=str(payload.get("id") or attachment_id),
                file_name=str(payload.get("file_name") or "未命名附件"),
                size=int(payload.get("size") or 0),
                chars=int(payload.get("chars") or 0),
                truncated=bool(payload.get("truncated")),
                ocr=bool(payload.get("ocr")),
                notes=[str(note) for note in (payload.get("notes") or [])],
                text=str(payload["text"]),
            )
        )
    return items


def material_block(items: Sequence[QAAttachment]) -> str:
    """拼成提示词里的「用户上传材料」块。

    与 ``<参考资料>`` 分开写、编号方式也分开（材料 1 / 材料 2），是为了让模型
    不可能把材料当成第 [n] 条来源——引用核验只认检索片段，材料混进引用会
    直接让结论失去可核对性。
    """
    if not items:
        return ""
    blocks = [
        f"〔材料 {index}〕文件名：{item.file_name}；正文约 {item.chars} 字\n{item.text}"
        for index, item in enumerate(items, 1)
    ]
    return "<用户上传材料>\n" + "\n\n".join(blocks) + "\n</用户上传材料>"


def attachment_warnings(items: Sequence[QAAttachment]) -> list[str]:
    """随回答一起呈现的附件提示：OCR 误差 + 截断 + 只识别了部分页

    这些提示必须在**回答旁边**出现，而不只是上传时一闪而过——用户事后看到结论
    时仍要知道"这段依据是识别出来的、只读了前几页"。
    """
    warnings: list[str] = []
    for item in items:
        warnings.extend(item.notes)
        if item.truncated:
            warnings.append(
                f"附件《{item.file_name}》正文较长，本次只读取了前 {MAX_ATTACHMENT_CHARS} 字参与作答，"
                "如需依据后半部分内容，请把相关段落单独整理后重新上传。"
            )
    return list(dict.fromkeys(warnings))
