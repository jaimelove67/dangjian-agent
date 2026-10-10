"""导入「培养对象名册」种子数据（开发 / 前后端联调）

用法（在仓库根目录，或用容器内路径）：

    python scripts/seed_member_profiles.py
    python scripts/seed_member_profiles.py --tenant tenant-verify

默认向租户 ``tenant-verify`` 导入 6 名培养对象（与 admin-verify 同租户），
覆盖申请人 / 积极分子 / 发展对象 / 预备党员 / 正式党员各阶段。

说明：
- 幂等：目标租户下若已存在培养对象则跳过，不重复导入。
- 在阶段天数由 ``stage_joined_on`` 实时计算，此处按 341/271/206/106/30/470 天前折算日期。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# 允许以 `python scripts/seed_member_profiles.py` 直接运行
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.session import engine
from app.models.member import MemberProfile

DEFAULT_TENANT = "tenant-verify"
_TODAY = date.today()


def _days_ago(n: int) -> date:
    return _TODAY - timedelta(days=n)


_SEED = [
    {
        "name": "张一鸣",
        "org_name": "计算机学院党委 · 本科生第一党支部",
        "current_stage": "activist",
        "stage_joined_on": _days_ago(341),
        "materials": ["思想汇报", "培养考察记录", "群众评议材料"],
        "pending": 1,
    },
    {
        "name": "李思远",
        "org_name": "计算机学院党委 · 本科生第一党支部",
        "current_stage": "activist",
        "stage_joined_on": _days_ago(271),
        "materials": ["思想汇报", "培养考察记录"],
        "pending": 2,
    },
    {
        "name": "王砚书",
        "org_name": "计算机学院党委 · 研究生第二党支部",
        "current_stage": "candidate",
        "stage_joined_on": _days_ago(206),
        "materials": ["政治审查材料", "公示情况报告"],
        "pending": 2,
    },
    {
        "name": "陈亦舟",
        "org_name": "计算机学院党委 · 研究生第二党支部",
        "current_stage": "probationary",
        "stage_joined_on": _days_ago(106),
        "materials": ["转正申请书"],
        "pending": 1,
    },
    {
        "name": "赵惟安",
        "org_name": "计算机学院党委 · 本科生第三党支部",
        "current_stage": "applicant",
        "stage_joined_on": _days_ago(30),
        "materials": ["入党申请书"],
        "pending": 0,
    },
    {
        "name": "周砚青",
        "org_name": "计算机学院党委 · 研究生第二党支部",
        "current_stage": "member",
        "stage_joined_on": _days_ago(470),
        "materials": [],
        "pending": 0,
    },
]


async def seed(tenant: str) -> None:
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        existing = await db.execute(
            select(MemberProfile).where(MemberProfile.tenant_id == tenant)
        )
        if existing.scalars().first() is not None:
            print(f"[skip] 租户 {tenant} 已存在培养对象，跳过导入")
            return

        for item in _SEED:
            db.add(MemberProfile(id=str(uuid.uuid4()), tenant_id=tenant, **item))
        await db.commit()
        print(f"[ok] 已导入 {len(_SEED)} 名培养对象 -> tenant={tenant}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入培养对象名册种子数据")
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help="租户ID")
    args = parser.parse_args()
    asyncio.run(seed(args.tenant))


if __name__ == "__main__":
    main()