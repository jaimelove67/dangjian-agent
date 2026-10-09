"""应用配置"""
from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用基础配置
    APP_NAME: str = "党建工作智能体"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # 数据库配置
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://user:pass@localhost/dangjian",
        description="数据库连接URL",
    )

    # Redis配置
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis连接URL",
    )

    # JWT配置
    SECRET_KEY: str = Field(
        default="your-secret-key-here-change-in-production",
        description="JWT密钥",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 文件上传配置
    MAX_UPLOAD_SIZE: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="文件上传大小限制（字节）",
    )

    # 知识库配置
    KNOWLEDGE_CHUNK_SIZE: int = Field(
        default=800,
        description="知识文档切分片段大小",
    )
    KNOWLEDGE_CHUNK_OVERLAP: int = Field(
        default=100,
        description="知识文档切分重叠区大小",
    )

    # LLM配置
    LLM_API_KEY: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None

    # 向量数据库配置
    VECTOR_DIMENSION: int = Field(
        default=768,
        description="向量维度",
    )


settings = Settings()
