"""知识文件发布信息只读出参：公开审核、非公开直接发布。"""

from datetime import date, datetime
from types import SimpleNamespace

from app.schemas.knowledge import DocumentResponse


def document(**overrides):
    values = {
        "id": "row-1",
        "doc_id": "DOC-1",
        "file_name": "制度.pdf",
        "title": "合成制度",
        "issuer": "合成学校",
        "doc_number": None,
        "level": "school",
        "visibility": "school",
        "security_level": "internal",
        "status": "effective",
        "authority": "school_policy",
        "validity": "effective",
        "review_status": "published",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": None,
        "doc_metadata": {"uploaded_by": "user-uploader"},
        "field_levels": {},
        "maintained_at": None,
        "next_review_at": None,
        "effective_date": date(2026, 1, 1),
        "expiration_date": None,
        "tags": [],
        "summary": None,
        "created_at": datetime(2026, 1, 2, 8, 0, 0),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_non_public_document_records_direct_publisher_and_time():
    data = DocumentResponse.from_document(
        document(), user_names={"user-uploader": "张老师"}
    )
    assert data.publish_mode == "direct"
    assert data.uploaded_by_name == "张老师"
    assert data.published_at == datetime(2026, 1, 2, 8, 0, 0)


def test_public_document_waits_for_review_before_it_has_a_publish_time():
    data = DocumentResponse.from_document(
        document(visibility="public", review_status="pending"),
        user_names={"user-uploader": "张老师"},
    )
    assert data.publish_mode == "review"
    assert data.uploaded_by_name == "张老师"
    assert data.reviewed_by_name is None
    assert data.published_at is None


def test_public_document_records_reviewer_and_review_time():
    reviewed_at = datetime(2026, 2, 3, 9, 30, 0)
    data = DocumentResponse.from_document(
        document(
            visibility="public",
            review_status="published",
            reviewed_by="user-reviewer",
            reviewed_at=reviewed_at,
            review_note="同意发布",
        ),
        user_names={"user-uploader": "张老师", "user-reviewer": "李老师"},
    )
    assert data.publish_mode == "review"
    assert data.reviewed_by_name == "李老师"
    assert data.review_note == "同意发布"
    assert data.published_at == reviewed_at
