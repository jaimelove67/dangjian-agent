"""低基数运行指标，不使用正文、对象 ID 或个人身份作为指标标签。"""

from prometheus_client import Counter, Histogram

REQUESTS = Counter("party_requests_total", "Requests", ["module", "method", "result"])
LATENCY = Histogram(
    "party_request_seconds",
    "Request duration",
    ["module"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 3, 5, 10, 30, 60, 120),
)
MODEL_CALLS = Counter("party_model_calls_total", "Model calls", ["type", "result"])
MODEL_LATENCY = Histogram("party_model_seconds", "Model call duration", ["type"])
RETRIEVAL_SCORE = Histogram(
    "party_retrieval_top_score", "Top retrieval score", buckets=(0.1, 0.3, 0.5, 0.7, 0.9, 1)
)


def observe_request(module: str, method: str, status: int, duration: float) -> None:
    result = "denied" if status in (401, 403, 429) else "failed" if status >= 400 else "success"
    REQUESTS.labels(module, method, result).inc()
    LATENCY.labels(module).observe(duration)
