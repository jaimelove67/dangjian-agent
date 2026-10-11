"""学习纪要不能补写共识，原文位置、重复人员和审核边界可核验。"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.study import ActivityUpdate, PlanCreate
from app.services.meeting_service import (
    apply_review,
    extract_minutes,
    minutes_missing,
    reset_review,
    validate_minutes,
)


def test_extraction_preserves_exact_offsets_with_crlf_and_whitespace():
    transcript = "  原始记录\r\n 学习要点：认真研读原始制度。\r\n讨论共识:由组织人员研究确定。\n工作要求：落实已明确工作。\n"
    minutes = extract_minutes(transcript)
    validate_minutes(transcript, minutes)
    assert all(minutes[key] for key in ("learning_points", "consensus", "requirements"))
    for notes in minutes.values():
        for note in notes:
            assert transcript[note["start"] : note["end"]] == note["quote"] == note["text"]
    body = ActivityUpdate(expected_revision=1, reason="校对", transcript=transcript)
    assert body.transcript == transcript


def test_ambiguous_transcript_does_not_invent_decisions_or_requirements():
    transcript = "学习要点：学习实际文件。\n有人认为可以考虑调整安排，尚未形成决定。"
    minutes = extract_minutes(transcript)
    assert minutes["consensus"] == minutes["requirements"] == []
    record = SimpleNamespace(
        minutes=minutes, transcript=transcript, participants=[], host="", held_on=None
    )
    assert "讨论共识待补" in minutes_missing(record)
    assert "工作要求待补" in minutes_missing(record)


@pytest.mark.parametrize("transcript", ["学习要点：" + "原" * 5001, "学习要点：原文。\n" * 61])
def test_oversized_minutes_require_manual_selection_instead_of_uneditable_output(transcript):
    with pytest.raises(HTTPException) as exc:
        extract_minutes(transcript)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("start,end,quote", [(0, 2, "伪造"), (4, 2, "原文"), (0, 900, "原文")])
def test_invalid_or_stale_evidence_is_rejected(start, end, quote):
    with pytest.raises(HTTPException) as exc:
        validate_minutes("原文内容", {"consensus": [{"start": start, "end": end, "quote": quote}]})
    assert exc.value.status_code == 422


def test_review_requires_another_person_and_modification_resets_approval():
    record = SimpleNamespace(
        review_status="pending",
        submitted_by="author",
        reviewed_by=None,
        reviewed_at=None,
        review_comment="",
    )
    with pytest.raises(HTTPException) as exc:
        apply_review(record, "author", "approved", "通过")
    assert exc.value.status_code == 403
    apply_review(record, "reviewer", "approved", "核对原文后通过")
    assert record.reviewed_by == "reviewer" and record.reviewed_at
    reset_review(record)
    assert record.review_status == "draft" and record.reviewed_by is None
    with pytest.raises(HTTPException):
        apply_review(record, "reviewer", "approved", "越过送审")


@pytest.mark.parametrize(
    "extra",
    [
        {"held_on": (date.today() + timedelta(days=1)).isoformat()},
        {
            "participants": [
                {"participant_id": "a", "name": "甲", "attended": True},
                {"participant_id": "a", "name": "乙", "attended": False},
            ]
        },
        {"participants": [{"participant_id": "a", "name": "甲", "attended": "false"}]},
        {"review_status": "approved"},
        {"tenant_id": "other"},
    ],
)
def test_invalid_or_forged_activity_input_is_rejected(extra):
    with pytest.raises(ValidationError):
        ActivityUpdate(expected_revision=1, reason="测试", **extra)


def test_plan_dates_cannot_silently_move_to_another_year():
    with pytest.raises(ValidationError):
        PlanCreate(
            org_unit_id="department",
            year=2026,
            title="计划",
            priorities=["学习重点"],
            responsible="负责人",
            reason="登记",
            items=[{"topic": "主题", "scheduled_on": "2027-01-01", "responsible": "负责人"}],
        )
