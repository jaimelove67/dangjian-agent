"""日志及审计摘要脱敏；正文只记录不可逆摘要和长度。"""

import hashlib
import json
import re
import uuid
from typing import Any

PRIVATE_FIELDS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "content",
    "text",
    "question",
    "answer",
    "prompt",
    "response",
    "snapshot",
    "opinion",
    "name",
    "user_name",
    "phone",
    "email",
    "remark",
    "minutes",
    "agenda",
    "summary",
    "original",
    "materials",
    "context",
    "error",
    "exception",
    "exc_info",
    "stack",
}


def summary(value: Any) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def audit_summary(value: Any) -> dict[str, Any]:
    """Keep immutable version pointers and deletion flags, hashing all business content."""
    result = summary(value)
    if not isinstance(value, dict):
        return result
    for field in ("revision", "content_revision", "config_version"):
        item = value.get(field)
        if type(item) is int and item >= 0:
            result[field] = item
    if type(value.get("is_deleted")) is bool:
        result["is_deleted"] = value["is_deleted"]
    snapshot_id = value.get("snapshot_id")
    if isinstance(snapshot_id, str):
        try:
            result["snapshot_id"] = str(uuid.UUID(snapshot_id))
        except ValueError:
            pass
    return result


def redact(value: Any, *, level: int = 0) -> Any:
    if level > 8:
        return summary(value)
    if isinstance(value, dict):
        return {
            str(key): (
                summary(item)
                if str(key).lower() in PRIVATE_FIELDS
                or any(word in str(key).lower() for word in ("secret", "password", "token"))
                else redact(item, level=level + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [redact(item, level=level + 1) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_.-]+", r"\1[redacted]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[token]", value)
    value = re.sub(
        r"(?i)(password|api_key|secret|token)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", value
    )
    value = re.sub(r"([a-z]+://)[^/\s:@]+:[^@\s/]+@", r"\1[credentials]@", value)
    return value
