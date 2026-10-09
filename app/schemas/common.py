"""统一响应结构（见开发规范 7.2）

所有接口统一返回：``code / message / data / trace_id``。
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应"""
    code: int = 0
    message: str = "success"
    data: Optional[T] = None
    trace_id: Optional[str] = None


class ErrorCode:
    """业务错误码（见开发规范 7.3）"""
    SUCCESS = 0
    PARAM_ERROR = 40001
    UNAUTHORIZED = 40101
    FORBIDDEN = 40301
    TENANT_ISOLATION = 40302
    NOT_FOUND = 40401
    CONFLICT = 40901
    BUSINESS_ERROR = 42201
    RATE_LIMITED = 42901
    SERVER_ERROR = 50001
    SERVICE_UNAVAILABLE = 50301
