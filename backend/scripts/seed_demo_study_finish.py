"""演示数据收尾：把已建学习计划走完 生成提纲→提交→审核→活动→纪要→审核

在应用容器内运行：

    docker compose -f docker-compose.server.yml exec -T app \
        python /app/seed_demo_study_finish.py

每次写操作前都重新读取当前 revision，避免「内容已被修订」的并发保护拦截。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402

BASE = f"http://127.0.0.1:{settings.PORT}/api/v1"
YEAR = 2026
SCHOOL_ORG = "c24117e8-5ff8-425f-b2e7-8652708d02dc"
DEMO_PW = "Demo@2026hnky"
REASON = "演示数据初始化，供客户演示使用"


def login(username: str, password: str) -> httpx.Client:
    resp = httpx.Client(timeout=60.0).post(
        f"{BASE}/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    c = httpx.Client(timeout=120.0)
    c.headers.update({"Authorization": f"Bearer {resp.json()['data']['access_token']}"})
    return c


def call(c: httpx.Client, method: str, path: str, **kw) -> tuple[int, Any]:
    resp = getattr(c, method)(f"{BASE}{path}", **kw)
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:300]
    return resp.status_code, body


def show(tag: str, code: int, body: Any, limit: int = 240) -> None:
    import json

    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    print(f"[{'ok ' if code in (200, 201) else 'ERR'}] {tag} HTTP {code}: {text[:limit]}")


def plan_of(c: httpx.Client, plan_id: str) -> dict:
    code, body = call(c, "get", f"/study/plans/{plan_id}")
    if code != 200:
        raise RuntimeError(f"读取计划失败 {code} {body}")
    return body.get("data", {}) or {}


def main() -> None:
    sc = login("school_admin", DEMO_PW)
    ac = login("school_admin2", DEMO_PW)

    # 参学人员需要真实账号 id，先从平台管理员接口取本租户账号清单。
    admin = login("admin", "Pq7#mK2vXz9Rt4")
    code, body = call(
        admin, "get", "/admin/users", params={"tenant_id": "d5584666-6c8a-453c-abf3-036e02dc83e1"}
    )
    users = {i.get("username"): i.get("id") for i in (body.get("data", {}) or {}).get("items", [])}
    print("users:", len(users))

    code, body = call(sc, "get", "/study/plans", params={"org_unit_id": SCHOOL_ORG, "year": YEAR})
    rows = (body.get("data", {}) or {}).get("items") or []
    if not rows:
        raise RuntimeError("未找到学习计划")
    plan_id = rows[0].get("id")
    print(f"plan={plan_id}")

    plan = plan_of(sc, plan_id)
    doc_ids = plan.get("source_doc_ids") or []
    # 依据与提纲只在草案阶段补；已提交或已通过时重跑会撤销审核。
    if plan.get("review_status") not in ("draft", "rejected", "returned"):
        print(f"plan 已处于 {plan.get('review_status')}，跳过依据与提纲生成")
        doc_ids = []
    for item in (plan.get("items", []) if doc_ids else []):
        # 每条学习安排都要登记自己的政策依据，否则提交审核时判定摘录待补。
        code, body = call(
            sc,
            "patch",
            f"/study/plans/{plan_id}/items/{item['id']}",
            json={
                "topic": item.get("topic"),
                "scheduled_on": item.get("scheduled_on"),
                "responsible": item.get("responsible"),
                "source_doc_ids": doc_ids,
                "expected_revision": plan.get("revision"),
                "reason": REASON,
            },
        )
        show(f"item sources {str(item['id'])[:8]}", code, body, 160)
        plan = plan_of(sc, plan_id)

    plan = plan_of(sc, plan_id)
    for item in (plan.get("items", []) if doc_ids else []):
        code, body = call(
            sc,
            "post",
            f"/study/plans/{plan_id}/items/{item['id']}/generate-drafts",
            json={"expected_revision": plan.get("revision"), "reason": REASON},
        )
        show(f"drafts {str(item['id'])[:8]}", code, body, 160)
        plan = plan_of(sc, plan_id)

    if plan.get("review_status") in ("draft", "returned"):
        code, body = call(
            sc,
            "post",
            f"/study/plans/{plan_id}/submit",
            json={"expected_revision": plan.get("revision"), "reason": REASON},
        )
        show("submit plan", code, body, 200)
        plan = plan_of(sc, plan_id)

    if plan.get("review_status") in ("pending", "submitted"):
        code, body = call(
            ac,
            "post",
            f"/study/plans/{plan_id}/review",
            json={
                "decision": "approved",
                "expected_revision": plan.get("revision"),
                "reason": REASON,
            },
        )
        show("review plan", code, body, 200)
        plan = plan_of(sc, plan_id)

    print("plan review_status =", plan.get("review_status"))

    items = plan.get("items", [])
    if not items:
        return
    item_id = items[0].get("id")
    activity = items[0].get("activity") or {}
    act_id = (
        items[0].get("activity_id")
        or activity.get("id")
        or items[0].get("meeting_record_id")
        or None
    )
    if not act_id:
        code, body = call(
            sc,
            "post",
            f"/study/plans/{plan_id}/items/{item_id}/activity",
            json={"expected_revision": plan.get("revision"), "reason": REASON},
        )
        show("create activity", code, body, 200)
        act_id = (body.get("data", {}) or {}).get("id")
        if not act_id:
            plan = plan_of(sc, plan_id)
            act_id = (plan.get("items", [{}])[0].get("activity") or {}).get("id")

    if not act_id:
        print("[ERR] 未取得活动 id")
        return

    code, body = call(
        sc,
        "patch",
        f"/study/activities/{act_id}",
        json={
            "held_on": f"{YEAR}-10-10",
            "host": "李国华",
            "participants": [
                {"participant_id": users.get("school_admin", ""), "name": "李国华", "attended": True},
                {"participant_id": users.get("dept_admin", ""), "name": "王志远", "attended": True},
            ],
            "transcript": "学习要点：党章中关于党员义务与发展党员程序的规定。\n"
            "讨论共识：把党员教育管理落到日常，按月组织学习并留存记录。\n"
            "工作要求：各支部年底前完成培训台账归集，报党委备案。",
            "expected_revision": 1,
            "reason": REASON,
        },
    )
    show("patch activity", code, body, 240)

    # 纪要三栏目（学习要点/讨论共识/工作要求）由原文抽取生成，不手工编造。
    code, body = call(
        sc,
        "post",
        f"/study/activities/{act_id}/generate-minutes",
        json={"expected_revision": 2, "reason": REASON},
    )
    show("generate minutes", code, body, 240)

    code, body = call(sc, "get", f"/study/activities/{act_id}")
    rev = (body.get("data", {}) or {}).get("revision") or 2
    code, body = call(
        sc,
        "post",
        f"/study/activities/{act_id}/submit",
        json={"expected_revision": rev, "reason": REASON},
    )
    show("submit activity", code, body, 200)

    code, body = call(sc, "get", f"/study/activities/{act_id}")
    rev = (body.get("data", {}) or {}).get("revision") or rev
    code, body = call(
        ac,
        "post",
        f"/study/activities/{act_id}/review",
        json={"decision": "approved", "expected_revision": rev, "reason": REASON},
    )
    show("review activity", code, body, 200)

    # ---------- 考核收尾：任务审核通过后重新归集并确认 ----------
    print("\n===== 年度考核收尾 =====")
    code, body = call(
        sc, "post", "/assessment/recalculate", json={"org_unit_id": SCHOOL_ORG, "year": YEAR}
    )
    data = body.get("data", {}) or {}
    show("recalculate", code, data.get("results", [{}])[0].get("missing", []), 300)
    run_id = data.get("id")
    if run_id:
        code, body = call(
            ac,
            "post",
            f"/assessment/runs/{run_id}/review",
            json={
                "status": "approved",
                "opinion": "同意年度归集结果（演示）",
                "expected_revision": data.get("revision") or 1,
            },
        )
        show("review run", code, body, 300)


if __name__ == "__main__":
    main()
