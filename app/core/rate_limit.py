"""Redis 原子固定窗口限流；生产依赖故障拒绝请求，测试回退有界内存。"""

import hashlib
import time
from collections import OrderedDict

from fastapi import HTTPException, Request

from app.core.cache import redis_manager
from app.core.config import settings

_windows: OrderedDict[str, tuple[int, int]] = OrderedDict()
_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return n
"""


async def check_rate_limit(request: Request) -> None:
    path = request.url.path
    if not path.startswith("/api/v1/") or path in {
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }:
        return
    ip = request.client.host if request.client else "unknown"
    expensive = any(part in path for part in ("/qa", "/embed", "/generate", "/batch", "/jobs"))
    category = "login" if path.endswith("/auth/login") else "model" if expensive else "api"
    limit = {
        "login": settings.LOGIN_RATE_LIMIT_PER_MINUTE,
        "model": settings.MODEL_RATE_LIMIT_PER_MINUTE,
        "api": settings.RATE_LIMIT_PER_MINUTE,
    }[category]
    identity = hashlib.sha256(ip.encode()).hexdigest()
    await acquire(category, identity, limit)


async def acquire(category: str, identity: str, limit: int) -> None:
    window = int(time.time() // 60)
    key = f"rate:{category}:{identity}:{window}"
    try:
        count = int(await redis_manager.client.eval(_SCRIPT, 1, key))
    except Exception as exc:
        if settings.ENV == "production":
            raise HTTPException(503, "运行保护依赖暂不可用") from exc
        if key not in _windows:
            while _windows and (
                len(_windows) >= 10000 or next(iter(_windows.values()))[0] < window
            ):
                _windows.popitem(last=False)
        _, previous = _windows.get(key, (window, 0))
        count = previous + 1
        _windows[key] = (window, count)
    if count > limit:
        raise HTTPException(429, "请求过于频繁，请稍后重试", headers={"Retry-After": "60"})


async def check_model_budget() -> None:
    """统一模型入口同时约束HTTP请求、重试与后台批量任务。"""
    from app.core.config import tenant_config
    from app.core.tenant import get_tenant_id

    tenant_id = get_tenant_id()
    if tenant_id:
        school = tenant_config.school_id(tenant_id) or tenant_id
        await acquire(
            "model_calls",
            hashlib.sha256(school.encode()).hexdigest(),
            settings.MODEL_CALL_LIMIT_PER_MINUTE,
        )
