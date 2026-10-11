"""应用配置模块

支持从环境变量和配置文件加载，支持多租户配置覆盖。
"""

from functools import lru_cache
from typing import Any, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # ==================== 基础配置 ====================
    PROJECT_NAME: str = "党建工作智能体"
    VERSION: str = "1.0.0"
    ENV: str = Field(default="development", description="运行环境")
    DEBUG: bool = Field(default=False, description="调试模式")
    MAX_UPLOAD_SIZE: int = Field(default=10 * 1024 * 1024, gt=0, description="上传大小上限（字节）")

    # ==================== 服务配置 ====================
    HOST: str = Field(default="0.0.0.0", description="服务地址")
    PORT: int = Field(default=8000, description="服务端口")
    ALLOWED_HOSTS: list[str] = Field(default=["*"], description="允许的主机")

    # ==================== 安全配置 ====================
    SECRET_KEY: str = Field(
        default="dev_secret_key_change_in_production", description="应用密钥（用于 JWT 签名等）"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT 签名算法")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="访问令牌有效期（分钟）")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="刷新令牌有效期（天）")
    BCRYPT_ROUNDS: int = Field(default=12, description="密码哈希成本因子")

    # ==================== 数据库配置 ====================
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://party_user:dev_password@localhost:5432/party_agent_dev",
        description="数据库连接URL",
    )
    DB_POOL_SIZE: int = Field(default=20, description="数据库连接池大小")
    DB_MAX_OVERFLOW: int = Field(default=10, description="连接池最大溢出数")
    DB_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间（秒）")

    # ==================== Redis 配置 ====================
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis 连接URL")
    REDIS_POOL_SIZE: int = Field(default=10, description="Redis 连接池大小")
    REDIS_CACHE_TTL: int = Field(default=3600, description="缓存默认过期时间（秒）")

    # ==================== 会话配置 ====================
    SESSION_TTL_SECONDS: int = Field(default=3600, description="问答会话有效期（秒）")
    SESSION_MAX_TURNS: int = Field(default=5, description="会话保留的最大轮次")

    # ==================== 问答链配置 ====================
    NO_EVIDENCE_THRESHOLD: float = Field(
        default=0.5, description="无依据判定阈值（检索片段最高分低于该值视为无依据）"
    )

    # ==================== 日志配置 ====================
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_FORMAT: str = Field(default="json", description="日志格式: json/text")

    # ==================== 模型配置 ====================
    # 阿里云 DashScope API Key（支持通义千问和DeepSeek）
    DASHSCOPE_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        description="阿里云 DashScope API Key",
    )
    DASHSCOPE_BASE_URL: str = Field(
        default="https://dashscope.aliyuncs.com",
        description="百炼 API Host（不含接口路径；可使用业务空间地域域名）",
    )
    MODEL_TIMEOUT_SECONDS: float = Field(default=45, gt=0, description="模型调用超时（秒）")

    # LLM 模型配置
    LLM_MODEL_NAME: str = Field(
        default="deepseek-v3",
        validation_alias=AliasChoices("CHAT_MODEL", "LLM_MODEL_NAME"),
        description="LLM 模型名称",
    )
    LLM_MAX_TOKENS: int = Field(default=4096, description="LLM 最大token数")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM 温度参数")

    # Embedding 模型配置（阿里云）
    EMBEDDING_MODEL_NAME: str = Field(
        default="qwen3.7-text-embedding-flash",
        validation_alias=AliasChoices("EMBED_MODEL", "EMBEDDING_MODEL_NAME"),
        description="向量化模型名称",
    )

    # 重排模型配置（阿里云）
    RERANKER_MODEL_NAME: str = Field(
        default="qwen3.7-text-rerank",
        validation_alias=AliasChoices("RERANK_MODEL", "RERANKER_MODEL_NAME"),
        description="重排模型名称",
    )

    # ==================== 检索配置 ====================
    RETRIEVAL_TOP_K: int = Field(default=10, description="初检条数")
    RERANK_TOP_K: int = Field(default=5, description="重排后保留条数")
    EXCLUDE_EXPIRED_BY_DEFAULT: bool = Field(default=True, description="默认排除失效文件")

    # ==================== 安全配置 ====================
    ENABLE_DATA_LEVEL_GATEWAY: bool = Field(default=True, description="启用数据级别出网闸门")
    ALLOWED_EXTERNAL_MODELS: list[str] = Field(default=[], description="允许的外部模型域名")

    # ==================== 业务配置 ====================
    ACTIVIST_TRAINING_DAYS: int = Field(default=365, description="入党积极分子培养期上限（天）")
    PROBATIONARY_PERIOD_DAYS: int = Field(default=365, description="预备党员预备期上限（天）")
    ASSESSMENT_REMINDER_SCAN_SECONDS: int = Field(
        default=300, ge=60, le=86400, description="考核站内提醒扫描周期（秒）"
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

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """兼容部署包中的 PostgreSQL URL，运行时始终使用异步驱动。"""
        for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @field_validator("DASHSCOPE_BASE_URL")
    @classmethod
    def validate_cloud_host(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("DASHSCOPE_BASE_URL 必须是 HTTPS API Host，不含接口路径或凭据")
        return value.rstrip("/")

    @model_validator(mode="after")
    def production_debug(self) -> "Settings":
        """生产环境不暴露调试入口或 SQL 参数。"""
        if self.ENV == "production":
            self.DEBUG = False
        return self

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
        self._parents: dict[str, Optional[str]] = {}

    def get(self, tenant_id: str, key: str, default: Any = None) -> Any:
        """获取租户配置

        Args:
            tenant_id: 租户ID
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        visited: set[str] = set()
        current = tenant_id
        while current and current not in visited:
            visited.add(current)
            if key in self._cache.get(current, {}):
                return self._cache[current][key]
            current = self._parents.get(current)

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

    def set(self, tenant_id: str, key: str, value: Any) -> None:
        """设置租户配置

        Args:
            tenant_id: 租户ID
            key: 配置键
            value: 配置值
        """
        if tenant_id not in self._cache:
            self._cache[tenant_id] = {}

        self._cache[tenant_id][key] = value

    async def load(self, db, tenant_id: str) -> None:
        """逐请求加载当前租户及其父级，跨进程配置变更也能及时生效。"""
        from sqlalchemy import select

        from app.core.tenant import bypass_tenant_filter
        from app.models.tenant import Tenant

        current, visited = tenant_id, set()
        with bypass_tenant_filter():
            while current:
                if current in visited or len(visited) >= 20:
                    raise ValueError("租户配置继承存在循环或层级过深")
                visited.add(current)
                tenant = (
                    await db.execute(
                        select(Tenant).where(Tenant.id == current, Tenant.is_deleted.is_(False))
                    )
                ).scalar_one_or_none()
                self._cache[current] = dict(tenant.config or {}) if tenant else {}
                self._parents[current] = tenant.parent_id if tenant else None
                current = self._parents[current]

    async def save(self, db, tenant_id: str, values: dict[str, Any]) -> None:
        """保留未更新键，写入数据库后重新加载；提交由调用方管理。"""
        from sqlalchemy import select

        from app.models.tenant import Tenant

        tenant = (
            await db.execute(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise LookupError("当前账号所属租户尚未登记，请先完成租户初始化")
        tenant.config = {**(tenant.config or {}), **values}
        await db.flush()
        await self.load(db, tenant_id)

    def reload(self, tenant_id: str) -> None:
        """重新加载租户配置

        Args:
            tenant_id: 租户ID
        """
        # 清除缓存
        if tenant_id in self._cache:
            del self._cache[tenant_id]
        self._parents.pop(tenant_id, None)


# 全局租户配置管理器
tenant_config = TenantConfig()
