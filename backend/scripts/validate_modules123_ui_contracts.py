"""用实际后端输入模型验证浏览器捕获的请求；不连接数据库或模型服务。"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.embeddings import EmbedRequest  # noqa: E402
from app.api.v1.knowledge import DocumentMetadataPatch  # noqa: E402
from app.schemas import (  # noqa: E402
    meeting,
    member_ext,
    member_review,
    member_selection,
    member_transfer,
    member_upper_report,
)

CONTRACTS = [
    ("POST", r"/embeddings/embed", EmbedRequest),
    ("PATCH", r"/knowledge-docs/[^/]+/metadata", DocumentMetadataPatch),
    ("POST", r"/member-full/batches", member_ext.BatchCreate),
    ("PATCH", r"/member-full/profiles/[^/]+", member_ext.ProfileUpdate),
    ("POST", r"/member-full/profiles/[^/]+/materials", member_ext.MaterialCreate),
    ("POST", r"/member-full/materials/[^/]+/review", member_ext.MaterialReview),
    ("POST", r"/member-full/profiles/[^/]+/transition", member_ext.TransitionRequest),
    ("POST", r"/member-full/profiles/[^/]+/cultivation", member_ext.CultivationCreate),
    ("POST", r"/member-full/reminders/[^/]+/resolve", member_ext.ReminderResolve),
    ("POST", r"/member-full/votes", member_ext.VoteBatch),
    ("POST", r"/member-full/scoring", member_ext.ScoringRequest),
    ("POST", r"/member-full/archive-check", member_ext.ArchiveCheckRun),
    ("POST", r"/meeting/records", meeting.ActivityCreate),
    ("PATCH", r"/meeting/records/[^/]+", meeting.ActivityUpdate),
    (
        "POST",
        r"/meeting/records/[^/]+/(generate-agenda|generate-minutes|submit|archive)",
        meeting.RevisionRequest,
    ),
    ("POST", r"/meeting/records/[^/]+/review", meeting.ReviewRequest),
    ("POST", r"/meeting/records/[^/]+/tasks", meeting.TaskCreate),
    ("PATCH", r"/meeting/tasks/[^/]+", meeting.TaskUpdate),
    ("POST", r"/meeting/tasks/[^/]+/handle", meeting.TaskHandle),
    ("POST", r"/meeting/member-reviews/launch", member_review.ReviewLaunch),
    ("POST", r"/meeting/member-reviews", member_review.ReviewCreate),
    ("PATCH", r"/meeting/member-reviews/[^/]+", member_review.ReviewUpdate),
    ("POST", r"/meeting/member-reviews/[^/]+/submit", member_review.ReviewSubmit),
    ("POST", r"/meeting/member-reviews/[^/]+/review", member_review.ReviewDecision),
    ("POST", r"/member-full/transfers", member_transfer.TransferCreate),
    ("POST", r"/member-full/transfers/[^/]+/settle", member_transfer.TransferSettle),
    ("POST", r"/member-full/transfers/[^/]+/revoke", member_transfer.TransferRevoke),
    ("POST", r"/member-full/upper-reports", member_upper_report.UpperReportCreate),
    ("POST", r"/member-full/upper-reports/[^/]+/settle", member_upper_report.UpperReportSettle),
    ("POST", r"/member-full/upper-reports/[^/]+/revoke", member_upper_report.UpperReportRevoke),
    ("POST", r"/member-full/selections", member_selection.SelectionCreate),
    ("PATCH", r"/member-full/selections/[^/]+", member_selection.SelectionUpdate),
    ("POST", r"/member-full/selections/[^/]+/submit", member_selection.SelectionSubmit),
    ("POST", r"/member-full/selections/[^/]+/review", member_selection.SelectionDecision),
    (
        "POST",
        r"/member-full/league-recommendations",
        member_selection.LeagueRecommendationCreate,
    ),
    (
        "POST",
        r"/member-full/league-recommendations/[^/]+/revoke",
        member_selection.LeagueRecommendationRevoke,
    ),
]


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/modules123-ui/contract-requests.json")
    requests = json.loads(source.read_text(encoding="utf-8"))
    if not requests:
        raise ValueError("请求记录为空，请先完成浏览器验证。")
    validated = Counter()
    for request in requests:
        method, path, body = request["method"], request["path"], request["body"]
        contract = next(
            (
                model
                for verb, pattern, model in CONTRACTS
                if method == verb and re.fullmatch(pattern, path)
            ),
            None,
        )
        if contract is None:
            raise ValueError(f"未映射的请求契约：{method} {path}")
        parsed = contract.model_validate(body)
        if contract is meeting.TaskCreate and parsed.task_text != body["task_text"]:
            raise ValueError("任务原文摘录在输入校验时发生变化。")
        if contract is meeting.ActivityUpdate and parsed.transcript != body.get("transcript"):
            raise ValueError("会议原文在输入校验时发生变化。")
        validated[contract.__name__] += 1
    result = {"request_count": len(requests), "contracts": dict(validated), "schema_only": True}
    source.with_name("contract-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(requests)} 条浏览器请求通过实际后端输入模型校验；未连接业务服务。")


if __name__ == "__main__":
    main()
