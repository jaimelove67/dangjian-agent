"""演示业务数据：中心组学习计划/活动 + 年度考核指标/任务/归集/审核

在应用容器内运行：

    docker compose -f docker-compose.server.yml exec -T app \
        python /app/seed_demo_business.py

全程调用真实业务接口（受权限、状态机与组织归属约束，并写审计日志）。
每个阶段独立 try，失败不影响后续阶段，便于逐步补齐。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402

BASE = f"http://127.0.0.1:{settings.PORT}/api/v1"
YEAR = 2026

# 租户与组织 ID 由部署决定，全库重建后必然变化；下面的默认值只是历史部署的兜底，
# 实际运行请以 seed_demo_school.py 的输出为准，用命令行参数覆盖。
SCHOOL_ORG = "c24117e8-5ff8-425f-b2e7-8652708d02dc"
DEPT1_ORG = "974a8cf4-2f5d-415a-92a1-e90f55e6382e"
TENANT = "d5584666-6c8a-453c-abf3-036e02dc83e1"

ADMIN = ("admin", "Pq7#mK2vXz9Rt4")
DEMO_PW = "Demo@2026hnky"

REASON = "演示数据初始化，供客户演示使用"


def _apply_args() -> None:
    """命令行覆盖租户与组织 ID，避免重建后脚本仍指向已不存在的旧 ID。"""
    global BASE, SCHOOL_ORG, DEPT1_ORG, TENANT
    import argparse

    parser = argparse.ArgumentParser(description="演示业务数据种子")
    parser.add_argument("--base-url", default=None, help="后端接口地址")
    parser.add_argument("--tenant", default=TENANT, help="学校租户 ID")
    parser.add_argument("--school-org", default=SCHOOL_ORG, help="学校党委组织 ID")
    parser.add_argument("--dept-org", default=DEPT1_ORG, help="院系党总支组织 ID")
    args = parser.parse_args()
    if args.base_url:
        BASE = args.base_url
    TENANT = args.tenant
    SCHOOL_ORG = args.school_org
    DEPT1_ORG = args.dept_org


_apply_args()


def login(client: httpx.Client, username: str, password: str) -> httpx.Client:
    resp = client.post(
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


def show(tag: str, code: int, body: Any, limit: int = 300) -> None:
    text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    flag = "ok " if code in (200, 201) else "ERR"
    print(f"[{flag}] {tag} HTTP {code}: {text[:limit]}")


def stage(name: str):
    print(f"\n===== {name} =====")


def main() -> None:
    # ---------- 0. 账号 id ----------
    stage("账号清单")
    admin_c = login(httpx.Client(timeout=60.0), *ADMIN)
    code, body = call(admin_c, "get", "/admin/users", params={"tenant_id": TENANT})
    users = {}
    if code == 200:
        for item in body.get("data", {}).get("items", []):
            users[item.get("username")] = item.get("id")
    show("users", code, list(users.items()))

    # ---------- 1. 中心组学习 ----------
    stage("中心组学习")
    try:
        sc = login(httpx.Client(timeout=60.0), "school_admin", DEMO_PW)

        # 演示资料入库时默认为 expired（未核验），学习模块只认现行有效依据，
        # 这里通过正式状态接口把用作政策依据的几篇置为 effective。
        for doc_id in [
            "DEMO-DOC-PARTY-CONSTITUTION",
            "DEMO-DOC-MEMBER-EDU-REGULATION",
            "DEMO-DOC-BRANCH-REGULATION",
        ]:
            code, body = call(
                sc,
                "patch",
                f"/knowledge-docs/{doc_id}/status",
                json={"status": "effective", "reason": REASON},
            )
            show(f"status {doc_id}", code, body, 200)

        code, body = call(
            sc, "get", "/study/materials", params={"org_unit_id": SCHOOL_ORG, "q": "党员"}
        )
        show("materials", code, body, 400)
        doc_ids = [
            i.get("doc_id") for i in (body.get("data", {}).get("sources", []) if code == 200 else [])
        ][:5]
        show("doc ids", code, doc_ids, 200)

        code, body = call(
            sc,
            "post",
            "/study/plans",
            json={
                "org_unit_id": SCHOOL_ORG,
                "year": YEAR,
                "title": f"{YEAR}年党委理论学习中心组学习计划（演示）",
                "priorities": [
                    "深入学习党章党规",
                    "学习党员教育管理工作条例",
                    "学习支部工作条例",
                ],
                "responsible": "李国华",
                "source_doc_ids": doc_ids,
                "reason": REASON,
            },
        )
        show("create plan", code, body, 500)
        plan_id = (body.get("data", {}) or {}).get("id") if code in (200, 201) else None
        if plan_id is None:  # 同年同组织已存在时复用
            code, body = call(
                sc, "get", "/study/plans", params={"org_unit_id": SCHOOL_ORG, "year": YEAR}
            )
            rows = (body.get("data", {}) or {}).get("items") or (body.get("data", {}) or {}).get(
                "plans"
            ) or []
            plan_id = rows[0].get("id") if rows else None
            show("reuse plan", code, plan_id, 200)

        if plan_id and doc_ids:  # 补全政策依据（首次创建时资料尚未置为有效）
            code, body = call(
                sc,
                "patch",
                f"/study/plans/{plan_id}",
                json={
                    "expected_revision": 1,
                    "title": f"{YEAR}年党委理论学习中心组学习计划（演示）",
                    "priorities": [
                        "深入学习党章党规",
                        "学习党员教育管理工作条例",
                        "学习支部工作条例",
                    ],
                    "responsible": "李国华",
                    "source_doc_ids": doc_ids,
                    "reason": REASON,
                },
            )
            show("patch plan sources", code, body, 250)

        if plan_id:
            code, body = call(sc, "get", f"/study/plans/{plan_id}")
            show("plan detail", code, body, 600)
            items = (body.get("data", {}) or {}).get("items", [])
            item_id = items[0].get("id") if items else None
            revision = (body.get("data", {}) or {}).get("revision") or 1

            # 年度重点须先按政策依据生成提纲草稿，否则提交审核时判定依据待补。
            for it in items:
                code, body = call(
                    sc,
                    "post",
                    f"/study/plans/{plan_id}/items/{it.get('id')}/generate-drafts",
                    json={"expected_revision": revision, "reason": REASON},
                )
                show(f"drafts {it.get('id')[:8]}", code, body, 200)
            revision = (body.get("data", {}) or {}).get("revision") or revision

            code, body = call(
                sc,
                "post",
                f"/study/plans/{plan_id}/submit",
                json={"expected_revision": revision, "reason": REASON},
            )
            show("submit plan", code, body, 300)

            ac = login(httpx.Client(timeout=60.0), "school_admin2", DEMO_PW)
            code, body = call(
                ac,
                "post",
                f"/study/plans/{plan_id}/review",
                json={"decision": "approved", "expected_revision": revision, "reason": REASON},
            )
            show("review plan", code, body, 300)

            if item_id:
                code, body = call(
                    sc,
                    "post",
                    f"/study/plans/{plan_id}/items/{item_id}/activity",
                    json={"expected_revision": revision, "reason": REASON},
                )
                show("create activity", code, body, 400)
                act_id = (body.get("data", {}) or {}).get("id") if code in (200, 201) else None
                if act_id:
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
                            "transcript": "学习要点：党章中关于党员义务的规定。\n讨论共识：把党员教育管理落到日常。\n工作要求：各支部按月组织学习并留存记录。",
                            "expected_revision": 1,
                            "reason": REASON,
                        },
                    )
                    show("patch activity", code, body, 400)
                    code, body = call(
                        sc,
                        "post",
                        f"/study/activities/{act_id}/submit",
                        json={"expected_revision": 1, "reason": REASON},
                    )
                    show("submit activity", code, body, 300)
                    code, body = call(
                        ac,
                        "post",
                        f"/study/activities/{act_id}/review",
                        json={"decision": "approved", "expected_revision": 1, "reason": REASON},
                    )
                    show("review activity", code, body, 300)
    except Exception as exc:  # noqa: BLE001 - 演示脚本，阶段失败不影响后续
        print(f"[ERR] 学习阶段异常：{exc}")

    # ---------- 2. 年度考核 ----------
    stage("年度考核")
    try:
        sc = login(httpx.Client(timeout=60.0), "school_admin", DEMO_PW)
        code, body = call(
            sc,
            "post",
            "/assessment/indicators",
            json={
                "org_unit_id": SCHOOL_ORG,
                "year": YEAR,
                "code": "DEMO-INDEX-01",
                "name": "党员教育培训完成率（演示）",
                "requirement": "各支部按年度计划完成党员教育培训，按实际完成人数统计。",
                "formula": "sum",
                "source": "manual",
                "source_options": {"measure": "sum"},
                "target": 100,
                "comparison": "gte",
                "unit": "人",
                "period_start": f"{YEAR}-01-01",
                "period_end": f"{YEAR}-12-31",
                "effective_from": None,
                "required_evidence": [],
                "confirmed": True,
                "confirmation_note": REASON,
                "expected_version": 0,
            },
        )
        show("create indicator", code, body, 500)

        code, body = call(
            sc,
            "post",
            "/assessment/tasks",
            json={
                "org_unit_id": DEPT1_ORG,
                "year": YEAR,
                "indicator_code": "DEMO-INDEX-01",
                "title": "信息工程学院党员教育培训任务（演示）",
                "owner_id": users.get("dept_admin"),
                "due_date": f"{YEAR}-11-30",
                "declared_progress": 60,
                "manual_value": 45,
                "basis": "按支部上报的培训记录统计（演示数据）",
                "completed_on": f"{YEAR}-10-12",
            },
        )
        show("create task", code, body, 500)
        task_id = (body.get("data", {}) or {}).get("id") if code in (200, 201) else None

        # 任务须先经人工审核通过，否则归集结果会记为「含未审核内容」。
        # 注意：考核模块没有 GET /assessment/tasks 列表接口（只有 /assessment/workspace），
        # 这里直接审核刚创建的任务，避免依赖不存在的列表路由。
        ac = login(httpx.Client(timeout=60.0), "school_admin2", DEMO_PW)
        if task_id:
            task_revision = (body.get("data", {}) or {}).get("revision") or 1
            if (body.get("data", {}) or {}).get("review_status") == "approved":
                show("review task", 200, "已审核，跳过", 120)
            else:
                code, body = call(
                    ac,
                    "post",
                    f"/assessment/tasks/{task_id}/review",
                    json={
                        "status": "approved",
                        "opinion": "同意任务填报（演示）",
                        "expected_revision": task_revision,
                    },
                )
                show(f"review task {task_id[:8]}", code, body, 200)

        code, body = call(
            sc,
            "post",
            "/assessment/recalculate",
            json={"org_unit_id": SCHOOL_ORG, "year": YEAR},
        )
        show("recalculate", code, body, 1800)
        data = body.get("data", {}) or {}
        run_id = data.get("run_id") or data.get("id") if code in (200, 201) else None
        show("run id", code, run_id, 120)
        if run_id:
            missing = [r.get("missing") for r in (data.get("results") or [])]
            if any(missing):
                print(f"[WARN] 归集仍有缺项，跳过人工确认：{missing}")
            else:
                ac = login(httpx.Client(timeout=60.0), "school_admin2", DEMO_PW)
                code, body = call(
                    ac,
                    "post",
                    f"/assessment/runs/{run_id}/review",
                    json={
                        "status": "approved",
                        "opinion": "同意归集结果（演示）",
                        "expected_revision": data.get("revision") or 1,
                    },
                )
                show("review run", code, body, 400)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] 考核阶段异常：{exc}")


if __name__ == "__main__":
    main()
