"""Distributed write quiescence for controlled backups; fail closed when enabled."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException

from app.core.cache import redis_manager
from app.core.config import settings

ENTER = """
if redis.call('exists', KEYS[1]) == 1 then return 0 end
redis.call('incr', KEYS[2]); redis.call('expire', KEYS[2], 600); return 1
"""
LEAVE = """
if tonumber(redis.call('get', KEYS[1]) or '0') > 0 then return redis.call('decr', KEYS[1]) end
return 0
"""
UNLOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


def keys() -> tuple[str, str]:
    prefix = "maintenance:" + hashlib.sha256(settings.DATABASE_URL.encode()).hexdigest()[:24]
    return prefix + ":lock", prefix + ":active"


async def enter() -> bool:
    if not settings.BACKUP_API_ENABLED:
        return True
    lock, active = keys()
    return bool(await redis_manager.client.eval(ENTER, 2, lock, active))


async def leave() -> None:
    if settings.BACKUP_API_ENABLED:
        await redis_manager.client.eval(LEAVE, 1, keys()[1])


@asynccontextmanager
async def quiescence() -> AsyncIterator[None]:
    lock, active = keys()
    token = uuid.uuid4().hex
    if not await redis_manager.client.set(lock, token, nx=True, ex=900):
        raise HTTPException(409, "已有维护任务正在执行")
    try:
        for _ in range(300):
            if int(await redis_manager.client.get(active) or 0) == 0:
                break
            await asyncio.sleep(0.1)
        else:
            raise HTTPException(409, "仍有业务请求未结束，本次维护未执行")
        yield
    finally:
        await redis_manager.client.eval(UNLOCK, 1, lock, token)
