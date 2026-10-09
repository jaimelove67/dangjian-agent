"""知识文档元数据校验测试（框架文档 5.2.1 / 5.2.2）"""
import pytest

from app.rules.document_metadata import (
    MetadataValidationError,
    validate_document_metadata,
)


def _valid(**overrides):
    base = {
        "doc_id": "doc-001",
        "file_name": "d.pdf",
        "title": "发展党员工作细则",
        "issuer": "中共中央办公厅",
        "level": "school",
        "visibility": "school",
        "security_level": "public",
        "effective_date": "2014-06-10",
        "expiration_date": None,
        "status": "effective",
        "tags": ["发展党员"],
    }
    base.update(overrides)
    return base


class TestValidCases:
    def test_valid_is_embeddable(self):
        assert validate_document_metadata(_valid()).embedding_allowed is True

    def test_classified_not_embeddable(self):
        result = validate_document_metadata(_valid(security_level="classified"))
        assert result.embedding_allowed is False

    def test_expiration_after_effective_ok(self):
        result = validate_document_metadata(_valid(expiration_date="2020-01-01"))
        assert result.embedding_allowed is True


class TestRequiredFields:
    @pytest.mark.parametrize(
        "field",
        [
            "doc_id",
            "file_name",
            "title",
            "issuer",
            "level",
            "visibility",
            "security_level",
            "effective_date",
            "status",
        ],
    )
    def test_missing_required_rejected(self, field):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(_valid(**{field: ""}))

    def test_empty_tags_rejected(self):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(_valid(tags=[]))


class TestRules:
    def test_central_must_be_public(self):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(_valid(level="central", security_level="internal"))

    def test_central_public_ok(self):
        result = validate_document_metadata(
            _valid(level="central", security_level="public")
        )
        assert result.embedding_allowed is True

    @pytest.mark.parametrize(
        "override",
        [
            {"level": "galaxy"},
            {"visibility": "galaxy"},
            {"security_level": "topsecret"},
            {"status": "archived"},
        ],
    )
    def test_invalid_enum_rejected(self, override):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(_valid(**override))

    def test_expiration_before_effective_rejected(self):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(
                _valid(effective_date="2020-01-01", expiration_date="2019-01-01")
            )

    def test_bad_date_format_rejected(self):
        with pytest.raises(MetadataValidationError):
            validate_document_metadata(_valid(effective_date="not-a-date"))

    def test_multiple_errors_collected(self):
        with pytest.raises(MetadataValidationError) as exc_info:
            validate_document_metadata(_valid(doc_id="", level="galaxy"))
        assert len(exc_info.value.errors) >= 2
