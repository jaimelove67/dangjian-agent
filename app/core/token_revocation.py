"""Redis 令牌吊销：退出覆盖当前登录会话，刷新令牌只能使用一次。"""

import time
import uuid

from app.core.cache import redis_manager
from app.core.config import settings
from app.core.security import TokenError


class AuthStoreUnavailable(Exception):
    """不能访问吊销存储时拒绝认证，避免故障期间恢复已退出的会话。"""


class TokenRevocationStore:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def ensure_available(self) -> None:
        """签发会话前检查读写能力，探针自行过期且不含凭证。"""
        key = f"auth:probe:{uuid.uuid4().hex}"
        try:
            saved = await self.redis.set(key, "1", ex=5)
            readable = await self.redis.exists(key)
        except Exception as exc:
            raise AuthStoreUnavailable("认证存储暂不可用") from exc
        if not saved or not readable:
            raise AuthStoreUnavailable("认证存储暂不可用")

    async def assert_active(self, payload: dict) -> None:
        jti = payload.get("jti")
        if not jti:
            raise TokenError("令牌缺少唯一标识")
        keys = [f"auth:revoked:token:{jti}"]
        if payload.get("sid"):
            keys.append(f"auth:revoked:session:{payload['sid']}")
        try:
            revoked = await self.redis.exists(*keys)
        except Exception as exc:
            raise AuthStoreUnavailable("认证存储暂不可用") from exc
        if revoked:
            raise TokenError("登录状态已退出或令牌已使用")

    async def revoke_session(self, payload: dict) -> None:
        if payload.get("sid"):
            key = f"auth:revoked:session:{payload['sid']}"
            ttl = (
                settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
                + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
        else:
            key = f"auth:revoked:token:{payload['jti']}"
            ttl = max(1, int(payload["exp"] - time.time()))
        try:
            await self.redis.set(key, "1", ex=ttl)
        except Exception as exc:
            raise AuthStoreUnavailable("退出状态未能保存，请重试") from exc

    async def consume_refresh(self, payload: dict) -> None:
        """原子消费旧刷新令牌，阻止重放和并发刷新生成多组令牌。"""
        await self.assert_active(payload)
        if not payload.get("sid"):
            raise TokenError("旧版刷新令牌不支持退出吊销，请重新登录")
        try:
            consumed = await self.redis.set(
                f"auth:revoked:token:{payload['jti']}",
                "1",
                nx=True,
                ex=max(1, int(payload["exp"] - time.time())),
            )
        except Exception as exc:
            raise AuthStoreUnavailable("认证存储暂不可用") from exc
        if not consumed:
            raise TokenError("刷新令牌已使用")


def get_token_revocation_store() -> TokenRevocationStore:
    try:
        return TokenRevocationStore(redis_manager.client)
    except RuntimeError as exc:
        raise AuthStoreUnavailable("认证存储尚未连接") from exc
