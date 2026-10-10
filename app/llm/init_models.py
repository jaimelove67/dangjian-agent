"""按项目配置注册三个云端模型；没有密钥时不发起请求。"""

from app.core.config import settings
from app.llm.base import ModelType
from app.llm.registry import get_model_registry


def init_models() -> None:
    if not settings.DASHSCOPE_API_KEY:
        return
    from app.llm.providers.dashscope_embedding import create_dashscope_embedding_provider
    from app.llm.providers.dashscope_reranker import create_dashscope_reranker_provider
    from app.llm.providers.qwen import create_dashscope_provider

    registry = get_model_registry()
    for factory, model_id, model_name in (
        (create_dashscope_provider, "cloud-llm", settings.LLM_MODEL_NAME),
        (create_dashscope_embedding_provider, "cloud-embedding", settings.EMBEDDING_MODEL_NAME),
        (create_dashscope_reranker_provider, "cloud-reranker", settings.RERANKER_MODEL_NAME),
    ):
        if registry.get_provider(model_id) is None:
            params = {
                "model_id": model_id,
                "model_name": model_name,
                "api_key": settings.DASHSCOPE_API_KEY,
            }
            if model_id == "cloud-llm":
                params.update(
                    max_tokens=settings.LLM_MAX_TOKENS, temperature=settings.LLM_TEMPERATURE
                )
            registry.register(factory(**params))


def model_readiness() -> dict[str, str]:
    """公开就绪检查只报告注册状态，不自动发起付费请求。"""
    registry = get_model_registry()
    return {
        kind.value: "configured" if registry.list_models(model_type=kind) else "missing"
        for kind in (ModelType.LLM, ModelType.EMBEDDING, ModelType.RERANKER)
    }


async def health_check_models() -> dict:
    return await get_model_registry().health_check_all()
