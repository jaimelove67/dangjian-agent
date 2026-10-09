"""Redis 缓存管理模块"""
import json
from typing import Any, Optional
import logging

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    """Redis 连接管理器"""

    def __init__(self):
        """初始化 Redis 管理器"""
        self._redis: Optional[Redis] = None

    async def connect(self) -> None:
        """连接 Redis"""
        try:
            self._redis = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=settings.REDIS_POOL_SIZE,
            )
            # 测试连接
            await self._redis.ping()
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """断开 Redis 连接"""
        if self._redis:
            await self._redis.close()
            logger.info("Redis disconnected")

    @property
    def client(self) -> Redis:
        """获取 Redis 客户端"""
        if not self._redis:
            raise RuntimeError("Redis not connected")
        return self._redis


# 全局 Redis 管理器
redis_manager = RedisManager()


class CacheService:
    """缓存服务

    提供统一的缓存接口，支持：
    - 基本的 get/set/delete 操作
    - 自动序列化/反序列化
    - 过期时间管理
    """

    def __init__(self, redis_client: Redis):
        """初始化缓存服务

        Args:
            redis_client: Redis 客户端
        """
        self._redis = redis_client

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在返回 None
        """
        try:
            value = await self._redis.get(key)
            if value is None:
                return None

            # 尝试 JSON 反序列化
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except Exception as e:
            logger.error(f"Failed to get cache key '{key}': {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示永不过期

        Returns:
            是否成功
        """
        try:
            # 序列化值
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value, ensure_ascii=False)
            else:
                serialized_value = str(value)

            # 设置缓存
            if ttl:
                await self._redis.setex(key, ttl, serialized_value)
            else:
                await self._redis.set(key, serialized_value)

            return True

        except Exception as e:
            logger.error(f"Failed to set cache key '{key}': {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存

        Args:
            key: 缓存键

        Returns:
            是否成功
        """
        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete cache key '{key}': {e}")
            return False

    async def exists(self, key: str) -> bool:
        """检查缓存是否存在

        Args:
            key: 缓存键

        Returns:
            是否存在
        """
        try:
            result = await self._redis.exists(key)
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to check cache key '{key}': {e}")
            return False

    async def expire(self, key: str, ttl: int) -> bool:
        """设置过期时间

        Args:
            key: 缓存键
            ttl: 过期时间（秒）

        Returns:
            是否成功
        """
        try:
            await self._redis.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Failed to set expire for key '{key}': {e}")
            return False

    async def get_ttl(self, key: str) -> Optional[int]:
        """获取剩余过期时间

        Args:
            key: 缓存键

        Returns:
            剩余秒数，-1 表示永不过期，-2 表示不存在
        """
        try:
            return await self._redis.ttl(key)
        except Exception as e:
            logger.error(f"Failed to get TTL for key '{key}': {e}")
            return None


def get_cache_service() -> CacheService:
    """获取缓存服务实例

    Returns:
        缓存服务
    """
    return CacheService(redis_manager.client)


# 会话缓存键前缀
SESSION_KEY_PREFIX = "session:"
# 配置缓存键前缀
CONFIG_KEY_PREFIX = "config:"
# 租户缓存键前缀
TENANT_KEY_PREFIX = "tenant:"


def make_session_key(session_id: str) -> str:
    """生成会话缓存键

    Args:
        session_id: 会话ID

    Returns:
        缓存键
    """
    return f"{SESSION_KEY_PREFIX}{session_id}"


def make_config_key(tenant_id: str, config_key: str) -> str:
    """生成配置缓存键

    Args:
        tenant_id: 租户ID
        config_key: 配置键

    Returns:
        缓存键
    """
    return f"{CONFIG_KEY_PREFIX}{tenant_id}:{config_key}"


def make_tenant_key(tenant_id: str) -> str:
    """生成租户缓存键

    Args:
        tenant_id: 租户ID

    Returns:
        缓存键
    """
    return f"{TENANT_KEY_PREFIX}{tenant_id}"
