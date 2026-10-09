"""配置加载与回退逻辑测试"""
import pytest
from unittest.mock import patch

from app.core.config import Settings, TenantConfig, get_settings


class TestSettings:
    """配置加载测试"""

    def test_default_settings(self):
        """测试：默认配置加载成功"""
        settings = Settings()

        assert settings.PROJECT_NAME == "党建工作智能体"
        assert settings.VERSION == "1.0.0"
        assert settings.ENV == "development"
        assert settings.DEBUG is True

    def test_env_validation(self):
        """测试：环境变量验证"""
        with pytest.raises(ValueError):
            Settings(ENV="invalid_env")

    def test_log_level_validation(self):
        """测试：日志级别验证"""
        with pytest.raises(ValueError):
            Settings(LOG_LEVEL="INVALID")

    def test_settings_singleton(self):
        """测试：配置单例模式"""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2


class TestTenantConfig:
    """租户配置测试"""

    def test_get_global_default(self):
        """测试：获取全局默认配置"""
        tenant_config = TenantConfig()

        value = tenant_config.get("tenant_001", "retrieval_top_k")

        assert value == 10  # 应该返回全局默认值

    def test_get_tenant_override(self):
        """测试：租户配置覆盖全局配置"""
        tenant_config = TenantConfig()

        # 设置租户配置
        tenant_config.set("tenant_001", "retrieval_top_k", 20)

        # 获取租户配置
        value = tenant_config.get("tenant_001", "retrieval_top_k")

        assert value == 20  # 应该返回租户配置

    def test_get_default_value(self):
        """测试：不存在的配置返回默认值"""
        tenant_config = TenantConfig()

        value = tenant_config.get("tenant_001", "non_existent_key", "default_value")

        assert value == "default_value"

    def test_reload_tenant_config(self):
        """测试：重新加载租户配置"""
        tenant_config = TenantConfig()

        # 设置租户配置
        tenant_config.set("tenant_001", "retrieval_top_k", 20)

        # 重新加载（清除缓存）
        tenant_config.reload("tenant_001")

        # 再次获取应该返回全局默认值
        value = tenant_config.get("tenant_001", "retrieval_top_k")

        assert value == 10  # 应该返回全局默认值

    def test_set_multiple_keys(self):
        """测试：设置多个配置项"""
        tenant_config = TenantConfig()

        tenant_config.set("tenant_001", "retrieval_top_k", 20)
        tenant_config.set("tenant_001", "rerank_top_k", 3)

        assert tenant_config.get("tenant_001", "retrieval_top_k") == 20
        assert tenant_config.get("tenant_001", "rerank_top_k") == 3

    def test_different_tenants(self):
        """测试：不同租户的配置隔离"""
        tenant_config = TenantConfig()

        tenant_config.set("tenant_001", "retrieval_top_k", 20)
        tenant_config.set("tenant_002", "retrieval_top_k", 30)

        assert tenant_config.get("tenant_001", "retrieval_top_k") == 20
        assert tenant_config.get("tenant_002", "retrieval_top_k") == 30
