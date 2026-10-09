"""数据脱敏工具

满足框架文档 9.3 与开发规范 9.1：对身份证号、手机号、邮箱、各类编号等在
**输出与日志**中自动脱敏，避免敏感信息泄露。

所有函数对 ``None`` / 空串 / 非字符串输入均安全返回。
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

# 默认需要脱敏的字段名（大小写不敏感）
DEFAULT_SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "id_card",
    "id_number",
    "idcard",
    "phone",
    "mobile",
    "phone_number",
    "email",
    "bank_card",
    "bank_account",
})


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def mask_id_card(value: Any) -> Any:
    """身份证号脱敏：保留前 6 位与后 4 位"""
    text = _as_text(value)
    if text is None:
        return value
    if len(text) < 10:
        return "***"
    return f"{text[:6]}********{text[-4:]}"


def mask_phone(value: Any) -> Any:
    """手机号脱敏：保留前 3 位与后 4 位"""
    text = _as_text(value)
    if text is None:
        return value
    if len(text) < 7:
        return "***"
    return f"{text[:3]}****{text[-4:]}"


def mask_email(value: Any) -> Any:
    """邮箱脱敏：保留首字母与域名"""
    text = _as_text(value)
    if text is None:
        return value
    parts = text.split("@")
    if len(parts) != 2 or not parts[0]:
        return "***"
    return f"{parts[0][0]}***@{parts[1]}"


def mask_name(value: Any) -> Any:
    """姓名脱敏：保留姓氏，其余用 * 代替"""
    text = _as_text(value)
    if text is None:
        return value
    if len(text) <= 1:
        return text
    return text[0] + "*" * (len(text) - 1)


def mask_number(value: Any, head: int = 4, tail: int = 4) -> Any:
    """通用编号脱敏：保留首尾若干位（如学号、工号、银行卡号）"""
    text = _as_text(value)
    if text is None:
        return value
    if len(text) <= head + tail:
        return "*" * len(text)
    return f"{text[:head]}{'*' * (len(text) - head - tail)}{text[-tail:]}"


# 字段名 → 脱敏函数
_FIELD_MASKERS = {
    "id_card": mask_id_card,
    "id_number": mask_id_card,
    "idcard": mask_id_card,
    "phone": mask_phone,
    "mobile": mask_phone,
    "phone_number": mask_phone,
    "email": mask_email,
    "bank_card": mask_number,
    "bank_account": mask_number,
    "name": mask_name,
}


def mask_field(field_name: str, value: Any) -> Any:
    """按字段名选择合适的脱敏函数；无匹配则原样返回"""
    masker = _FIELD_MASKERS.get(field_name.lower())
    return masker(value) if masker else value


def mask_dict(
    data: Any,
    sensitive_fields: Optional[Iterable[str]] = None,
) -> Any:
    """递归脱敏字典 / 列表中的敏感字段

    Args:
        data: 待脱敏数据（dict / list / 标量）
        sensitive_fields: 需要脱敏的字段名集合，默认 ``DEFAULT_SENSITIVE_FIELDS``

    Returns:
        脱敏后的副本（不修改原对象）
    """
    fields = {f.lower() for f in (sensitive_fields or DEFAULT_SENSITIVE_FIELDS)}

    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in fields:
                masked[key] = mask_field(key, value)
            else:
                masked[key] = mask_dict(value, fields)
        return masked
    if isinstance(data, list):
        return [mask_dict(item, fields) for item in data]
    if isinstance(data, tuple):
        return tuple(mask_dict(item, fields) for item in data)
    return data
