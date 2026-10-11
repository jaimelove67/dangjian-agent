"""共用纪要原文定位与人工审核规则，不调用外部模型或自动认定组织结论。"""

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

MINUTES_LABELS = {
    "learning_points": ("学习要点", "学习重点"),
    "consensus": ("讨论共识", "会议共识"),
    "requirements": ("工作要求", "落实要求"),
}
STUDY_NOTICE = "供党委研究确定"


def utc_now() -> datetime:
    """与项目数据库的无时区 UTC 字段保持一致。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def extract_minutes(transcript: str) -> dict[str, Any]:
    """仅摘录带明确标签的原文行；模糊或缺少的内容留空并显示待补。"""
    result: dict[str, Any] = {key: [] for key in MINUTES_LABELS}
    offset = 0
    for line in transcript.splitlines(keepends=True):
        for key, labels in MINUTES_LABELS.items():
            pattern = r"^\s*(?:" + "|".join(labels) + r")[：:]\s*(\S.*)"
            match = re.match(pattern, line.rstrip("\r\n"))
            if match:
                quote = match.group(1).rstrip()
                if len(quote) > 5000 or len(result[key]) >= 60:
                    raise HTTPException(
                        422, "纪要原文单项超过5000字或栏目超过60项，请人工选取并校对原文"
                    )
                start = offset + match.start(1)
                result[key].append(
                    {"text": quote, "quote": quote, "start": start, "end": start + len(quote)}
                )
                break
        offset += len(line)
    return result


def validate_minutes(transcript: str, minutes: dict[str, Any]) -> None:
    """所有摘录必须精确回查当前文本；更换原文后旧摘录不能沿用。"""
    for key in MINUTES_LABELS:
        for note in minutes.get(key, []):
            start, end, quote = note["start"], note["end"], note["quote"]
            if (
                not quote.strip()
                or start >= end
                or end > len(transcript)
                or transcript[start:end] != quote
            ):
                raise HTTPException(422, "纪要摘录与原文位置不一致，请重新定位")


def minutes_missing(record: Any) -> list[str]:
    """缺项不能用空白、零值或模型补写掩盖。"""
    missing = []
    for key, labels in MINUTES_LABELS.items():
        if not (record.minutes or {}).get(key):
            missing.append(labels[0] + "待补")
    if not record.held_on:
        missing.append("实际学习日期待补")
    if not record.host:
        missing.append("主持人待补")
    if not record.participants:
        missing.append("参学记录待补")
    if not record.transcript:
        missing.append("原始文本待补")
    return missing


def reset_review(record: Any) -> None:
    """修改内容必须重新送审；旧证据保存在修订表中。"""
    record.review_status = "draft"
    record.submitted_by = None
    record.reviewed_by = None
    record.reviewed_at = None
    record.review_comment = ""


def apply_review(record: Any, user_id: str, decision: str, comment: str) -> None:
    """只能审核已提交的当前版本，审核人不得审核自己提交的内容。"""
    if record.review_status != "pending":
        raise HTTPException(409, "当前内容不在待审核状态")
    if record.submitted_by == user_id:
        raise HTTPException(403, "请由另一位有权限的组织人员审核")
    record.review_status = decision
    record.reviewed_by = user_id
    record.reviewed_at = utc_now()
    record.review_comment = comment
