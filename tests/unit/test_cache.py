"""缓存服务测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.cache import (
    CacheService,
    make_session_key,
    make_config_key,
    make_tenant_key,
)


@pytest.fixture
def mock_redis():
    """模拟 Redis 客户端"""
    return AsyncMock()


@pytest.fixture
def cache_service(mock_redis):
    """创建缓存服务"""
    return CacheService(mock_redis)


class TestCacheService:
    """缓存服务测试"""

    @pytest.mark.asyncio
    async def test_get_success(self, cache_service, mock_redis):
        """测试：成功获取缓存"""
        mock_redis.get.return_value = '{"key": "value"}'

        result = await cache_service.get("test_key")

        assert result == {"key": "value"}
        mock_redis.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_get_not_found(self, cache_service, mock_redis):
        """测试：缓存不存在返回 None"""
        mock_redis.get.return_value = None

        result = await cache_service.get("test_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_non_json_value(self, cache_service, mock_redis):
        """测试：获取非 JSON 值"""
        mock_redis.get.return_value = "plain_string"

        result = await cache_service.get("test_key")

        assert result == "plain_string"

    @pytest.mark.asyncio
    async def test_set_dict_value(self, cache_service, mock_redis):
        """测试：设置字典值"""
        test_value = {"key": "value"}

        result = await cache_service.set("test_key", test_value)

        assert result is True
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, cache_service, mock_redis):
        """测试：设置带过期时间的缓存"""
        test_value = {"key": "value"}

        result = await cache_service.set("test_key", test_value, ttl=3600)

        assert result is True
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_success(self, cache_service, mock_redis):
        """测试：删除缓存成功"""
        result = await cache_service.delete("test_key")

        assert result is True
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_exists_true(self, cache_service, mock_redis):
        """测试：缓存存在"""
        mock_redis.exists.return_value = 1

        result = await cache_service.exists("test_key")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, cache_service, mock_redis):
        """测试：缓存不存在"""
        mock_redis.exists.return_value = 0

        result = await cache_service.exists("test_key")

        assert result is False

    @pytest.mark.asyncio
    async def test_expire(self, cache_service, mock_redis):
        """测试：设置过期时间"""
        result = await cache_service.expire("test_key", 3600)

        assert result is True
        mock_redis.expire.assert_called_once_with("test_key", 3600)

    @pytest.mark.asyncio
    async def test_get_ttl(self, cache_service, mock_redis):
        """测试：获取剩余过期时间"""
        mock_redis.ttl.return_value = 1800

        result = await cache_service.get_ttl("test_key")

        assert result == 1800


class TestCacheKeyMakers:
    """缓存键生成器测试"""

    def test_make_session_key(self):
        """测试：生成会话缓存键"""
        key = make_session_key("sess_123")
        assert key == "session:sess_123"

    def test_make_config_key(self):
        """测试：生成配置缓存键"""
        key = make_config_key("tenant_001", "retrieval_top_k")
        assert key == "config:tenant_001:retrieval_top_k"

    def test_make_tenant_key(self):
        """测试：生成租户缓存键"""
        key = make_tenant_key("tenant_001")
        assert key == "tenant:tenant_001"
