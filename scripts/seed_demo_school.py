"""演示数据初始化：学校租户、组织树与各角色账号（走真实 API，幂等）

在应用容器内运行（容器已具备 httpx 与后端接口）：

    docker compose -f docker-compose.server.yml exec -T app \
        python /app/seed_demo_school.py --admin-password <平台管理员密码>

说明：
- 全程调用真实业务接口（POST /admin/tenants、/admin/organizations、/admin/users），
  因此受权限校验、组织树规则约束，并写入审计日志；不直连数据库造假。
- 幂等：同名租户/组织/已存在用户名会跳过（接口返回 409 时按已存在处理）。
- 创建的均为**演示用虚构数据**，学校、院系、支部与人员姓名均为示例，
  正式使用前应由校方核对后重建或改名。
- 输出组织与账号清单（含 id），便于后续名册、知识库等脚本引用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402

BASE = None  # 由 --base-url 或 settings.PORT 推导

SCHOOL_NAME = "湖南科技职业技术学院"
SCHOOL_TENANT_KEY = "DEMO_SCHOOL"

# key -> (名称, 类型, 父级 key)
ORGS: list[tuple[str, str, str, str | None]] = [
    ("school", "湖南科技职业技术学院党委", "school", None),
    ("dept1", "信息工程学院党总支", "department", "school"),
    ("dept2", "机电工程学院党总支", "department", "school"),
    ("branch1", "信息工程学院教工第一党支部", "branch", "dept1"),
    ("branch2", "信息工程学院学生第一党支部", "branch", "dept1"),
    ("branch3", "机电工程学院学生第二党支部", "branch", "dept2"),
]

# 用户名 -> (姓名, 角色, 组织 key)
USERS: list[tuple[str, str, str, str]] = [
    ("school_admin", "李国华", "school_admin", "school"),
    ("dept_admin", "王志远", "department_admin", "dept1"),
    ("branch_sec", "陈晓明", "branch_secretary", "branch1"),
    ("organizer", "刘芳", "organizer", "branch1"),
    ("member01", "赵强", "member", "branch1"),
    ("applicant01", "孙悦", "applicant", "branch1"),
]


def _post(client: httpx.Client, path: str, payload: dict, params: dict | None = None):
    resp = client.post(f"{BASE}{path}", json=payload, params=params)
    if resp.status_code in (200, 201):
        return True, resp.json().get("data", {}), resp.status_code
    return False, {"detail": resp.text[:200]}, resp.status_code


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="演示数据：学校租户、组织树与账号")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--password", default="Demo@2026hnky", help="演示账号统一密码（>=12 字符）")
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    BASE = (args.base_url or f"http://127.0.0.1:{settings.PORT}/api/v1").rstrip("/")
    if len(args.password) < 12:
        raise ValueError("演示账号密码至少 12 个字符（UserCreate 约束）")

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{BASE}/auth/login",
            json={"username": args.admin_username, "password": args.admin_password},
        )
        resp.raise_for_status()
        token = resp.json()["data"]["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        # ---------- 学校租户 ----------
        ok, data, code = _post(
            client,
            "/admin/tenants",
            {"name": SCHOOL_NAME, "tenant_type": "school", "parent_id": "PLATFORM_TENANT"},
        )
        if ok:
            tenant_id = data.get("id") or data.get("tenant_id")
            print(f"[ok] 学校租户 {SCHOOL_NAME} -> {tenant_id}")
        else:
            # 已存在时回查列表取 id
            listing = client.get(f"{BASE}/admin/tenants").json()
            items = listing.get("data", {}).get("items", [])
            match = next((i for i in items if i.get("name") == SCHOOL_NAME), None)
            if match is None:
                raise RuntimeError(f"学校租户创建失败 HTTP {code}: {data}")
            tenant_id = match.get("id")
            print(f"[skip] 学校租户已存在 -> {tenant_id}")

        params = {"tenant_id": tenant_id}

        # ---------- 组织树 ----------
        listing = client.get(f"{BASE}/admin/organizations", params=params).json()
        existing_orgs = {i["name"]: i["id"] for i in listing.get("data", {}).get("items", [])}
        org_ids: dict[str, str] = {}
        for key, name, org_type, parent_key in ORGS:
            if name in existing_orgs:
                org_ids[key] = existing_orgs[name]
                print(f"[skip] 组织已存在：{name}")
                continue
            payload: dict = {"name": name, "org_type": org_type}
            if parent_key:
                payload["parent_id"] = org_ids[parent_key]
            ok, data, code = _post(client, "/admin/organizations", payload, params)
            if not ok:
                raise RuntimeError(f"组织 {name} 创建失败 HTTP {code}: {data}")
            org_ids[key] = data.get("id")
            print(f"[ok] 组织：{name} ({org_type}) -> {org_ids[key]}")

        # ---------- 账号 ----------
        for username, name, role, org_key in USERS:
            ok, data, code = _post(
                client,
                "/admin/users",
                {
                    "username": username,
                    "name": name,
                    "password": args.password,
                    "role": role,
                    "org_unit_id": org_ids[org_key],
                },
                params,
            )
            if ok:
                print(f"[ok] 账号：{username} ({role}) -> {org_key}")
            elif code == 409:
                print(f"[skip] 账号已存在：{username}")
            else:
                print(f"[FAIL] 账号 {username} HTTP {code}: {data}")

    print("\n" + json.dumps({"tenant_id": tenant_id, "org_ids": org_ids}, ensure_ascii=False))


if __name__ == "__main__":
    main()
