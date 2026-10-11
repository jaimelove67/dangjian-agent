"""检索基础类型与接口定义"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class RetrievalResult:
    """检索结果"""

    # 片段ID
    chunk_id: str

    # 片段内容
    content: str

    # 相关度分数（0-1，越大越相关）
    score: float

    # 所属文档ID
    doc_id: str

    # 条款编号（如"第十四条"）
    article: Optional[str] = None

    # 片段序号
    sequence: Optional[int] = None

    # 所属文档状态（引用核验/时效提示用）
    doc_status: Optional[str] = None

    # 所属文档生效/失效日期（引用核验/时效提示用）
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None

    # 文档元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"RetrievalResult(chunk_id={self.chunk_id!r}, "
            f"score={self.score:.4f}, article={self.article})"
        )


class Retriever(ABC):
    """检索器基类"""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """检索相关片段

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件（如租户ID、文档级别等）

        Returns:
            检索结果列表，按相关度降序排列
        """
        raise NotImplementedError
