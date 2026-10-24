"""为已由DBA建立的非所有者运行账号生成/应用最小权限。默认只输出SQL。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402

from app.core.database_privileges import UNSAFE_RUNTIME_ROLE  # noqa: E402
from app.db.session import engine  # noqa: E402


def validate_role(role: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", role):
        raise ValueError("角色名只允许小写字母、数字、下划线")
    return role


def statements(role: str) -> list[str]:
    validate_role(role)
    quoted = '"' + role + '"'
    return [
        f"GRANT USAGE ON SCHEMA public TO {quoted}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}",
        f"REVOKE ALL ON audit_logs FROM {quoted}",
        f"GRANT SELECT, INSERT ON audit_logs TO {quoted}",
        f"REVOKE CREATE ON SCHEMA public FROM {quoted}",
    ]


async def apply(role: str) -> None:
    validate_role(role)
    async with engine.begin() as conn:
        unsafe = await conn.scalar(text("SELECT " + UNSAFE_RUNTIME_ROLE), {"role": role})
        if unsafe:
            raise ValueError("账号必须存在且不能拥有/继承表、数据库所有者或高权限角色")
        for statement in statements(role):
            await conn.execute(text(statement))
        allowed = await conn.scalar(
            text(
                "SELECT has_table_privilege(:role,'audit_logs','SELECT') "
                "AND has_table_privilege(:role,'audit_logs','INSERT') "
                "AND NOT has_table_privilege(:role,'audit_logs','UPDATE') "
                "AND NOT has_table_privilege(:role,'audit_logs','DELETE') "
                "AND NOT has_table_privilege(:role,'audit_logs','TRUNCATE') "
                "AND NOT has_any_column_privilege(:role,'audit_logs','UPDATE')"
            ),
            {"role": role},
        )
        if not allowed:
            raise ValueError("账号从其他授权继承了审计修改权限，应用已回滚")
    await engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role", required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    try:
        if a.apply:
            asyncio.run(apply(a.role))
            print(json.dumps({"status": "applied", "role": a.role, "audit": "select_insert_only"}))
        else:
            print(";\n".join(statements(a.role)) + ";")
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
