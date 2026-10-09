"""应用配置模块

支持从环境变量和配置文件加载，支持多租户配置覆盖。
"""
import os
from typing import Optional, Any
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # ==================== 基础配置 ====================
    PROJECT_NAME: str = "党建工作智能体"
    VERSION: str = "1.0.0"
    ENV: str = Field(default="development", description="运行环境")
    DEBUG: bool = Field(default=True, description="调试模式")

    # ==================== 服务配置 ====================
    HOST: str = Field(default="0.0.0.0", description="服务地址")
    PORT: int = Field(default=8000, description="服务端口")
    ALLOWED_HOSTS: list[str] = Field(default=["*"], description="允许的主机")

    # ==================== 安全配置 ====================
    SECRET_KEY: str = Field(
        default="dev_secret_key_change_in_production",
        description="应用密钥（用于 JWT 签名等）"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT 签名算法")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, description="访问令牌有效期（分钟）"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="刷新令牌有效期（天）"
    )
    BCRYPT_ROUNDS: int = Field(default=12, description="密码哈希成本因子")

    # ==================== 数据库配置 ====================
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://party_user:dev_password@localhost:5432/party_agent_dev",
        description="数据库连接URL"
    )
    DB_POOL_SIZE: int = Field(default=20, description="数据库连接池大小")
    DB_MAX_OVERFLOW: int = Field(default=10, description="连接池最大溢出数")
    DB_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间（秒）")

    # ==================== Redis 配置 ====================
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接URL"
    )
    REDIS_POOL_SIZE: int = Field(default=10, description="Redis 连接池大小")
    REDIS_CACHE_TTL: int = Field(default=3600, description="缓存默认过期时间（秒）")

    # ==================== 会话配置 ====================
    SESSION_TTL_SECONDS: int = Field(default=3600, description="问答会话有效期（秒）")
    SESSION_MAX_TURNS: int = Field(default=5, description="会话保留的最大轮次")

    # ==================== 日志配置 ====================
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_FORMAT: str = Field(default="json", description="日志格式: json/text")

    # ==================== 模型配置 ====================
    # 阿里云 DashScope API Key（支持通义千问和DeepSeek）
    DASHSCOPE_API_KEY: Optional[str] = Field(default=None, description="阿里云 DashScope API Key")

    # LLM 模型配置
    LLM_MODEL_NAME: str = Field(
        default="deepseek-v4.1-flash",
        description="LLM 模型名称"
    )
    LLM_MAX_TOKENS: int = Field(default=4096, description="LLM 最大token数")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM 温度参数")

    # Embedding 模型配置（阿里云）
    EMBEDDING_MODEL_NAME: str = Field(
        default="qwen3.7-text-embedding-flash",
        description="向量化模型名称"
    )

    # 重排模型配置（阿里云）
    RERANKER_MODEL_NAME: str = Field(
        default="qwen3.7-text-rerank",
        description="重排模型名称"
    )

    # ==================== 检索配置 ====================
    RETRIEVAL_TOP_K: int = Field(default=10, description="初检条数")
    RERANK_TOP_K: int = Field(default=5, description="重排后保留条数")
    NO_EVIDENCE_THRESHOLD: float = Field(default=0.5, description="无依据判定阈值")
    EXCLUDE_EXPIRED_BY_DEFAULT: bool = Field(
        default=True,
        description="默认排除失效文件"
    )

    # ==================== 安全配置 ====================
    ENABLE_DATA_LEVEL_GATEWAY: bool = Field(
        default=True,
        description="启用数据级别出网闸门"
    )
    ALLOWED_EXTERNAL_MODELS: list[str] = Field(
        default=[],
        description="允许的外部模型域名"
    )

    # ==================== 业务配置 ====================
    ACTIVIST_TRAINING_DAYS: int = Field(
        default=365,
        description="入党积极分子培养期上限（天）"
    )
    PROBATIONARY_PERIOD_DAYS: int = Field(
        default=365,
        description="预备党员预备期上限（天）"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        """验证环境变量"""
        allowed = ["development", "production", "testing"]
        if v not in allowed:
            raise ValueError(f"ENV must be one of {allowed}")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证日志级别"""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 全局配置实例
settings = get_settings()


class TenantConfig:
    """租户级配置管理

    支持租户级配置覆盖，配置优先级：
    租户配置 > 上级租户配置 > 全局默认配置
    """

    def __init__(self):
        """初始化配置管理器"""
        self._cache: dict[str, dict[str, Any]] = {}
        # TODO: 后续从数据库加载租户配置

    def get(
        self,
        tenant_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        """获取租户配置

        Args:
            tenant_id: 租户ID
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        # 查找租户配置
        if tenant_id in self._cache:
            tenant_config = self._cache[tenant_id]
            if key in tenant_config:
                return tenant_config[key]

        # 查找父级租户配置
        # TODO: 实现租户树查找逻辑

        # 返回全局默认配置
        global_config = {
            "retrieval_top_k": settings.RETRIEVAL_TOP_K,
            "rerank_top_k": settings.RERANK_TOP_K,
            "no_evidence_threshold": settings.NO_EVIDENCE_THRESHOLD,
            "exclude_expired_by_default": settings.EXCLUDE_EXPIRED_BY_DEFAULT,
            "activist_training_days": settings.ACTIVIST_TRAINING_DAYS,
            "probationary_period_days": settings.PROBATIONARY_PERIOD_DAYS,
        }

        return global_config.get(key, default)

    def set(
        self,
        tenant_id: str,
        key: str,
        value: Any
    ) -> None:
        """设置租户配置

        Args:
            tenant_id: 租户ID
            key: 配置键
            value: 配置值
        """
        if tenant_id not in self._cache:
            self._cache[tenant_id] = {}

        self._cache[tenant_id][key] = value
        # TODO: 持久化到数据库

    def reload(self, tenant_id: str) -> None:
        """重新加载租户配置

        Args:
            tenant_id: 租户ID
        """
        # 清除缓存
        if tenant_id in self._cache:
            del self._cache[tenant_id]

        # TODO: 从数据库重新加载


# 全局租户配置管理器
tenant_config = TenantConfig()
