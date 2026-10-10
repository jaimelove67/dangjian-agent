"""导入「培养对象名册」种子数据（开发 / 前后端联调）

用法（在仓库根目录，或用容器内路径）：

    python scripts/seed_member_profiles.py --tenant TEST_TENANT --org-unit-id TEST_BRANCH

向明确指定的测试租户与有效支部导入 6 名合成培养对象，
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

# 直接脚本运行时先加入项目根目录，再导入应用模块。
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.tenant import tenant_context  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.member import MemberProfile  # noqa: E402
from app.models.org import OrgUnit  # noqa: E402

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


async def seed(tenant: str, org_unit_id: str) -> None:
    if settings.ENV not in {"development", "testing"}:
        raise RuntimeError("名册种子脚本只允许在 development/testing 环境运行")
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with tenant_context(tenant):
        async with session_factory() as db:
            org = (
                await db.execute(
                    select(OrgUnit).where(
                        OrgUnit.id == org_unit_id,
                        OrgUnit.tenant_id == tenant,
                        OrgUnit.org_type == "branch",
                        OrgUnit.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                raise ValueError("名册必须关联指定租户的有效支部")
            existing = await db.execute(
                select(MemberProfile).where(
                    MemberProfile.tenant_id == tenant,
                    MemberProfile.org_unit_id == org_unit_id,
                    MemberProfile.is_deleted.is_(False),
                )
            )
            if existing.scalars().first() is not None:
                print(f"[skip] 租户 {tenant} 的该支部已存在培养对象，跳过导入")
                return

            for item in _SEED:
                db.add(
                    MemberProfile(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant,
                        org_unit_id=org_unit_id,
                        **{**item, "name": "合成" + item["name"], "org_name": org.name},
                    )
                )
            await db.commit()
            print(f"[ok] 已导入 {len(_SEED)} 名合成培养对象 -> tenant={tenant}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入培养对象名册种子数据")
    parser.add_argument("--tenant", required=True, help="测试租户ID")
    parser.add_argument("--org-unit-id", required=True, help="有效测试支部ID")
    args = parser.parse_args()
    asyncio.run(seed(args.tenant, args.org_unit_id))


if __name__ == "__main__":
    main()
