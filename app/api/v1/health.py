"""健康检查接口"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.config import settings, tenant_config
from app.core.database_privileges import UNSAFE_RUNTIME_ROLE
from app.deps import require_roles
from app.models.user import UserRole

logger = logging.getLogger(__name__)

router = APIRouter()
_require_system = require_roles(UserRole.SYSTEM_ADMIN)


@lru_cache(maxsize=1)
def expected_schema_head() -> str | None:
    """从迁移脚本推导期望的数据库版本，而不是写死版本号。

    写死常量时，新增迁移与这行不同步就会让 ``/health/ready`` 永久 503：故障表现
    （就绪探针失败）与真实原因（常量忘改）完全错位。解析不到 alembic 配置时返回
    ``None``，交由表结构检查判定，不误报就绪失败。
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
            ini = base / "alembic.ini"
            if not ini.is_file():
                continue
            config = Config(str(ini))
            location = config.get_main_option("script_location") or "migrations"
            if "%(here)s" not in location and not Path(location).is_absolute():
                config.set_main_option("script_location", str((base / location).resolve()))
            return ScriptDirectory.from_config(config).get_current_head()
    except Exception:
        logger.warning("schema_head_unresolved", exc_info=True)
    return None


@router.get(
    "/health",
    summary="健康检查",
    description="检查服务是否正常运行",
    response_description="服务状态信息",
)
async def health_check() -> Dict[str, Any]:
    """健康检查接口

    Returns:
        服务状态信息
    """
    return {"status": "healthy"}


@router.get(
    "/admin/health",
    summary="系统运行信息",
    description="仅平台管理员可查看服务名称、版本与运行环境",
    dependencies=[Depends(_require_system)],
)
async def system_health_check() -> Dict[str, Any]:
    """向平台管理员返回系统运行详情。"""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENV,
    }


@router.get(
    "/health/ready",
    summary="就绪检查",
    description="公开探针，仅返回整体就绪状态，依赖详情需平台管理员查看",
    response_description="服务就绪状态",
)
async def readiness_check() -> JSONResponse:
    """公开就绪探针，保留 HTTP 状态码且不暴露依赖详情。"""
    details = await _readiness_details()
    return JSONResponse(
        status_code=details.status_code,
        content={"status": "ready" if details.status_code == status.HTTP_200_OK else "not_ready"},
    )


@router.get(
    "/admin/health/ready",
    summary="系统就绪详情",
    description="仅平台管理员可查看数据库、Redis、结构与模型配置状态",
    dependencies=[Depends(_require_system)],
)
async def system_readiness_check() -> JSONResponse:
    """向平台管理员返回各依赖的就绪详情。"""
    return await _readiness_details()


async def _readiness_details() -> JSONResponse:
    """检查所有依赖，仅由公开摘要和管理员详情接口调用。"""
    connectivity_verified = False
    checks = {
        "database": "unknown",
        "redis": "unknown",
        "schema": "unknown",
        "models": "unknown",
        "encryption": "unknown",
        "audit_storage": "unknown",
    }

    # 检查 Redis 连接
    try:
        from app.core.cache import redis_manager

        await redis_manager.client.ping()
        checks["redis"] = "healthy"
    except Exception:
        logger.error("redis_health_check_failed")
        checks["redis"] = "unhealthy"

    # 检查数据库连接
    try:
        from sqlalchemy import text

        from app.db.session import async_session_maker, engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            expected_tables = (
                "users",
                "tenants",
                "org_units",
                "knowledge_docs",
                "embedding_chunks",
                "audit_logs",
                "config_revisions",
                "human_reviews",
                "durable_jobs",
                "model_usage",
            )
            present = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables_ready = set(expected_tables).issubset({row[0] for row in present})
            fts_ready = await conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese_zh') "
                    "AND EXISTS(SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'knowledge_docs' AND column_name = 'search_vector')"
                )
            )
            checks["schema"] = "healthy" if tables_ready and fts_ready else "migration_required"
            if tables_ready:
                head = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                expected_head = expected_schema_head()
                if expected_head and head != expected_head:
                    checks["schema"] = "migration_required"
            if settings.ENV == "production" and tables_ready:
                safe_role = await conn.scalar(
                    text(
                        "SELECT NOT (" + UNSAFE_RUNTIME_ROLE + ") "
                        "AND has_table_privilege(current_user,'audit_logs','SELECT') "
                        "AND has_table_privilege(current_user,'audit_logs','INSERT') "
                        "AND NOT has_table_privilege(current_user,'audit_logs', "
                        "'UPDATE,DELETE,TRUNCATE') "
                        "AND NOT has_any_column_privilege(current_user,'audit_logs','UPDATE')"
                    ),
                    {"role": await conn.scalar(text("SELECT current_user"))},
                )
                checks["runtime_role"] = "healthy" if safe_role else "configuration_required"

                from app.services.governance_service import admission, default_values

                rows = await conn.execute(
                    text(
                        "SELECT config FROM tenants WHERE tenant_type='school' "
                        "AND is_active=true AND is_deleted=false"
                    )
                )
                configs = [row[0] or {} for row in rows]
                checks["school_admission"] = (
                    "healthy"
                    if configs
                    and all(
                        admission(default_values(value), value.get("electronic_archive", {}))[
                            "status"
                        ]
                        == "configured"
                        for value in configs
                    )
                    else "configuration_required"
                )
                from datetime import datetime, timedelta

                from app.core.tenant import tenant_context
                from app.llm.base import DataLevel, ModelType, TaskType
                from app.llm.router import get_model_router

                schools = (
                    await conn.execute(
                        text(
                            "SELECT id, config_version FROM tenants "
                            "WHERE tenant_type='school' AND is_active=true AND is_deleted=false"
                        )
                    )
                ).all()
                valid = bool(schools)
                for tid, version in schools:
                    async with async_session_maker() as db:
                        await tenant_config.load(db, tid)
                    with tenant_context(tid):
                        for kind in ModelType:
                            try:
                                model = get_model_router().get_model(
                                    data_level=DataLevel.PUBLIC,
                                    task_type=TaskType.QA,
                                    model_type=kind,
                                )
                                recent = await conn.scalar(
                                    text(
                                        "SELECT EXISTS(SELECT 1 FROM model_usage "
                                        "WHERE tenant_id=:tid AND config_version=:version "
                                        "AND model_type=:kind "
                                        "AND model_name=:model AND result='success' "
                                        "AND created_at>=:since)"
                                    ),
                                    {
                                        "tid": tid,
                                        "version": version,
                                        "kind": kind.value,
                                        "model": model.get_model_id(),
                                        "since": datetime.utcnow() - timedelta(minutes=15),
                                    },
                                )
                                valid = valid and bool(recent)
                            except Exception:
                                valid = False
                connectivity_verified = valid
        checks["database"] = "healthy"
    except Exception:
        logger.error("database_health_check_failed")
        checks["database"] = "unhealthy"

    from app.llm.init_models import model_readiness

    models = model_readiness()
    models_configured = all(value != "missing" for value in models.values())
    # 就绪只看"模型是否配置齐全"；"最近 15 分钟有成功调用"另作为 model_warm 观察项。
    # 若把 model_warm 也算进就绪，只要 15 分钟没人提问，系统状态页就会整片报
    # "尚未就绪"，把真正的故障淹掉。
    checks["models"] = "healthy" if models_configured else "configuration_required"
    checks["model_warm"] = "healthy" if connectivity_verified else "unverified"

    try:
        import os
        import uuid

        from app.core.encryption import keyring, seal, unseal
        from app.core.request_audit import spool_root

        active, _ = keyring()
        checks["encryption"] = (
            "healthy"
            if active != "development" or settings.ENV != "production"
            else "configuration_required"
        )
        root = spool_root()
        probe = root / (uuid.uuid4().hex + ".probe")
        try:
            encrypted = seal(b"readiness", "readiness")
            with probe.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            checks["audit_storage"] = (
                "healthy"
                if unseal(probe.read_bytes(), "readiness") == b"readiness"
                else "unhealthy"
            )
        finally:
            if probe.exists():
                probe.unlink()
    except Exception:
        checks["encryption"] = "configuration_required"
        checks["audit_storage"] = "unhealthy"
    if settings.ENV == "production":
        checks["jwt_secret"] = (
            "healthy"
            if len(settings.SECRET_KEY) >= 32 and not settings.SECRET_KEY.startswith("dev_")
            else "configuration_required"
        )

    # 判断整体状态：model_warm 是观察项，不参与就绪判定
    blocking = {key: value for key, value in checks.items() if key != "model_warm"}
    all_healthy = all(v == "healthy" for v in blocking.values())
    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "model_capabilities": models,
        },
    )


@router.get(
    "/health/live",
    summary="存活检查",
    description="检查服务进程是否存活",
    response_description="存活状态",
)
async def liveness_check() -> Dict[str, str]:
    """存活检查接口

    Returns:
        存活状态
    """
    return {"status": "alive"}
