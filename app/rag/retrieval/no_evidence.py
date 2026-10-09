"""无依据判定模块"""
from typing import List

from app.schemas.retrieval import RetrievalResult


def has_evidence(
    results: List[RetrievalResult],
    threshold: float = 0.5,
    min_results: int = 1,
) -> bool:
    """判定是否有足够依据

    Args:
        results: 检索结果列表
        threshold: 最低分数阈值
        min_results: 最少结果数

    Returns:
        是否有足够依据
    """
    # 检查是否有结果
    if not results or len(results) < min_results:
        return False

    # 检查最高分是否达到阈值
    if results[0].score < threshold:
        return False

    return True


def check_evidence_threshold(
    results: List[RetrievalResult],
    threshold: float = 0.5,
) -> tuple[bool, str]:
    """检查依据阈值并返回原因

    Args:
        results: 检索结果列表
        threshold: 最低分数阈值

    Returns:
        (是否有依据, 原因说明)
    """
    if not results:
        return False, "未检索到相关文档"

    if results[0].score < threshold:
        return False, f"检索结果相关度过低（最高分: {results[0].score:.3f}, 阈值: {threshold}）"

    return True, "检索到相关文档"
