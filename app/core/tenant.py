"""多租户隔离模块

实现框架文档 9.2 与开发规范 9.4 的租户隔离机制：

- 租户上下文基于 ``contextvars`` 存储于请求生命周期内；
- 写入（flush）时自动为新增对象注入 ``tenant_id``，缺失则拒绝；
- 查询（SELECT）时自动追加 ``tenant_id`` 条件，业务代码无需手工拼接；
- 提供显式过滤器 ``apply_tenant_filter`` 供手写查询复用。

租户标识只能来自**登录态**（见框架文档 8.2），不接收前端传入。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional

from sqlalchemy import Select, event, inspect
from sqlalchemy.orm import Session, with_loader_criteria

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """租户隔离校验失败"""


# 当前请求上下文（由鉴权依赖或中间件写入）
current_tenant_id: ContextVar[Optional[str]] = ContextVar("current_tenant_id", default=None)
current_user_id: ContextVar[Optional[str]] = ContextVar("current_user_id", default=None)
current_data_level: ContextVar[Optional[str]] = ContextVar("current_data_level", default=None)

# 系统级操作（迁移/脚本/跨租户管理）可临时绕过自动过滤
_bypass_tenant_filter: ContextVar[bool] = ContextVar("_bypass_tenant_filter", default=False)


# ==================== 上下文管理 ====================
def set_tenant_context(
    tenant_id: str,
    user_id: Optional[str] = None,
    data_level: Optional[str] = None,
) -> None:
    """写入当前租户上下文"""
    if not tenant_id:
        raise TenantIsolationError("租户 ID 不能为空")
    current_tenant_id.set(str(tenant_id))
    current_user_id.set(str(user_id) if user_id else None)
    current_data_level.set(data_level)


def clear_tenant_context() -> None:
    """清空当前租户上下文"""
    current_tenant_id.set(None)
    current_user_id.set(None)
    current_data_level.set(None)


def get_tenant_id() -> Optional[str]:
    """获取当前租户 ID"""
    return current_tenant_id.get()


@contextmanager
def tenant_context(
    tenant_id: str,
    user_id: Optional[str] = None,
    data_level: Optional[str] = None,
) -> Iterator[None]:
    """租户上下文管理器（用于脚本 / 后台任务）

    退出时恢复为 None，避免上下文泄漏到后续请求。
    """
    set_tenant_context(tenant_id, user_id, data_level)
    try:
        yield
    finally:
        clear_tenant_context()


@contextmanager
def bypass_tenant_filter() -> Iterator[None]:
    """临时绕过自动租户过滤（仅限系统级 / 迁移 / 跨租户统计场景）"""
    token = _bypass_tenant_filter.set(True)
    try:
        yield
    finally:
        _bypass_tenant_filter.reset(token)


# ==================== 查询过滤 ====================
def apply_tenant_filter(
    statement: Select, entity: Any, tenant_id: Optional[str] = None
) -> Select:
    """为查询语句显式追加租户条件

    Args:
        statement: SQLAlchemy select 语句
        entity: 目标映射类（需含 tenant_id 列）
        tenant_id: 租户 ID，默认取当前上下文

    Returns:
        追加了租户过滤的语句

    Raises:
        TenantIsolationError: 上下文无租户且未显式传入
    """
    tid = tenant_id or current_tenant_id.get()
    if not tid:
        raise TenantIsolationError("租户 ID 缺失，无法执行租户过滤查询")
    return statement.where(entity.tenant_id == tid)


def _mapper_has_tenant_id(instance: Any) -> bool:
    """判断实例对应的映射类是否包含 tenant_id 列"""
    try:
        return "tenant_id" in inspect(instance).mapper.columns
    except Exception:  # pragma: no cover - 非映射对象
        return False


# ==================== SQLAlchemy 事件监听 ====================
@event.listens_for(Session, "before_flush")
def _inject_tenant_id_on_flush(
    session: Session, flush_context: Any, instances: Any
) -> None:
    """写入前自动注入 tenant_id（缺失则拒绝）"""
    default_tenant = current_tenant_id.get()
    for instance in session.new:
        if not _mapper_has_tenant_id(instance):
            continue
        if getattr(instance, "tenant_id", None):
            continue
        if not default_tenant:
            raise TenantIsolationError(
                f"新增 {type(instance).__name__} 缺少 tenant_id，且当前无租户上下文"
            )
        instance.tenant_id = default_tenant


def _tenant_criteria(tenant_id: str) -> Callable[[Any], Any]:
    """构造租户过滤条件（供 with_loader_criteria 使用）"""
    def _criteria(cls: Any) -> Any:
        return cls.tenant_id == tenant_id

    return _criteria


@event.listens_for(Session, "do_orm_execute")
def _auto_filter_by_tenant(execute_state: Any) -> None:
    """查询前自动追加租户条件（仅在存在租户上下文且未绕过时生效）"""
    if not execute_state.is_select:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    if _bypass_tenant_filter.get(False):
        return

    tenant_id = current_tenant_id.get()
    if not tenant_id:
        return

    entities = []
    for description in execute_state.statement.column_descriptions:
        entity = description.get("entity")
        if entity is not None and hasattr(entity, "tenant_id"):
            entities.append(entity)

    if not entities:
        return

    options = [
        with_loader_criteria(entity, _tenant_criteria(tenant_id), include_aliases=True)
        for entity in entities
    ]
    execute_state.statement = execute_state.statement.options(*options)
