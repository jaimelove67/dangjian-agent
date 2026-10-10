"""知识查询的强制授权、公共库和时效过滤。

公共库查询需要越过普通 ORM 的租户等值过滤，因此仅在追加本模块策略的
语句执行期间绕过它；其他业务查询仍由原租户监听器保护。
"""

from datetime import date
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_role_profile
from app.core.tenant import TenantIsolationError, bypass_tenant_filter, get_tenant_id
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc
from app.models.user import User

DATA_LEVELS = ("public", "internal", "sensitive", "classified")


def knowledge_filters(user: User, *, include_expired: bool = False) -> dict[str, Any]:
    """只从登录用户生成授权条件，不接受客户端权限列表。"""
    profile = get_role_profile(user.role)
    return {
        "tenant_id": str(user.tenant_id),
        "knowledge_scopes": list(profile.knowledge_scopes),
        "max_security_level": profile.data_level.value,
        "org_unit_id": user.org_unit_id,
        "org_unit_ids": getattr(
            user, "knowledge_org_ids", [user.org_unit_id] if user.org_unit_id else []
        ),
        "all_org_units": profile.business_scope == "all",
        "include_expired": include_expired,
    }


def apply_knowledge_access(stmt: Select, filters: dict[str, Any], *, chunks: bool = True) -> Select:
    """强制限制租户、公开共享、角色、组织和有效日期。"""
    tenant_id = filters.get("tenant_id") or get_tenant_id()
    if not tenant_id:
        raise TenantIsolationError("知识查询缺少租户上下文")
    scopes = filters.get("knowledge_scopes", ["public"])
    maximum = filters.get("max_security_level", "public")
    if maximum not in DATA_LEVELS:
        raise TenantIsolationError("知识查询的数据级别非法")
    permitted_levels = DATA_LEVELS[: min(DATA_LEVELS.index(maximum) + 1, 3)]
    public_library = and_(
        KnowledgeDoc.visibility == "public",
        KnowledgeDoc.security_level == "public",
        KnowledgeDoc.level.in_(["central", "provincial"]),
    )
    stmt = stmt.where(
        or_(KnowledgeDoc.tenant_id == tenant_id, public_library),
        KnowledgeDoc.is_deleted.is_(False),
        KnowledgeDoc.visibility.in_(scopes),
        KnowledgeDoc.security_level.in_(permitted_levels),
    )
    if not filters.get("include_future", False):
        stmt = stmt.where(KnowledgeDoc.effective_date <= date.today())
    if not filters.get("all_org_units", False):
        stmt = stmt.where(
            or_(
                KnowledgeDoc.visibility.in_(["public", "school"]),
                and_(
                    KnowledgeDoc.visibility.in_(["department", "branch"]),
                    KnowledgeDoc.doc_metadata["org_unit_id"]
                    .as_string()
                    .in_(
                        filters.get(
                            "org_unit_ids",
                            [filters["org_unit_id"]] if filters.get("org_unit_id") else [],
                        )
                    ),
                ),
            )
        )
    if chunks:
        stmt = stmt.where(
            EmbeddingChunk.is_deleted.is_(False),
            EmbeddingChunk.tenant_id == KnowledgeDoc.tenant_id,
        )
    if not filters.get("include_expired", False):
        stmt = stmt.where(
            KnowledgeDoc.status == "effective",
            or_(
                KnowledgeDoc.expiration_date.is_(None), KnowledgeDoc.expiration_date >= date.today()
            ),
        )
    elif filters.get("status"):
        stmt = stmt.where(KnowledgeDoc.status == filters["status"])
    if filters.get("doc_ids"):
        stmt = stmt.where(KnowledgeDoc.doc_id.in_(filters["doc_ids"]))
    if filters.get("security_level"):
        stmt = stmt.where(KnowledgeDoc.security_level == filters["security_level"])
    return stmt


async def execute_knowledge_query(db: AsyncSession, stmt: Select):
    """执行已明确授权的知识查询，允许公共库与当前租户的并集。"""
    with bypass_tenant_filter():
        return await db.execute(stmt)


def source_columns() -> tuple:
    """引用所需的真实来源字段。片段始终连接数据库主键。"""
    return (
        EmbeddingChunk.chunk_id,
        EmbeddingChunk.content,
        KnowledgeDoc.doc_id,
        EmbeddingChunk.article,
        EmbeddingChunk.sequence,
        KnowledgeDoc.title,
        KnowledgeDoc.file_name,
        KnowledgeDoc.issuer,
        KnowledgeDoc.doc_number,
        KnowledgeDoc.level,
        KnowledgeDoc.visibility,
        KnowledgeDoc.security_level,
        KnowledgeDoc.effective_date,
        KnowledgeDoc.expiration_date,
        KnowledgeDoc.status,
    )


def source_metadata(row: Any, method: str) -> dict[str, Any]:
    return {
        **{
            key: getattr(row, key, None)
            for key in (
                "title",
                "file_name",
                "issuer",
                "doc_number",
                "level",
                "visibility",
                "security_level",
                "effective_date",
                "expiration_date",
                "status",
            )
        },
        "retrieval_method": method,
    }
