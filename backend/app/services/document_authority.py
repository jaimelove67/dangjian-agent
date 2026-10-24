"""后台任务与接口共用的校内文档写入检查。公共库仅由系统管理员维护。"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Permission, has_permission
from app.models.knowledge import KnowledgeDoc
from app.models.user import User, UserRole
from app.services.org_scope import accessible_org_units


async def require_document_write_access(db: AsyncSession, user: User, doc: KnowledgeDoc) -> None:
    if str(doc.tenant_id) != str(user.tenant_id) or not has_permission(
        user.role, Permission.KNOWLEDGE_MANAGE
    ):
        raise HTTPException(404, "文档不存在或没有维护权限")
    if doc.visibility == "public" or doc.level in {"central", "provincial"}:
        if user.role != UserRole.SYSTEM_ADMIN:
            raise HTTPException(403, "公共库仅由系统管理员维护")
    elif user.role not in {UserRole.SYSTEM_ADMIN, UserRole.SCHOOL_ADMIN}:
        permitted = {str(row.id) for row in await accessible_org_units(db, user)}
        if str((doc.doc_metadata or {}).get("org_unit_id", "")) not in permitted:
            raise HTTPException(404, "文档不在当前组织维护范围")
