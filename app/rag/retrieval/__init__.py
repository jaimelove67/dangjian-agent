"""检索链路模块

提供多种检索策略：
- 向量检索（语义相似度）
- 关键词检索（全文检索）
- 混合检索（向量+关键词融合）
- 重排序（Reranker）
"""
from app.rag.retrieval.base import RetrievalResult, Retriever
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever

__all__ = [
    "RetrievalResult",
    "Retriever",
    "VectorRetriever",
    "KeywordRetriever",
    "HybridRetriever",
]
