"""ORM 记录到 JSON 快照的通用序列化，供业务服务生成只追加版本快照。"""

from typing import Any, cast

from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect


def record_snapshot(record: Any) -> dict[str, Any]:
    """把一条 ORM 记录序列化为版本快照，且**不读取未加载的列**。

    异步会话里读取延迟列（如材料二进制 ``content``）或过期属性会触发一次同步
    懒加载 SQL，SQLAlchemy 直接抛 ``MissingGreenlet``；顺带把大字段塞进 JSON 也
    会让响应异常膨胀。因此已持久化（或已脱离会话）的对象只取当前已加载的列，
    未加载的列在快照中不出现。

    Args:
        record: 任意 SQLAlchemy 映射实例。

    Returns:
        列名到 JSON 可序列化值的映射，不含本次未加载的延迟列。

    Note:
        新建但尚未 flush 的对象没有可回查的数据库行，未赋值列直接按 ``None``
        保留，快照键集合与旧实现一致；只有持久化对象的未加载列会被剔除。
    """
    state = inspect(record)
    skip = state.unloaded if (state.persistent or state.detached) else set()
    data = {
        column.key: getattr(record, column.key)
        for column in record.__table__.columns
        if column.key not in skip
    }
    return cast(dict[str, Any], jsonable_encoder(data))
