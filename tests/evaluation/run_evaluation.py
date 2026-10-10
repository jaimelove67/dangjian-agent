"""真实 API 评测器；未就绪或调用失败不能计为质量通过。

EVALUATION_ACCESS_TOKEN 提供已有登录令牌，不在命令行或结果中保存令牌。
python tests/evaluation/run_evaluation.py --base-url http://127.0.0.1:8000/api/v1
"""

import argparse
import asyncio
import json
import math
import os
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent


def grade_retrieval(sample, items, k=5):
    # 多片段可能来自同一文档；先去重，再计算文档召回。
    documents = []
    for item in items:
        identity = item["doc_id"]
        if identity not in {doc[0] for doc in documents}:
            documents.append((identity, item.get("metadata", {}).get("title", "")))
    expected = set(sample["expected_docs"])
    ranks = [
        rank
        for rank, (identity, title) in enumerate(documents, 1)
        if identity in expected or title in expected
    ]
    matched = {name for name in expected if any(name in doc for doc in documents[:k])}
    return {
        "recall_at_k": len(matched) / len(expected) if expected else 0,
        "precision_at_k": sum(rank <= k for rank in ranks) / k,
        "mrr": 1 / ranks[0] if ranks else 0,
    }


def grade_qa(sample, data):
    refused = data.get("refused") is True
    citations = data.get("citations", [])
    references = {int(value) for value in re.findall(r"\[(\d+)\]", data.get("answer", ""))}
    located = {
        citation.get("index")
        for citation in citations
        if citation.get("doc_id") and citation.get("chunk_id") and citation.get("content")
    }
    traceable = bool(references) and references <= located and not refused
    keywords = sample.get("expected_answer_contains", [])
    return {
        "refusal_correct": refused == sample["should_refuse"],
        "keyword_match": not refused
        and bool(keywords)
        and all(keyword in data.get("answer", "") for keyword in keywords),
        "citation_traceable": traceable,
    }


def summarize(retrieval, qa, latencies, samples, errors):
    normal = [result for result in qa if not result["should_refuse"]]
    refusal = [result for result in qa if result["should_refuse"]]

    def mean(values):
        return sum(values) / len(values) if values else None

    minimums = (
        len(samples) >= 200
        and sum(s["should_refuse"] for s in samples) >= 30
        and sum(s.get("category") == "时效测试" for s in samples) >= 20
    )
    return {
        "status": "failed" if errors else "completed",
        "errors": errors,
        "sample_size_meets_acceptance": minimums,
        "retrieval": {
            metric: mean([result[metric] for result in retrieval])
            for metric in ("recall_at_k", "precision_at_k", "mrr")
        },
        "qa": {
            "refusal_accuracy": mean([result["refusal_correct"] for result in refusal]),
            "false_refusal_rate": mean([not result["refusal_correct"] for result in normal]),
            "keyword_match_rate": mean([result["keyword_match"] for result in normal]),
            "citation_traceability_rate": mean([result["citation_traceable"] for result in normal]),
        },
        "request_latency_p95_seconds": (
            sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1] if latencies else None
        ),
        "notes": "关键词命中是自动化代理指标，不能代替专家答案正确性审查；延迟为串行样本请求，不能代替负载测试。",
    }


async def evaluate(base_url, token):
    samples = json.loads((ROOT / "qa_samples.json").read_text(encoding="utf-8"))
    retrieval_samples = json.loads((ROOT / "retrieval_samples.json").read_text(encoding="utf-8"))
    async with httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=150) as client:
        ready = await client.get("health/ready")
        if ready.status_code != 200:
            return {
                "status": "blocked",
                "reason": "后端、数据库结构或模型尚未就绪",
                "checks": ready.json().get("checks", {}),
            }
        if not token:
            return {
                "status": "blocked",
                "reason": "请通过 EVALUATION_ACCESS_TOKEN 配置已有登录令牌",
            }
        client.headers["Authorization"] = "Bearer " + token
        retrieval, qa, errors, latencies = [], [], [], []
        for phase, rows, endpoint, field in (
            ("retrieval", retrieval_samples, "knowledge/search", "query"),
            ("qa", samples, "qa", "question"),
        ):
            for sample in rows:
                started = time.perf_counter()
                try:
                    response = await client.post(endpoint, json={field: sample[field], "top_k": 5})
                    latencies.append(time.perf_counter() - started)
                    if response.status_code != 200 or response.json().get("code") != 0:
                        errors.append(
                            {
                                "phase": phase,
                                "id": sample["id"],
                                "http_status": response.status_code,
                            }
                        )
                        continue
                    data = response.json()["data"]
                    if phase == "retrieval":
                        retrieval.append(grade_retrieval(sample, data["items"]))
                    else:
                        qa.append(
                            {**grade_qa(sample, data), "should_refuse": sample["should_refuse"]}
                        )
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    errors.append(
                        {"phase": phase, "id": sample["id"], "reason": "请求失败或响应格式异常"}
                    )
        report = summarize(retrieval, qa, latencies, samples, errors)
        report["executed_samples"] = {"retrieval": len(retrieval), "qa": len(qa)}
        return report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "evaluation_summary.json")
    args = parser.parse_args()
    try:
        report = await evaluate(args.base_url, os.getenv("EVALUATION_ACCESS_TOKEN", ""))
    except (httpx.HTTPError, ValueError):
        report = {"status": "blocked", "reason": "无法连接就绪接口或响应无效"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
