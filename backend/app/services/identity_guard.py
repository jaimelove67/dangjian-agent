"""请求、刷新令牌及后台任务共用的实时身份和祖先停用检查。"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings, tenant_config
from app.models.user import User
from app.services.org_scope import knowledge_org_ids


async def ensure_active_identity(db: AsyncSession, user: User) -> None:
    if user.is_deleted or not user.is_active:
        raise HTTPException(403, "用户已被禁用")
    tenant_id = str(user.tenant_id)
    try:
        await tenant_config.load(db, tenant_id)
    except ValueError:
        raise HTTPException(403, "租户祖先配置无效") from None
    registered = tenant_config.local(tenant_id, "_present")
    if registered and not tenant_config.local(tenant_id, "_chain_active"):
        raise HTTPException(403, "当前租户或祖先租户已停用")
    if settings.ENV == "production" and not registered:
        raise HTTPException(403, "当前租户尚未登记")
    user.knowledge_org_ids = await knowledge_org_ids(db, user)
    if user.org_unit_id and not user.knowledge_org_ids:
        raise HTTPException(403, "所属组织或祖先组织已失效")
