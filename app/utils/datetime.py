"""日期时间工具函数"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional


def to_date(value: Any) -> Optional[date]:
    """转换为日期类型

    Args:
        value: 输入值（None / date / datetime / ISO格式字符串）

    Returns:
        date对象，或None

    Raises:
        ValueError: 日期格式无效
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError(f"无法解析日期: {value!r}")
