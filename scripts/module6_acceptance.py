"""模块6严格质量、准入、获准模型连通与完整问答负载验收。未执行不计通过。"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


async def load(
    base: str, questions: list[str], requests: int, concurrency: int, target: float = 3.0
) -> dict[str, Any]:
    admin = os.environ.get("MODULE6_ADMIN_TOKEN")
    token = os.environ.get("MODULE6_LOAD_TOKEN")
    if not admin or not token or not questions:
        return {
            "status": "pending_configuration",
            "reason": "official_scope_tokens_or_questions_missing",
            "requests": 0,
        }
    if not base.startswith("https://") and not base.startswith(
        ("http://127.0.0.1:", "http://localhost:")
    ):
        raise ValueError("验收服务必须HTTPS或明确本机地址")
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(base_url=base, timeout=60, follow_redirects=False) as client:
        policy = await client.get(
            "/api/v1/admin/governance", headers={"Authorization": "Bearer " + admin}
        )
        data = policy.json().get("data", {}) if policy.status_code == 200 else {}
        model = data.get("values", {}).get("model_policy", {})
        if data.get("admission", {}).get("status") != "configured" or not (
            model.get("external_enabled") or model.get("local_sensitive_enabled")
        ):
            return {
                "status": "pending_configuration",
                "reason": "school_admission_or_model_approval_pending",
                "requests": 0,
            }
        semaphore = asyncio.Semaphore(concurrency)
        samples = []

        async def sample(index: int) -> None:
            async with semaphore:
                started = time.monotonic()
                result = "failed"
                try:
                    response = await client.post(
                        "/api/v1/qa",
                        headers=headers,
                        json={"question": questions[index % len(questions)]},
                    )
                    body = response.json()
                    value = body.get("data") or {}
                    if (
                        response.status_code == 200
                        and body.get("code") == 0
                        and value.get("answer")
                        and (value.get("citations") and value.get("refused") is False)
                    ):
                        result = "success"
                except (httpx.HTTPError, ValueError):
                    pass
                samples.append({"seconds": time.monotonic() - started, "result": result})

        await asyncio.gather(*(sample(index) for index in range(requests)))
    successful = sorted(x["seconds"] for x in samples if x["result"] == "success")
    p95 = successful[max(0, math.ceil(len(successful) * 0.95) - 1)] if successful else None
    passed = len(successful) == requests and p95 is not None and p95 <= target
    return {
        "status": "passed" if passed else "failed",
        "requests": requests,
        "concurrency": concurrency,
        "successful_full_qa": len(successful),
        "failed": requests - len(successful),
        "p95_full_successful_seconds": p95,
        "target_seconds": target,
        "samples": samples,
    }


def quality(report_dir: Path) -> dict[str, Any]:
    report_dir = report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    targets = [
        "app",
        *[str(path.relative_to(ROOT)) for path in sorted((ROOT / "scripts").glob("module6_*.py"))],
    ]
    checks = [
        ("format", [sys.executable, "-m", "black", "--check", *targets], ROOT),
        ("imports", [sys.executable, "-m", "isort", "--check-only", *targets], ROOT),
        ("lint", [sys.executable, "-m", "flake8", *targets], ROOT),
        ("types", [sys.executable, "-m", "mypy", "app"], ROOT),
        (
            "backend",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--cov=app",
                "--cov-fail-under=80",
                "--cov-report=json:" + str(report_dir / "coverage.json"),
            ],
            ROOT,
        ),
        ("frontend", [npm, "run", "build"], ROOT / "frontend"),
        (
            "frontend_interaction",
            [
                "node",
                "scripts/verify-module6.mjs",
                "--serve",
                "--out",
                str(report_dir / "frontend"),
            ],
            ROOT / "frontend",
        ),
        ("vulnerabilities", [sys.executable, "-m", "pip_audit", "--strict"], ROOT),
    ]
    results = {}
    for name, command, cwd in checks:
        with (report_dir / (name + ".log")).open("w", encoding="utf-8") as stream:
            try:
                run = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
                    check=False,
                )
                results[name] = {
                    "status": "passed" if run.returncode == 0 else "failed",
                    "exit_code": run.returncode,
                }
            except (OSError, subprocess.TimeoutExpired) as exc:
                results[name] = {"status": "unexecuted_or_failed", "error": type(exc).__name__}
    return {
        "status": "passed" if all(v["status"] == "passed" for v in results.values()) else "failed",
        "python": sys.version.split()[0],
        "coverage_gate": 80,
        "checks": results,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("quality")
    q.add_argument("--report-dir", type=Path, default=ROOT / "tmp/module6-quality")
    load_parser = sub.add_parser("load")
    load_parser.add_argument("--base-url", required=True)
    load_parser.add_argument("--questions", type=Path, required=True)
    load_parser.add_argument("--requests", type=int, default=100)
    load_parser.add_argument("--concurrency", type=int, default=5)
    load_parser.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == "quality":
            result = quality(a.report_dir)
            output = a.report_dir / "report.json"
        else:
            if not 1 <= a.requests <= 10000 or not 1 <= a.concurrency <= 100:
                raise ValueError("负载规模无效")
            questions = json.loads(a.questions.read_text(encoding="utf-8-sig"))
            if not isinstance(questions, list) or any(
                not isinstance(x, str) or not x.strip() for x in questions
            ):
                raise ValueError("问题清单必须是非空字符串数组")
            result = asyncio.run(load(a.base_url, questions, a.requests, a.concurrency))
            output = a.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "samples"}, ensure_ascii=False))
        return (
            0
            if result["status"] == "passed"
            else 2 if result["status"] == "pending_configuration" else 1
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
