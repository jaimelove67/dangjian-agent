"""创建测试用户（开发 / 前后端联调用）

用法（在仓库根目录，或用容器内路径）：

    python scripts/create_test_user.py --username test-reviewer --tenant TEST_TENANT \
        --org-unit-id TEST_ORG --role school_admin

密码默认交互输入，不提供默认管理员或密码。

说明：
- 幂等：用户名已存在时不会重复创建。
- 密码以 bcrypt 哈希写入（复用应用自身的 hash_password），不存储明文。
- 仅用于 development/testing 环境，目标组织必须属于指定租户。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

# 直接脚本运行时先加入项目根目录，再导入应用模块。
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenant import tenant_context  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.org import OrgUnit  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


async def create_user(args: argparse.Namespace) -> None:
    if settings.ENV not in {"development", "testing"}:
        raise RuntimeError("测试账号脚本只允许在 development/testing 环境运行")
    if not args.password:
        raise ValueError("必须提供测试用户密码")
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with tenant_context(args.tenant):
        async with session_factory() as db:
            org = (
                await db.execute(
                    select(OrgUnit).where(
                        OrgUnit.id == args.org_unit_id,
                        OrgUnit.tenant_id == args.tenant,
                        OrgUnit.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                raise ValueError("测试用户组织必须是指定租户的有效组织")
            existing = await db.execute(select(User).where(User.username == args.username))
            if existing.scalar_one_or_none() is not None:
                print(f"[skip] 用户已存在：{args.username}")
                return

            user = User(
                id=str(uuid.uuid4()),
                username=args.username,
                name=args.name,
                password_hash=hash_password(args.password),
                role=UserRole(args.role),
                tenant_id=args.tenant,
                org_unit_id=args.org_unit_id,
                email=args.email or None,
                phone=args.phone or None,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            print(f"[ok] 已创建用户：{args.username} (role={args.role}, tenant={args.tenant})")


def main() -> None:
    parser = argparse.ArgumentParser(description="创建开发/联调测试用户")
    parser.add_argument("--username", required=True, help="测试用户名")
    parser.add_argument("--password", help="测试密码（省略时交互输入）")
    parser.add_argument("--name", default="合成测试用户", help="显示姓名")
    parser.add_argument(
        "--role",
        default=UserRole.MEMBER.value,
        choices=[r.value for r in UserRole],
        help="角色",
    )
    parser.add_argument("--tenant", required=True, help="测试租户ID")
    parser.add_argument("--org-unit-id", required=True, help="测试用户所属组织ID")
    parser.add_argument("--email", default="", help="邮箱（可空）")
    parser.add_argument("--phone", default="", help="手机号（可空）")
    args = parser.parse_args()
    if settings.ENV not in {"development", "testing"}:
        parser.error("测试账号脚本只允许在 development/testing 环境运行")
    args.password = args.password or getpass.getpass("测试用户密码：")

    asyncio.run(create_user(args))


if __name__ == "__main__":
    main()
