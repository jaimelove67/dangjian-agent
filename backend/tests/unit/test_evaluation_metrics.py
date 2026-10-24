"""评测必须识别错误引用，重复片段不能虚增召回率。"""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "evaluation", Path(__file__).parents[1] / "evaluation" / "run_evaluation.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_document_metrics_deduplicate_chunks():
    metrics = evaluation.grade_retrieval(
        {"expected_docs": ["A", "B"]},
        [{"doc_id": "A"}, {"doc_id": "A"}, {"doc_id": "C"}, {"doc_id": "B"}],
        k=2,
    )
    assert metrics == {"recall_at_k": 0.5, "precision_at_k": 0.5, "mrr": 1.0}


def test_answer_with_wrong_source_cannot_count_as_traceable():
    grade = evaluation.grade_qa(
        {"should_refuse": False, "expected_answer_contains": ["规则"]},
        {
            "answer": "规则 [99]",
            "refused": False,
            "citations": [{"index": 1, "doc_id": "A", "chunk_id": "C", "content": "规则"}],
        },
    )
    assert grade["keyword_match"] is True
    assert grade["citation_traceable"] is False


def test_error_and_small_dataset_are_not_acceptance_success():
    report = evaluation.summarize([], [], [], [{"should_refuse": True}], [{"http_status": 503}])
    assert report["status"] == "failed"
    assert report["sample_size_meets_acceptance"] is False
    assert report["qa"]["refusal_accuracy"] is None
