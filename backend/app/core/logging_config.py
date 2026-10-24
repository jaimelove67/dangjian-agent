"""日志配置模块

实现结构化日志（JSON格式），支持追踪ID、租户ID等上下文信息。
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, MutableMapping, Optional, cast

import structlog

from app.core.config import settings
from app.core.redaction import redact, redact_text


def _safe_event(logger: Any, method: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
    """所有 structlog 输出统一脱敏，供应商异常正文只保留摘要。"""
    protected = dict(event)
    for key in ("error", "exception", "exc_info", "stack"):
        if key in protected:
            from app.core.redaction import summary

            protected[key] = summary(protected[key])
    return cast(dict[str, Any], redact(protected))


class JSONFormatter(logging.Formatter):
    """JSON 格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON

        Args:
            record: 日志记录

        Returns:
            JSON 格式的日志
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加追踪ID
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id

        # 添加租户ID
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id

        # 添加用户ID
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id

        # 添加额外字段
        if hasattr(record, "extra_fields"):
            log_data.update(redact(record.extra_fields))

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = (
                type(record.exc_info[1]).__name__
                if settings.ENV == "production"
                else redact_text(self.formatException(record.exc_info))
            )

        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """文本格式化器（开发环境使用）"""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging() -> None:
    """配置日志系统"""
    # 获取根日志器
    root_logger = logging.getLogger()

    # 设置日志级别
    log_level = getattr(logging, settings.LOG_LEVEL.upper())
    root_logger.setLevel(log_level)

    # 清除现有处理器
    root_logger.handlers.clear()

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # 根据配置选择格式化器
    formatter: logging.Formatter
    if settings.LOG_FORMAT == "json" or settings.ENV == "production":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    structlog.configure(
        processors=[_safe_event, structlog.processors.JSONRenderer(ensure_ascii=False)],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    # 设置第三方库日志级别（减少噪音）
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def get_logger(
    name: str,
    trace_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **extra_fields: Any,
) -> logging.LoggerAdapter:
    """获取带上下文的日志器

    Args:
        name: 日志器名称
        trace_id: 追踪ID
        tenant_id: 租户ID
        user_id: 用户ID
        **extra_fields: 额外字段

    Returns:
        日志适配器
    """
    logger = logging.getLogger(name)

    # 构建额外信息
    extra: dict[str, Any] = {}
    if trace_id:
        extra["trace_id"] = trace_id
    if tenant_id:
        extra["tenant_id"] = tenant_id
    if user_id:
        extra["user_id"] = user_id
    if extra_fields:
        extra["extra_fields"] = extra_fields

    return logging.LoggerAdapter(logger, extra)
