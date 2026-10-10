"""多轮会话上下文管理（框架文档 5.8）

- 会话隔离：缓存键包含租户标识，防跨租户串话；
- 上下文范围：仅保留问答内容与引用**摘要**（文件名/条款），**不保留原始敏感片段**；
- 过期策略：写入时设置 TTL，到期自动清理；
- 存储：Redis（经 ``CacheService``）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol


class CacheLike(Protocol):
    """与 ``app.core.cache.CacheService`` 兼容的最小缓存接口"""

    async def get(self, key: str) -> Any: ...
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool: ...
    async def delete(self, key: str) -> bool: ...


@dataclass
class QATurn:
    """单轮问答（仅保留问答与引用摘要）"""

    question: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    @staticmethod
    def create(
        question: str, answer: str, citations: Optional[list[dict[str, Any]]] = None
    ) -> "QATurn":
        return QATurn(
            question=question,
            answer=answer,
            citations=citations or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )


class SessionStore:
    """基于缓存的会话存储"""

    KEY_PREFIX = "session:"

    def __init__(
        self,
        cache: CacheLike,
        *,
        ttl_seconds: int = 3600,
        max_turns: int = 5,
        owner_id: Optional[str] = None,
    ) -> None:
        self._cache = cache
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self.owner_id = owner_id

    def build_key(self, tenant_id: str, session_id: str) -> str:
        """会话键：包含租户标识，实现会话隔离"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not session_id:
            raise ValueError("session_id 不能为空")
        owner = f"{self.owner_id}:" if self.owner_id else ""
        return f"{self.KEY_PREFIX}{tenant_id}:{owner}{session_id}"

    async def get_history(self, tenant_id: str, session_id: str) -> list[QATurn]:
        """读取会话历史（不含原始敏感片段）"""
        raw = await self._cache.get(self.build_key(tenant_id, session_id))
        if not raw:
            return []
        return [QATurn(**item) for item in raw]

    async def append_turn(self, tenant_id: str, session_id: str, turn: QATurn) -> None:
        """追加一轮问答（超出上限时截断旧轮次）"""
        history = await self.get_history(tenant_id, session_id)
        history.append(turn)
        history = history[-self.max_turns :]
        saved = await self._cache.set(
            self.build_key(tenant_id, session_id),
            [asdict(item) for item in history],
            ttl=self.ttl_seconds,
        )
        if not saved:
            raise RuntimeError("会话保存失败")

    async def clear(self, tenant_id: str, session_id: str) -> bool:
        """清除会话"""
        return await self._cache.delete(self.build_key(tenant_id, session_id))

    @staticmethod
    def summarize_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """仅保留引用摘要字段（文件名、条款），避免缓存原始片段"""
        return [{"doc_name": c.get("doc_name"), "article": c.get("article")} for c in citations]
