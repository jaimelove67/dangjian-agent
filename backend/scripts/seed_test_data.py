"""重建「测试大学」演示数据（走真实 API，可重复执行）

在 dev_bootstrap 建好的 TEST_TENANT 之上补一整套演示数据：
组织树改名与补齐、10 名各阶段培养对象（含身份证号）、组织负责人与任职履历。

用法（仓库根目录，需后端在跑）：

    .venv\\Scripts\\python.exe - <<'PY'
    import sys, runpy
    sys.argv = ["seed_test_data.py", "--base-url", "http://127.0.0.1:18000"]
    runpy.run_path("scripts/seed_test_data.py", run_name="__main__")
    PY

说明：
- 全部走真实接口（组织改名/新建、名册登记、任职记录），因此受权限与校验约束并写审计，
  不直连数据库造假。
- 幂等：组织按名称、名册按姓名、任职按「组织+姓名+职务」查重，重复执行不会双份。
- 姓名、身份证号、电话均为虚构演示数据，上线前必须整体替换。
"""

from __future__ import annotations

import argparse
import sys

import httpx

# 身份证号校验位（GB 11643）：前 17 位算最后一位，演示号也要能过校验
_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK = "10X98765432"


def id_card(base17: str) -> str:
    total = sum(int(digit) * weight for digit, weight in zip(base17, _WEIGHTS))
    return base17 + _CHECK[total % 11]


# 组织：(key, 名称, 类型, 父级 key)。TEST_ORG/TEST_DEPT/TEST_BRANCH 由 dev_bootstrap 建，
# 这里只改名并补建其余；新建的组织 key 为 None。
ORGS: list[tuple[str | None, str, str, str | None]] = [
    (None, "测试大学党委", "school", None),
    (None, "计算机学院党总支", "department", "测试大学党委"),
    (None, "计算机学院教工党支部", "branch", "计算机学院党总支"),
    (None, "计算机学院学生党支部", "branch", "计算机学院党总支"),
    (None, "马克思主义学院党总支", "department", "测试大学党委"),
    (None, "马克思主义学院教工党支部", "branch", "马克思主义学院党总支"),
]

# 名册：(姓名, 身份证前17位, 阶段, 进入阶段日期, 所属组织)
MEMBERS: list[tuple[str, str, str, str, str]] = [
    ("苏晚晴", "43010219920315026", "activist", "2026-03-01", "计算机学院教工党支部"),
    ("何若谷", "43010319881107043", "candidate", "2025-11-01", "计算机学院教工党支部"),
    ("白露", "43010419950621088", "member", "2016-07-01", "计算机学院教工党支部"),
    ("陈嘉禾", "43010220040912015", "applicant", "2026-09-01", "计算机学院学生党支部"),
    ("林知远", "43010320030228037", "activist", "2026-04-15", "计算机学院学生党支部"),
    ("郑维舟", "43010420011205062", "candidate", "2025-10-20", "计算机学院学生党支部"),
    ("谢云帆", "43010520020719074", "probationary", "2026-05-10", "计算机学院学生党支部"),
    ("唐文清", "43010219910130053", "member", "2012-06-30", "计算机学院学生党支部"),
    ("顾长风", "43010319830906019", "member", "2010-09-01", "马克思主义学院教工党支部"),
    ("邵明德", "43010419860422071", "member", "2014-03-15", "马克思主义学院教工党支部"),
]

# 任职：(组织, 姓名, 职务, 电话, 任职日期, 是否主要负责人, 离任日期)
TERMS: list[tuple[str, str, str, str, str, bool, str | None]] = [
    ("测试大学党委", "沈国栋", "党委书记", "0731-88880001", "2020-03-01", True, None),
    ("测试大学党委", "韩启明", "党委书记", "0731-88880002", "2015-03-01", False, "2020-02-29"),
    ("计算机学院党总支", "程立诚", "党总支书记", "13800002222", "2021-09-01", True, None),
    ("计算机学院党总支", "罗伟东", "党总支书记", "13800002233", "2016-01-01", False, "2021-08-31"),
    ("计算机学院教工党支部", "邵明德", "党支部书记", "13900003333", "2024-06-01", True, None),
    ("计算机学院学生党支部", "唐文清", "党支部书记", "13700004444", "2022-09-01", True, None),
    ("马克思主义学院党总支", "顾长风", "党总支书记", "13600005555", "2023-02-01", True, None),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="重建测试大学演示数据")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--username", default="test-reviewer")
    parser.add_argument("--password", default="Test123456")
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/api/v1"
    client = httpx.Client(timeout=30)
    token = client.post(
        f"{base}/auth/login", json={"username": args.username, "password": args.password}
    ).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1) 组织：先改名（dev_bootstrap 建的三个组织 id 不变，账号归属不受影响），再补齐缺的。
    #    顺序不能反：先建会把"计算机学院党总支"当成新组织创建出来，旧组织留成一堆空壳。
    by_name = {row["name"]: row["id"] for row in client.get(
        f"{base}/admin/organizations", headers=headers).json()["data"]["items"]}
    for old, new in (("计算机学院党委", "计算机学院党总支"),
                     ("本科生第一党支部", "计算机学院教工党支部")):
        if old in by_name and new not in by_name:
            resp = client.patch(f"{base}/admin/organizations/{by_name[old]}",
                                headers=headers, json={"name": new})
            if resp.status_code < 400:
                by_name[new] = by_name.pop(old)
                print(f"[rename] {old} → {new}")
    for _, name, org_type, parent in ORGS:
        if name in by_name:
            continue
        payload = {"name": name, "org_type": org_type,
                   "parent_id": by_name[parent] if parent else None}
        resp = client.post(f"{base}/admin/organizations", headers=headers, json=payload)
        if resp.status_code >= 400:
            print(f"[skip] 组织 {name} 未建成：{resp.text[:120]}")
            continue
        by_name[name] = resp.json()["data"]["id"]
        print(f"[org] {name}")

    # 2) 名册：身份证号作为登录账号来源，一人一号
    roster = {row["name"] for row in client.get(
        f"{base}/member/roster?page=1&page_size=100", headers=headers).json()["data"]["items"]}
    for name, base17, stage, joined, org in MEMBERS:
        if name in roster:
            print(f"[skip] 名册已有 {name}")
            continue
        payload = {"name": name, "id_card_no": id_card(base17), "current_stage": stage,
                   "stage_joined_on": joined, "org_unit_id": by_name[org]}
        resp = client.post(f"{base}/member/roster", headers=headers, json=payload)
        mark = "ok" if resp.status_code < 400 else f"HTTP {resp.status_code} {resp.text[:80]}"
        print(f"[member] {name} {stage} → {mark}")

    # 3) 负责人与任职履历：先建任职（会回写组织现任），组织表单字段保持同源
    existing = {(row["org_unit_id"], row["name"], row["title"]) for row in client.get(
        f"{base}/admin/org-leaders", headers=headers).json()["data"]["items"]}
    for org, name, title, phone, started, primary, ended in TERMS:
        org_id = by_name[org]
        if (org_id, name, title) in existing:
            print(f"[skip] 任职已有 {org} {name}")
            continue
        payload = {"org_unit_id": org_id, "name": name, "title": title, "phone": phone,
                   "started_on": started, "is_primary": primary}
        if ended:
            payload["ended_on"] = ended
        resp = client.post(f"{base}/admin/org-leaders", headers=headers, json=payload)
        mark = "ok" if resp.status_code < 400 else f"HTTP {resp.status_code} {resp.text[:80]}"
        print(f"[term] {org} · {name} {title} → {mark}")

    print("\n--- 组织与负责人 ---")
    for row in client.get(f"{base}/admin/organizations", headers=headers).json()["data"]["items"]:
        print(f"  {row['org_type']:10s} {row['name']:16s} "
              f"{row['leader_name'] or '未登记':6s} {row['leader_title'] or '':8s} "
              f"{row['leader_phone'] or ''}")
    print("--- 名册 ---")
    items = client.get(f"{base}/member/roster?page=1&page_size=100", headers=headers).json()["data"]["items"]
    for row in sorted(items, key=lambda r: (r.get("org_name") or "", r["name"])):
        print(f"  {row['name']:5s} {row.get('id_card_masked') or '—':20s} {row.get('org_name') or ''}")
    print(f"合计 {len(items)} 人 / 组织 {len(by_name)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
