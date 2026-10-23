"""按租户物理清理数据（私有化上线前清除演示 / 测试租户）

产品接口没有「删除租户」，只有 is_active=false 停用。要在正式库里彻底清掉
「测试大学」这类演示租户，用本脚本按 tenant_id 逐表删除，顺序由外键依赖推导。

用法（仓库根目录，需能连 DATABASE_URL）：

    # 1) 先看会删什么（默认 dry-run，不写库）
    .venv\\Scripts\\python.exe scripts/purge_tenant.py --tenant "测试大学"

    # 2) 确认真删（会先做一次预检，再逐表删除）
    .venv\\Scripts\\python.exe scripts/purge_tenant.py --tenant "测试大学" --yes

    # 3) 保留审计日志（合规要求留痕时加这个）
    .venv\\Scripts\\python.exe scripts/purge_tenant.py --tenant "测试大学" --yes --keep-audit

注意：
- 只删 tenant_id 命中的行；平台租户（PLATFORM_TENANT）与其它租户不受影响。
- 审计日志默认一起删；如要留痕，加 --keep-audit。
- 文件卷（uploads/<tenant_id>/）不自动删，脚本会打印路径，确认后手工删。
- 执行前务必 pg_dump 备份。
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402

# 导入全部模型，否则 Base.metadata 里没有表
import importlib  # noqa: E402
import pkgutil  # noqa: E402

import app.models as _models  # noqa: E402

for _, _name, _ in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"app.models.{_name}")

PLATFORM_TENANT = "PLATFORM_TENANT"
AUDIT_TABLE = "audit_logs"


async def resolve_tenant(conn, key: str) -> tuple[str, str] | None:
    """按 id 或名称定位租户，返回 (id, name)"""
    row = (
        await conn.execute(
            select(Base.metadata.tables["tenants"].c.id, Base.metadata.tables["tenants"].c.name)
            .where(Base.metadata.tables["tenants"].c.id == key)
        )
    ).first()
    if row:
        return row[0], row[1]
    row = (
        await conn.execute(
            select(Base.metadata.tables["tenants"].c.id, Base.metadata.tables["tenants"].c.name)
            .where(Base.metadata.tables["tenants"].c.name == key)
        )
    ).first()
    return (row[0], row[1]) if row else None


def delete_order() -> list:
    """子表先删：metadata.sorted_tables 是父表在前，反过来即可"""
    tables = list(Base.metadata.sorted_tables)
    return list(reversed(tables))


async def main() -> int:
    parser = argparse.ArgumentParser(description="按租户物理清理数据")
    parser.add_argument("--tenant", required=True, help="租户 ID 或租户名称")
    parser.add_argument("--yes", action="store_true", help="真正执行删除（默认只预演）")
    parser.add_argument("--keep-audit", action="store_true", help="保留 audit_logs 记录")
    parser.add_argument("--purge-files", action="store_true", help="同时删除 uploads/<tenant_id> 文件卷")
    args = parser.parse_args()

    async with engine.begin() as conn:
        found = await resolve_tenant(conn, args.tenant)
        if not found:
            print(f"[x] 未找到租户：{args.tenant}")
            return 2
        tenant_id, tenant_name = found
        if tenant_id == PLATFORM_TENANT:
            print("[x] 拒绝删除平台租户 PLATFORM_TENANT")
            return 2

        print(f"目标租户：{tenant_name} ({tenant_id})")
        print(f"模式：{'执行删除' if args.yes else '预演（不写库）'}")

        plan: list[tuple[str, int]] = []
        for table in delete_order():
            if args.keep_audit and table.name == AUDIT_TABLE:
                continue
            column = table.c.get("tenant_id") if "tenant_id" in table.c else None
            condition = column == tenant_id if column is not None else table.c.id == tenant_id
            count = await conn.scalar(select(func.count()).select_from(table).where(condition))
            if count:
                plan.append((table.name, int(count)))

        if not plan:
            print("[i] 该租户下没有残留数据")
        else:
            print(f"待清理 {len(plan)} 张表，共 {sum(n for _, n in plan)} 行：")
            for name, n in plan:
                print(f"    {name:32s} {n:>6d}")

        if not args.yes:
            print("\n[i] 预演结束，未改动数据库。确认无误后加 --yes 执行。")
            storage = Path(settings.FILE_STORAGE_DIR) / tenant_id
            print(f"[i] 文件卷（需手工删）：{storage}")
            return 0

        for table in delete_order():
            if args.keep_audit and table.name == AUDIT_TABLE:
                continue
            column = table.c.get("tenant_id") if "tenant_id" in table.c else None
            condition = column == tenant_id if column is not None else table.c.id == tenant_id
            result = await conn.execute(delete(table).where(condition))
            if result.rowcount:
                print(f"[del] {table.name:32s} {result.rowcount:>6d}")

    storage = Path(settings.FILE_STORAGE_DIR) / tenant_id
    if args.purge_files and storage.exists():
        shutil.rmtree(storage)
        print(f"[del] 文件卷 {storage}")
    elif storage.exists():
        print(f"[!] 文件卷仍保留，确认后手工删：{storage}")

    print("[ok] 完成。建议再跑一次预演确认已清空。")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
