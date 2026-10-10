"""模型提供者包

包含各种模型提供者的实现。
"""

from app.llm.providers.dashscope_embedding import (
    DashScopeEmbeddingProvider,
    create_dashscope_embedding_provider,
)
from app.llm.providers.dashscope_reranker import (
    DashScopeRerankerProvider,
    create_dashscope_reranker_provider,
)
from app.llm.providers.qwen import (
    DashScopeProvider,
    QwenProvider,
    create_dashscope_provider,
    create_qwen_provider,
)

__all__ = [
    # DashScope LLM
    "DashScopeProvider",
    "create_dashscope_provider",
    # DashScope Embedding
    "DashScopeEmbeddingProvider",
    "create_dashscope_embedding_provider",
    # DashScope Reranker
    "DashScopeRerankerProvider",
    "create_dashscope_reranker_provider",
    # 兼容性别名
    "QwenProvider",
    "create_qwen_provider",
]
