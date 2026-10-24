"""独立请求审计。数据库故障时先写认证加密的持久缓冲，恢复后幂等重放。"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.audit import make_audit_log
from app.core.config import settings
from app.core.encryption import atomic_write, seal, unseal
from app.core.tenant import bypass_tenant_filter
from app.db.session import async_session_maker
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


def spool_root() -> Path:
    root = Path(settings.AUDIT_SPOOL_DIR).absolute()
    if root.resolve() != root:
        raise ValueError("审计缓冲目录不能使用符号链接")
    root.mkdir(parents=True, exist_ok=True)
    return root


def spool(event: dict[str, Any]) -> None:
    root = spool_root()
    event_id = uuid.UUID(event["id"])
    path = root / f"{event_id}.audit"
    encrypted = seal(json.dumps(event, default=str).encode(), "audit:" + str(event_id))
    atomic_write(path, encrypted)


async def persist(event: dict[str, Any]) -> None:
    try:
        with bypass_tenant_filter():
            async with async_session_maker() as db:
                row = make_audit_log(
                    **{
                        key: value
                        for key, value in event.items()
                        if key not in {"id", "created_at"}
                    }
                )
                row.id = event["id"]
                row.created_at = datetime.fromisoformat(event["created_at"])
                db.add(row)
                await db.commit()
    except Exception:
        await asyncio.to_thread(spool, event)
        logger.warning("audit_database_unavailable_event_spooled")


async def replay(limit: int = 100) -> int:
    completed = 0
    root = spool_root()
    for path in list(root.glob("*.audit"))[:limit]:
        if path.is_symlink() or path.resolve().parent != root.resolve():
            continue
        try:
            event_id = str(uuid.UUID(path.stem))
            event = json.loads(unseal(path.read_bytes(), "audit:" + event_id))
            with bypass_tenant_filter():
                async with async_session_maker() as db:
                    existing = (
                        await db.execute(select(AuditLog.id).where(AuditLog.id == event_id))
                    ).scalar_one_or_none()
                    if existing is None:
                        row = make_audit_log(
                            **{
                                key: value
                                for key, value in event.items()
                                if key not in {"id", "created_at"}
                            }
                        )
                        row.id = event_id
                        row.created_at = datetime.fromisoformat(event["created_at"])
                        db.add(row)
                        await db.commit()
            path.unlink()
            completed += 1
        except Exception:
            logger.warning("audit_spool_replay_deferred", exc_info=True)
            # 单个损坏或暂时失败的事件不应阻塞其余缓冲回放；
            # 未成功的事件文件保留，待下一次 replay 或人工处理重试。
            continue
    return completed


def event_for_request(request: Any, status: int, duration: float) -> dict[str, Any]:
    identity = getattr(request.state, "audit_identity", {})
    route = request.scope.get("route")
    template = getattr(route, "path", "/unmatched")
    method = request.method
    action = (
        "export"
        if "export" in template or "original" in template
        else {
            "GET": "query",
            "POST": "create",
            "PATCH": "update",
            "PUT": "update",
            "DELETE": "delete",
        }.get(method, "request")
    )
    if "/auth/" in template:
        action = template.rsplit("/", 1)[-1]
    object_ids = list(request.path_params.values())
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "tenant_id": identity.get("tenant_id", "unauthenticated"),
        "user_id": identity.get("user_id", "anonymous"),
        "user_name": identity.get("user_id", "anonymous"),
        "action": action,
        "resource_type": template.split("/")[3][:50] if len(template.split("/")) > 3 else "request",
        "resource_id": str(object_ids[0])[:200] if object_ids else None,
        "data_level": getattr(
            request.state, "audit_data_level", identity.get("data_level", "public")
        ),
        "ip_address": request.client.host[:45] if request.client else None,
        "user_agent": None,
        "request_id": getattr(request.state, "trace_id", uuid.uuid4().hex),
        "result": (
            "denied" if status in (401, 403, 429) else "failed" if status >= 400 else "success"
        ),
        "new_value": {
            "route": template,
            "method": method,
            "status": status,
            "duration_ms": round(duration * 1000, 2),
        },
    }
