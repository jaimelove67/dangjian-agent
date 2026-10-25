"""Generate the one-time default password used by approved reset requests."""

from __future__ import annotations

import re

from pypinyin import Style, lazy_pinyin

_ASCII_ALNUM = re.compile(r"[^a-z0-9]", re.IGNORECASE)


def _initials(value: str, label: str) -> str:
    """Return lowercase pinyin initials, retaining ASCII letters and digits."""

    text = "".join(str(value or "").split())
    if not text:
        raise ValueError(f"{label}不能为空")
    initials = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower()
    initials = _ASCII_ALNUM.sub("", initials)
    if not initials:
        raise ValueError(f"{label}无法生成拼音首字母")
    return initials


def approved_reset_password(school_name: str, user_name: str) -> str:
    """Build ``school-initials_user-initials`` for a temporary reset password."""

    password = f"{_initials(school_name, '学校名称')}_{_initials(user_name, '姓名')}"
    if len(password.encode("utf-8")) > 72:
        raise ValueError("学校名称和姓名过长，无法生成有效的默认密码")
    return password
