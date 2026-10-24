"""入库元数据的"建议值"抽取：从文件正文里抄出已经写明的事实，交给用户确认。

设计边界（与附件、问答链路保持一致）：

1. **不落库**：这是一次预览，接口不写任何表，用户点"入库"才走原来的创建流程；
2. **不猜**：正文没写的字段一律留空，不给默认值、不做推断。发文机关与生效日期
   一旦编错，后面每条引用都会带着错的出处，比让用户自己填更糟；
3. **不出网越界**：正文按 WF-04 判定能否发给云端模型，涉密/含个人标识直接拒绝，
   提示用户改用离线路径；
4. **扫描件不处理**：没有文字层就没有可抄的事实，此时明确要求用户先转文字层，
   而不是拿几张图去猜标题。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException, status

from app.chains.workflow_interfaces import sensitive_check
from app.core.config import settings
from app.llm.base import DataLevel, TaskType
from app.llm.errors import ModelUnavailableError
from app.llm.gateway import GatewayError
from app.llm.service import get_model_service
from app.prompts.knowledge_meta import FIELDS, LEVELS, build_prompt
from app.rag.exceptions import ParseError, UnsupportedFormatError
from app.rag.loader import default_registry
from app.schemas.wf import SensitiveCheckRequest

logger = logging.getLogger(__name__)

#: 只取正文前这么多字：标题、文号、发文机关、施行日期几乎都在开头，
#: 整篇发过去既慢又贵，还会稀释模型的注意力
MAX_PREVIEW_CHARS = 6000
#: 摘要长度上限，与前端提示保持一致
MAX_SUMMARY_CHARS = 120
#: 标签数量与长度上限
MAX_TAGS = 5
MAX_TAG_CHARS = 16


def _squeeze(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_date(value: Any) -> Optional[str]:
    """把模型可能写出的多种日期写法收敛成 YYYY-MM-DD；认不出就丢弃。

    中文文件里常见「2026年9月1日」「2026.9.1」「2026/09/01」，直接拒绝会让用户
    白等一次识别；但也不能"尽力猜"，所以只接受能明确解析出年月日的形式。
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    match = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", raw)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_json(raw: str) -> dict[str, Any]:
    """容忍代码块包裹与前后废话，取出第一段 JSON 对象"""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型未返回 JSON")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型未返回 JSON 对象")
    return value


def _clean_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,，、;；\s]+", value)
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip().strip("#")
        if tag and len(tag) <= MAX_TAG_CHARS and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def _clean_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().strip("《》")
    return text[:limit]


def normalize_suggestion(payload: dict[str, Any]) -> dict[str, Any]:
    """逐字段校验：模型给的枚举、日期、长度不合规就置空，绝不"修一修"凑合"""
    level = str(payload.get("level") or "").strip().lower()
    return {
        "title": _clean_text(payload.get("title"), limit=200),
        "doc_number": _clean_text(payload.get("doc_number"), limit=100),
        "issuer": _clean_text(payload.get("issuer"), limit=100),
        "level": level if level in LEVELS else "",
        "issue_date": _parse_date(payload.get("issue_date")),
        "effective_date": _parse_date(payload.get("effective_date")),
        "expiration_date": _parse_date(payload.get("expiration_date")),
        "tags": _clean_tags(payload.get("tags")),
        "summary": _clean_text(payload.get("summary"), limit=MAX_SUMMARY_CHARS),
    }


def extract_text(data: bytes, *, file_name: str) -> tuple[str, int]:
    """抽出正文并截断；读不出正文时给出明确出路（与入库接口同一套说法）"""
    try:
        parsed = default_registry.parse(data, file_name=file_name)
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_FORMAT", "message": str(exc)},
        ) from exc
    except ParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PARSE_FAILED", "message": f"《{file_name}》解析失败：{exc}"},
        ) from exc

    text = _squeeze(parsed.text or "")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "EMPTY_TEXT",
                "message": (
                    "这份文件里没有可读取的正文，无法自动识别标题、发文机关等信息。"
                    "如果是扫描件，请先用文字识别导出带文字层的 PDF，或把正文另存为 .docx / .txt。"
                    "你也可以直接手动填写表单完成入库。"
                ),
            },
        )
    return text[:MAX_PREVIEW_CHARS], len(text)


async def suggest_metadata(
    *, data: bytes, file_name: str, context: Optional[dict] = None
) -> dict[str, Any]:
    """调模型抽取建议值；返回字段 + 未识别项说明 + 正文长度"""
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "不能上传空文件")
    if len(data) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB）",
            },
        )

    preview, total_chars = extract_text(data, file_name=file_name)

    # 正文会整段发给云端模型：与问答共用同一条出网边界
    decision = sensitive_check(SensitiveCheckRequest(text=preview))
    if not decision.cloud_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLOUD_NOT_ALLOWED",
                "message": (
                    f"《{file_name}》不能发送到云端模型识别：{decision.guidance}。"
                    "请手动填写下方表单完成入库。"
                ),
            },
        )

    try:
        response = await get_model_service().generate(
            build_prompt(preview),
            data_level=DataLevel(decision.level),
            task_type=TaskType.EXTRACT,
            temperature=0,
            context=context or {},
        )
    except GatewayError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "CLOUD_NOT_ALLOWED", "message": f"无法调用云端模型：{exc}"},
        ) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MODEL_UNAVAILABLE",
                "message": f"信息识别服务暂不可用：{exc}。你仍可手动填写表单完成入库。",
            },
        ) from exc

    try:
        suggestion = normalize_suggestion(_parse_json(response.content))
    except (ValueError, json.JSONDecodeError):
        logger.warning(
            "knowledge_meta_parse_failed", extra={"file_name": file_name, "chars": total_chars}
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "SUGGEST_PARSE_FAILED",
                "message": "没能从这份文件里提取出结构化信息，请手动填写表单完成入库。",
            },
        ) from None

    missing = [field for field in FIELDS if not suggestion.get(field)]
    suggestion["missing_fields"] = missing
    suggestion["text_chars"] = total_chars
    suggestion["truncated"] = total_chars > MAX_PREVIEW_CHARS
    logger.info(
        "knowledge_meta_suggested",
        extra={
            "file_name": file_name,
            "text_chars": total_chars,
            "missing": missing,
            "level": suggestion["level"],
        },
    )
    return suggestion
