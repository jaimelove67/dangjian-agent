"""知识库服务完善测试"""
import pytest

from app.services.knowledge_service import DocumentConflictError, DocumentNotFoundError


class TestDocumentService:
    """测试知识库服务的边界情况"""

    def test_document_not_found_error(self):
        """测试文档不存在异常"""
        exc = DocumentNotFoundError("doc-001")
        assert "doc-001" in str(exc)

    def test_document_conflict_error(self):
        """测试文档标识冲突异常"""
        exc = DocumentConflictError("文档标识已存在: doc-001")
        assert "doc-001" in str(exc)
