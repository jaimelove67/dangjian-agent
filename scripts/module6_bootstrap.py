"""校方正式组织导入。默认只验证；待配置清单不生成虚构学校或账号。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.audit import write_audit  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenant import bypass_tenant_filter, tenant_context  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.schemas.governance import UserCreate  # noqa: E402
from app.services.identity_service import ORG_PARENTS, TENANT_PARENTS, IdentityService  # noqa: E402


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Platform(Strict):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=50)
    operator_name: str = Field(min_length=1, max_length=50)
    password_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,100}$")


class TenantEntry(Strict):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    parent: str
    name: str = Field(min_length=1, max_length=100)
    tenant_type: Literal["school", "department", "branch"]


class OrgEntry(Strict):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    tenant: str
    parent: str | None = None
    name: str = Field(min_length=1, max_length=100)
    org_type: Literal["school", "department", "branch"]


class UserEntry(Strict):
    tenant: str
    org: str
    username: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=1, max_length=50)
    role: UserRole
    password_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,100}$")


class Manifest(Strict):
    status: Literal["pending", "confirmed"] = "pending"
    evidence: str = Field(default="", max_length=2000)
    platform: Platform | None = None
    tenants: list[TenantEntry] = Field(default_factory=list, max_length=500)
    organizations: list[OrgEntry] = Field(default_factory=list, max_length=5000)
    users: list[UserEntry] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def validate_tree(self) -> Manifest:
        tenants = {"platform": "platform"}
        for item in self.tenants:
            if item.key in tenants or tenants.get(item.parent) != TENANT_PARENTS[item.tenant_type]:
                raise ValueError("租户按父级在前登记，键唯一且类型符合平台/学校/院系/支部")
            tenants[item.key] = item.tenant_type
        orgs: dict[str, OrgEntry] = {}
        roots: set[str] = set()
        for item in self.organizations:
            if item.key in orgs or item.tenant not in tenants:
                raise ValueError("组织键须唯一，租户必须已登记")
            parent = orgs.get(item.parent or "")
            if item.org_type == "school":
                if item.parent is not None or item.tenant in roots:
                    raise ValueError("每个租户只允许一个无父级学校组织")
                roots.add(item.tenant)
            elif (
                not parent
                or parent.tenant != item.tenant
                or parent.org_type not in ORG_PARENTS[item.org_type]
            ):
                raise ValueError("组织父级必须同租户、在前登记且类型有效")
            orgs[item.key] = item
        usernames = {self.platform.username} if self.platform else set()
        required = {
            UserRole.SCHOOL_ADMIN: {"school"},
            UserRole.DEPARTMENT_ADMIN: {"department"},
            UserRole.BRANCH_SECRETARY: {"branch"},
            UserRole.ORGANIZER: {"branch", "department"},
        }
        for item in self.users:
            org = orgs.get(item.org)
            if item.username in usernames or not org or org.tenant != item.tenant:
                raise ValueError("用户唯一并绑定同租户有效组织")
            if item.role == UserRole.SYSTEM_ADMIN or (
                item.role in required and org.org_type not in required[item.role]
            ):
                raise ValueError("组织角色不匹配；清单不能额外授予系统管理员")
            usernames.add(item.username)
        if self.status == "confirmed" and (
            not self.evidence.strip() or not self.platform or not self.tenants
        ):
            raise ValueError("确认导入需要校方依据、平台和至少一个真实学校")
        if self.status == "pending" and (self.tenants or self.organizations or self.users):
            raise ValueError("未确认清单不能携带待导入的正式组织或账号")
        return self


async def apply_manifest(manifest: Manifest, adopt_actor_id: str | None = None) -> dict[str, Any]:
    if manifest.status != "confirmed" or manifest.platform is None:
        raise ValueError("学校资料尚未确认，禁止应用")
    platform = manifest.platform
    # 密码仅来自环境变量；先完整验证，避免部分用户导入后才发现缺少密码。
    passwords = {
        item.password_env: os.environ.get(item.password_env, "") for item in manifest.users
    }
    if not adopt_actor_id:
        passwords[platform.password_env] = os.environ.get(platform.password_env, "")
    for password in passwords.values():
        UserCreate(
            username="validation-user",
            name="validation",
            password=password,
            role=UserRole.MEMBER,
            org_unit_id="validation",
        )
    with bypass_tenant_filter():
        async with async_session_maker() as db:
            actor = None
            if adopt_actor_id:
                actor = (
                    await db.execute(
                        select(User).where(
                            User.id == adopt_actor_id,
                            User.role == UserRole.SYSTEM_ADMIN,
                            User.is_active.is_(True),
                            User.is_deleted.is_(False),
                        )
                    )
                ).scalar_one_or_none()
                if actor is None:
                    raise ValueError("采纳的已有平台操作者须是有效系统管理员")
                tid = str(actor.tenant_id)
                existing = (
                    await db.execute(select(Tenant).where(Tenant.id == tid))
                ).scalar_one_or_none()
                if existing is not None:
                    raise ValueError("操作者租户已经登记，请使用管理工作区维护")
            else:
                if (await db.execute(select(Tenant.id).limit(1))).first() or (
                    await db.execute(select(User.id).limit(1))
                ).first():
                    raise ValueError("非空库必须明确指定已有系统管理员；禁止覆盖现有账号")
                tid = str(uuid.uuid4())
            root = Tenant(
                id=tid,
                tenant_id=tid,
                name=platform.name,
                tenant_type="platform",
                path="/" + tid,
                is_active=True,
                config_version=0,
                config={"registration": {"status": "pending"}},
            )
            db.add(root)
            if actor is None:
                actor = User(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    username=platform.username,
                    name=platform.operator_name,
                    role=UserRole.SYSTEM_ADMIN,
                    is_active=True,
                    password_hash=hash_password(passwords[platform.password_env]),
                )
                db.add(actor)
            await db.flush()
            with tenant_context(tid, user_id=str(actor.id)):
                service = IdentityService(db, actor)
                tenant_ids = {"platform": tid}
                org_ids: dict[str, str] = {}
                for item in manifest.tenants:
                    row = await service.create_tenant(
                        {
                            "name": item.name,
                            "tenant_type": item.tenant_type,
                            "parent_id": tenant_ids[item.parent],
                        }
                    )
                    tenant_ids[item.key] = str(row.id)
                    row.config = {
                        "registration": {"status": "confirmed", "evidence": manifest.evidence}
                    }
                for item in manifest.organizations:
                    row = await service.save_org(
                        tenant_ids[item.tenant],
                        {
                            "name": item.name,
                            "org_type": item.org_type,
                            "parent_id": org_ids.get(item.parent or ""),
                        },
                    )
                    org_ids[item.key] = str(row.id)
                for item in manifest.users:
                    await service.save_user(
                        tenant_ids[item.tenant],
                        {
                            "username": item.username,
                            "name": item.name,
                            "role": item.role,
                            "org_unit_id": org_ids[item.org],
                            "password": passwords[item.password_env],
                        },
                    )
                await write_audit(
                    db,
                    tenant_id=tid,
                    user_id=str(actor.id),
                    user_name=str(actor.id),
                    action="bootstrap",
                    resource_type="identity",
                    request_id=uuid.uuid4().hex,
                    result="success",
                    new_value={
                        "tenants": len(manifest.tenants),
                        "organizations": len(manifest.organizations),
                        "users": len(manifest.users),
                    },
                    data_level="internal",
                )
                await db.commit()
    return {
        "status": "imported",
        "tenants": tenant_ids,
        "org_count": len(org_ids),
        "approvals": "pending_configuration",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("config/module6-school.pending.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--adopt-actor-id")
    args = parser.parse_args()
    try:
        manifest = Manifest.model_validate_json(args.manifest.read_text(encoding="utf-8-sig"))
        if not args.apply:
            print(
                json.dumps(
                    {
                        "status": (
                            "validated"
                            if manifest.status == "confirmed"
                            else "pending_configuration"
                        ),
                        "applied": False,
                        "school_count": sum(x.tenant_type == "school" for x in manifest.tenants),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(
            json.dumps(
                asyncio.run(apply_manifest(manifest, args.adopt_actor_id)), ensure_ascii=False
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
