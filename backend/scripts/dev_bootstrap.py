"""本地开发一次性初始化：租户、组织树与测试账号（幂等）

只允许 development/testing 环境。用法（仓库根目录）：

    .venv\\Scripts\\python.exe scripts/dev_bootstrap.py --password Test123456
    .venv\\Scripts\\python.exe scripts/dev_bootstrap.py --password Test123456 --with-sample-roles

说明：
- 创建平台租户 PLATFORM_TENANT、学校租户 TEST_TENANT。
- 在 TEST_TENANT 下创建学校根组织 TEST_ORG、院系 TEST_DEPT、支部 TEST_BRANCH。
- 默认创建三个账号（覆盖平台、学校、支部三级）：
    admin            system_admin      平台
    test-reviewer    school_admin      TEST_ORG
    branch-secretary branch_secretary  TEST_BRANCH
- 加 --with-sample-roles 后再创建四个基层账号（与 docs/USER_GUIDE.md 的账号表一致）：
    test-dept        department_admin  TEST_DEPT
    test-organizer   organizer         TEST_BRANCH
    test-member      member            TEST_BRANCH
    test-applicant   applicant         TEST_BRANCH
- 幂等：已存在则跳过；密码统一使用 --password。
- 普通党员与申请人的账号仍需组织人员在名册中关联本人档案后，
  才能查看本人档案与提交材料（脚本不做关联，避免替组织做认定）。
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
from app.models.org import OrgUnit  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

PLATFORM_ID = "PLATFORM_TENANT"
SCHOOL_TENANT_ID = "TEST_TENANT"

ORG_IDS = {"school": "TEST_ORG", "department": "TEST_DEPT", "branch": "TEST_BRANCH"}

USERS = [
    ("admin", "测试系统管理员", UserRole.SYSTEM_ADMIN, PLATFORM_ID, None),
    ("test-reviewer", "测试学校管理员", UserRole.SCHOOL_ADMIN, SCHOOL_TENANT_ID, "TEST_ORG"),
    (
        "branch-secretary",
        "测试支部书记",
        UserRole.BRANCH_SECRETARY,
        SCHOOL_TENANT_ID,
        "TEST_BRANCH",
    ),
]

# 与 docs/USER_GUIDE.md 的测试账号表保持一致；用 --with-sample-roles 显式启用。
SAMPLE_USERS = [
    ("test-dept", "测试院系管理员", UserRole.DEPARTMENT_ADMIN, SCHOOL_TENANT_ID, "TEST_DEPT"),
    ("test-organizer", "测试组织员", UserRole.ORGANIZER, SCHOOL_TENANT_ID, "TEST_BRANCH"),
    ("test-member", "测试党员", UserRole.MEMBER, SCHOOL_TENANT_ID, "TEST_BRANCH"),
    ("test-applicant", "测试申请人", UserRole.APPLICANT, SCHOOL_TENANT_ID, "TEST_BRANCH"),
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="本地开发初始化：租户、组织与测试账号")
    parser.add_argument("--password", required=True, help="测试账号统一密码（≥8 字符）")
    parser.add_argument(
        "--with-sample-roles",
        action="store_true",
        help="额外创建院系管理员、组织员、党员、申请人四个基层账号",
    )
    args = parser.parse_args()
    if settings.ENV not in {"development", "testing"}:
        raise RuntimeError("初始化脚本只允许在 development/testing 环境运行")
    if len(args.password) < 8:
        raise ValueError("密码至少 8 个字符")

    accounts = USERS + (SAMPLE_USERS if args.with_sample_roles else [])

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with bypass_tenant_filter():
        async with session_factory() as db:
            # ---------- 租户 ----------
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
                print(f"[ok] 平台租户：{PLATFORM_ID}")
            else:
                print(f"[skip] 平台租户已存在：{PLATFORM_ID}")

            school = await db.get(Tenant, SCHOOL_TENANT_ID)
            if school is None:
                db.add(
                    Tenant(
                        id=SCHOOL_TENANT_ID,
                        tenant_id=SCHOOL_TENANT_ID,
                        name="测试大学",
                        tenant_type="school",
                        parent_id=PLATFORM_ID,
                        path=f"/{PLATFORM_ID}/{SCHOOL_TENANT_ID}",
                        is_active=True,
                        config={"registration": {"status": "pending"}},
                    )
                )
                await db.flush()
                print(f"[ok] 学校租户：{SCHOOL_TENANT_ID}")
            else:
                print(f"[skip] 学校租户已存在：{SCHOOL_TENANT_ID}")

            # ---------- 组织 ----------
            for org_type, org_id in ORG_IDS.items():
                exist = await db.get(OrgUnit, org_id)
                if exist is not None:
                    print(f"[skip] 组织已存在：{org_id}")
                    continue
                parent_id = {"department": "TEST_ORG", "branch": "TEST_DEPT"}.get(org_type)
                path = (
                    f"/{ORG_IDS['school']}/{org_id}"
                    if org_id == "TEST_DEPT"
                    else f"/{ORG_IDS['school']}/{ORG_IDS['department']}/{org_id}"
                    if org_id == "TEST_BRANCH"
                    else f"/{org_id}"
                )
                db.add(
                    OrgUnit(
                        id=str(org_id),
                        tenant_id=SCHOOL_TENANT_ID,
                        name={
                            "TEST_ORG": "测试大学党委",
                            "TEST_DEPT": "计算机学院党委",
                            "TEST_BRANCH": "本科生第一党支部",
                        }[org_id],
                        org_type=org_type,
                        parent_id=parent_id,
                        path=path,
                        is_active=True,
                    )
                )
                await db.flush()
                print(f"[ok] 组织：{org_id} ({org_type})")

            # ---------- 用户 ----------
            for username, name, role, tenant_id, org_id in accounts:
                existing = await db.execute(select(User).where(User.username == username))
                if existing.scalar_one_or_none() is not None:
                    print(f"[skip] 用户已存在：{username}")
                    continue
                if org_id is not None:
                    org = await db.get(OrgUnit, org_id)
                    if org is None or org.tenant_id != SCHOOL_TENANT_ID:
                        raise ValueError(f"组织 {org_id} 不存在或不属于学校租户")
                db.add(
                    User(
                        id=str(uuid.uuid4()),
                        username=username,
                        name=name,
                        password_hash=hash_password(args.password),
                        role=role,
                        tenant_id=tenant_id,
                        org_unit_id=org_id,
                        is_active=True,
                    )
                )
                await db.flush()
                print(f"[ok] 用户：{username} ({role.value})")

            await db.commit()

    print(
        "[next] 普通党员与申请人还需在 /members 中由组织人员关联本人档案后，"
        "才能查看本人档案与提交个人材料。"
    )


if __name__ == "__main__":
    asyncio.run(main())
