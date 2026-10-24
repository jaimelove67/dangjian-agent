"""服务器端一次性初始化：平台租户 + 平台管理员账号（幂等）

用法（仓库根目录，容器内 ENV=development）：

    docker compose -f docker-compose.server.yml exec -T app \
        python scripts/server_init_admin.py --username admin --password <强密码>

说明：
- 只创建平台租户 PLATFORM_TENANT 与一名系统管理员，不代替组织做认定。
  学校租户、组织树、业务账号请在系统管理页面由管理员自行登记。
- 幂等：租户或用户名已存在时不会重复创建；已存在用户可用 --reset-password 重置密码。
- 密码以 bcrypt 哈希写入（复用应用自身的 hash_password），不存储明文。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenant import bypass_tenant_filter  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

PLATFORM_ID = "PLATFORM_TENANT"


async def main() -> None:
    parser = argparse.ArgumentParser(description="服务器初始化：平台租户与系统管理员")
    parser.add_argument("--username", default="admin", help="管理员用户名")
    parser.add_argument("--password", required=True, help="管理员密码（>=8 字符）")
    parser.add_argument("--name", default="平台管理员", help="显示姓名")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="用户已存在时重置其密码",
    )
    args = parser.parse_args()

    if settings.ENV not in {"development", "testing"}:
        raise RuntimeError("脚本只允许在 development/testing 环境运行")
    if len(args.password) < 8:
        raise ValueError("密码至少 8 个字符")

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with bypass_tenant_filter():
        async with session_factory() as db:
            # ---------- 平台租户 ----------
            platform = await db.get(Tenant, PLATFORM_ID)
            if platform is None:
                db.add(
                    Tenant(
                        id=PLATFORM_ID,
                        tenant_id=PLATFORM_ID,
                        name="党建平台",
                        tenant_type="platform",
                        parent_id=None,
                        path="/" + PLATFORM_ID,
                        is_active=True,
                    )
                )
                await db.flush()
                print("[ok] platform tenant created:", PLATFORM_ID)
            else:
                print("[skip] platform tenant exists:", PLATFORM_ID)

            # ---------- 管理员账号 ----------
            result = await db.execute(select(User).where(User.username == args.username))
            user = result.scalar_one_or_none()
            if user is None:
                db.add(
                    User(
                        id=str(uuid.uuid4()),
                        username=args.username,
                        name=args.name,
                        password_hash=hash_password(args.password),
                        role=UserRole.SYSTEM_ADMIN,
                        tenant_id=PLATFORM_ID,
                        org_unit_id=None,
                        is_active=True,
                    )
                )
                await db.flush()
                print("[ok] user created:", args.username, UserRole.SYSTEM_ADMIN.value)
            elif args.reset_password:
                user.password_hash = hash_password(args.password)
                await db.flush()
                print("[ok] password reset:", args.username)
            else:
                print("[skip] user exists:", args.username)

            await db.commit()

    print("[done] login with:", args.username)


if __name__ == "__main__":
    asyncio.run(main())
