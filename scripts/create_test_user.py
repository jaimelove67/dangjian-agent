"""创建测试用户（开发 / 前后端联调用）

用法（在仓库根目录，或用容器内路径）：

    python scripts/create_test_user.py
    python scripts/create_test_user.py --username admin --password admin123 --role system_admin

默认创建：admin / admin123 （角色 system_admin，租户 tenant-demo）

说明：
- 幂等：用户名已存在时不会重复创建。
- 密码以 bcrypt 哈希写入（复用应用自身的 hash_password），不存储明文。
- 仅用于开发/联调环境，切勿在生产环境使用默认口令。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# 允许以 `python scripts/create_test_user.py` 直接运行
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.db.session import engine
from app.models.user import User, UserRole


async def create_user(args: argparse.Namespace) -> None:
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
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
            email=args.email or None,
            phone=args.phone or None,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(
            f"[ok] 已创建用户：{args.username} / {args.password} "
            f"(role={args.role}, tenant={args.tenant})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="创建开发/联调测试用户")
    parser.add_argument("--username", default="admin", help="用户名（默认 admin）")
    parser.add_argument("--password", default="admin123", help="明文密码（默认 admin123）")
    parser.add_argument("--name", default="系统管理员", help="显示姓名")
    parser.add_argument(
        "--role",
        default=UserRole.SYSTEM_ADMIN.value,
        choices=[r.value for r in UserRole],
        help="角色",
    )
    parser.add_argument("--tenant", default="tenant-demo", help="租户ID")
    parser.add_argument("--email", default="admin@party-agent.local", help="邮箱（可空）")
    parser.add_argument("--phone", default="", help="手机号（可空）")
    args = parser.parse_args()

    asyncio.run(create_user(args))


if __name__ == "__main__":
    main()
