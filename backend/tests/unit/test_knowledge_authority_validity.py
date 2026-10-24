"""知识条目权威来源 / 效力状态 / 审核发布（T-DATA-05、T-KB-12）纯逻辑测试。"""

import pytest

from app.core.constants import (
    DocumentAuthority,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentValidity,
    is_authoritative,
    is_in_force,
)
from app.models.knowledge import KnowledgeDoc
from app.rag.verifier import RetrievedChunk, has_authoritative_basis
from app.services.knowledge_service import (
    default_authority,
    reopen_review,
    sync_validity_status,
)


class TestAuthorityHelpers:
    @pytest.mark.parametrize(
        "authority",
        [
            "party_constitution",
            "party_regulation",
            "superior_document",
            "school_policy",
            None,
        ],
    )
    def test_non_reference_is_authoritative(self, authority):
        assert is_authoritative(authority) is True

    def test_reference_is_not_authoritative(self):
        assert is_authoritative(DocumentAuthority.REFERENCE.value) is False


class TestValidityHelpers:
    def test_only_effective_is_in_force(self):
        assert is_in_force(DocumentValidity.EFFECTIVE.value) is True

    @pytest.mark.parametrize("validity", ["pending", "superseded", "repealed"])
    def test_other_validity_is_not_in_force(self, validity):
        assert is_in_force(validity) is False

    def test_missing_validity_is_treated_as_in_force(self):
        # 历史数据与未标注来源的调用方按现行有效处理，避免整体降级存量制度。
        assert is_in_force(None) is True


class TestDefaultAuthority:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            ("central", "superior_document"),
            ("provincial", "superior_document"),
            ("school", "school_policy"),
            ("department", "school_policy"),
        ],
    )
    def test_default_by_level(self, level, expected):
        assert default_authority(level) == expected

    def test_unknown_level_falls_back_to_reference(self):
        assert default_authority("galaxy") == DocumentAuthority.REFERENCE.value


class TestSyncValidityStatus:
    def test_repealed_forces_abolished(self):
        assert sync_validity_status("effective", "repealed") == (
            DocumentStatus.ABOLISHED.value,
            DocumentValidity.REPEALED.value,
        )

    def test_abolished_forces_repealed(self):
        assert sync_validity_status("abolished", "effective") == (
            DocumentStatus.ABOLISHED.value,
            DocumentValidity.REPEALED.value,
        )

    def test_other_states_are_independent(self):
        assert sync_validity_status("expired", "superseded") == ("expired", "superseded")
        assert sync_validity_status("effective", "pending") == ("effective", "pending")


class TestReopenReview:
    def _document(self, **overrides):
        base = {
            "doc_id": "d1",
            "file_name": "d.txt",
            "title": "制度",
            "issuer": "合成单位",
            "level": "school",
            "visibility": "public",
            "security_level": "public",
            "review_status": DocumentReviewStatus.PUBLISHED.value,
            "reviewed_by": "u1",
            "review_note": "已核对",
        }
        base.update(overrides)
        return KnowledgeDoc(**base)

    def test_published_public_content_reopens(self):
        document = self._document()
        assert reopen_review(document) is True
        assert document.review_status == DocumentReviewStatus.PENDING.value
        assert document.reviewed_by is None and document.reviewed_at is None
        assert document.review_note is None

    def test_non_public_content_is_untouched(self):
        document = self._document(visibility="school")
        assert reopen_review(document) is False
        assert document.review_status == DocumentReviewStatus.PUBLISHED.value

    def test_already_pending_content_is_untouched(self):
        document = self._document(review_status=DocumentReviewStatus.PENDING.value)
        assert reopen_review(document) is False


class TestAuthoritativeBasis:
    def _chunk(self, **overrides):
        base = {
            "index": 1,
            "doc_id": "d1",
            "doc_name": "文件1",
            "content": "第一条 培养期一般不少于一年。",
        }
        base.update(overrides)
        return RetrievedChunk(**base)

    def test_authoritative_and_in_force_basis(self):
        assert has_authoritative_basis([self._chunk(authority="party_regulation")]) is True

    def test_reference_only_has_no_basis(self):
        assert has_authoritative_basis([self._chunk(authority="reference")]) is False

    def test_out_of_force_only_has_no_basis(self):
        chunks = [
            self._chunk(validity="repealed"),
            self._chunk(index=2, validity="superseded"),
        ]
        assert has_authoritative_basis(chunks) is False

    def test_mixed_has_basis(self):
        chunks = [
            self._chunk(authority="reference"),
            self._chunk(index=2, authority="school_policy"),
        ]
        assert has_authoritative_basis(chunks) is True

    def test_empty_has_no_basis(self):
        assert has_authoritative_basis([]) is False
