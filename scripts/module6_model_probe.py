"""按已确认学校策略进行三类模型真实连通验收，仅使用固定公开测试文本。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select  # noqa: E402

from app.core.cache import redis_manager  # noqa: E402
from app.core.config import tenant_config  # noqa: E402
from app.core.security import Permission, has_permission  # noqa: E402
from app.core.tenant import bypass_tenant_filter, tenant_context  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402
from app.llm.base import DataLevel  # noqa: E402
from app.llm.init_models import init_models  # noqa: E402
from app.llm.service import get_model_service  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.governance_service import read_governance  # noqa: E402
from app.services.identity_guard import ensure_active_identity  # noqa: E402


async def probe(actor_id: str) -> dict:
    with bypass_tenant_filter():
        async with async_session_maker() as db:
            user = (
                await db.execute(
                    select(User).where(User.id == actor_id, User.is_deleted.is_(False))
                )
            ).scalar_one_or_none()
            if user is None or not has_permission(user.role, Permission.CONFIG_MANAGE):
                raise ValueError("验收必须使用已登记的学校配置管理身份")
            await ensure_active_identity(db, user)
            if tenant_config.local(str(user.tenant_id), "_tenant_type") != "school":
                raise ValueError("请使用学校租户的配置管理身份验收")
            config = await read_governance(db, user)
            if config["admission"]["status"] != "configured":
                return {"status": "pending_configuration", "calls": 0}
    init_models()
    await redis_manager.connect()
    service = get_model_service()
    checks = {}
    with tenant_context(str(user.tenant_id), str(user.id)):
        context = {"request_id": str(uuid.uuid4()), "task_type": "public_connectivity_probe"}
        actions = {
            "llm": lambda: service.generate(
                "这是公开的系统连通性验收。请只回复 OK。",
                DataLevel.PUBLIC,
                context=context,
                max_tokens=8,
            ),
            "embedding": lambda: service.embed(
                ["公开的系统连通性验收文本。"], DataLevel.PUBLIC, context=context
            ),
            "reranker": lambda: service.rerank(
                "公开连通性验收",
                ["公开连通性验收文本", "公开的无关测试文本"],
                1,
                DataLevel.PUBLIC,
                context=context,
            ),
        }
        for kind, action in actions.items():
            started = time.monotonic()
            try:
                response = await action()
                valid = (
                    bool(getattr(response, "content", None))
                    if kind == "llm"
                    else (
                        bool(getattr(response, "embeddings", None))
                        if kind == "embedding"
                        else bool(getattr(response, "results", None))
                    )
                )
                checks[kind] = {
                    "status": "passed" if valid else "failed",
                    "seconds": time.monotonic() - started,
                    "model_id": getattr(response, "model_id", "unknown"),
                }
            except Exception as exc:
                checks[kind] = {
                    "status": "failed",
                    "error": type(exc).__name__,
                    "seconds": time.monotonic() - started,
                }
    await redis_manager.disconnect()
    return {
        "status": "passed" if all(v["status"] == "passed" for v in checks.values()) else "failed",
        "calls": len(checks),
        "checks": checks,
        "notice": "仅为真实连通性证据，不代表完整问答性能验收。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(args.actor_id))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return (
            0
            if result["status"] == "passed"
            else 2 if result["status"] == "pending_configuration" else 1
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
