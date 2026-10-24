"""模型调用的脱敏计量；不存提示词、模型响应或供应商异常正文。"""

import logging
import time
import uuid
from functools import wraps
from typing import Any, Callable

from app.core.config import tenant_config
from app.core.metrics import MODEL_CALLS, MODEL_LATENCY
from app.core.tenant import bypass_tenant_filter, get_tenant_id
from app.db.session import async_session_maker
from app.models.governance import ModelUsage

logger = logging.getLogger(__name__)


async def record(
    kind: str,
    duration: float,
    result: str,
    model: str,
    context: dict | None = None,
    config_version: int | None = None,
) -> None:
    MODEL_CALLS.labels(kind, result).inc()
    MODEL_LATENCY.labels(kind).observe(duration)
    tenant_id = get_tenant_id()
    if not tenant_id:
        return
    request_id = str((context or {}).get("request_id") or uuid.uuid4().hex)[:64]
    try:
        with bypass_tenant_filter():
            async with async_session_maker() as db:
                db.add(
                    ModelUsage(
                        tenant_id=tenant_id,
                        request_id=request_id,
                        model_type=kind,
                        model_name=model[:100],
                        result=result,
                        duration_seconds=duration,
                        config_version=(
                            config_version
                            if config_version is not None
                            else int(tenant_config.local(tenant_id, "_config_version", 0))
                        ),
                    )
                )
                await db.commit()
    except Exception:
        # 请求级审计仍有加密缓冲，模型指标也保留在 Prometheus。
        # 保留宽捕获以隔离计量路径（不应让计量失败打断业务请求），
        # 附带异常信息便于诊断；此处不含请求正文与提示词。
        logger.warning("model_usage_database_unavailable", exc_info=True)


def tracked(kind: str) -> Callable:
    def decorate(function: Callable) -> Callable:
        @wraps(function)
        async def invoke(*args: Any, **kwargs: Any) -> Any:
            started, result, model = time.monotonic(), "failed", "routing"
            version = int(tenant_config.local(get_tenant_id() or "", "_config_version", 0))
            try:
                response = await function(*args, **kwargs)
                valid = (
                    bool(getattr(response, "content", "").strip())
                    if kind == "llm"
                    else bool(
                        getattr(response, "embeddings", None)
                        if kind == "embedding"
                        else getattr(response, "results", None)
                    )
                )
                result, model = ("success" if valid else "invalid_response"), getattr(
                    response, "model_id", "unknown"
                )
                return response
            finally:
                await record(
                    kind, time.monotonic() - started, result, model, kwargs.get("context"), version
                )

        return invoke

    return decorate
