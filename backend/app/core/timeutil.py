"""时间展示口径（导出与界面说明共用）。

库里的时间列是 UTC 朴素时间（``datetime.utcnow()``），而复核者看的是北京时间：不换算
就会出现"谁在什么时候做的"差 8 小时——审计与台账导出最忌讳这种偏移。中国无夏令时，
固定 +08:00 即可，不引入时区库依赖（Windows 上 ``zoneinfo`` 还需额外 tzdata）。

注意：只做**展示**换算；存储与比较一律保持 UTC 朴素时间。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

#: 展示用固定偏移（北京时间）
BEIJING = timezone(timedelta(hours=8))


def as_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    """带时区的输入换算成 UTC 朴素时间（与库内存储口径一致）；朴素输入原样返回

    接口收到的 ``+08:00`` 输入必须换算后再与库里的 UTC 列比较，否则边界会错 8 小时。
    """
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def local_time(value: Optional[datetime]) -> str:
    """UTC 朴素时间 → 北京时间文本（分钟精度；空值返回空串，不写 None）"""
    if value is None:
        return ""
    return value.replace(tzinfo=timezone.utc).astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")


def local_now_text() -> str:
    """当前北京时间文本（导出说明里的"导出时间"统一走这里）"""
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")
