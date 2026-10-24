"""检索模块单元测试"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.retrieval.base import RetrievalResult
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever


@pytest.fixture
def mock_db():
    """模拟数据库会话"""
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_model_service():
    """模拟模型服务"""
    service = MagicMock()
    service.embed = AsyncMock()
    service.rerank = AsyncMock()
    return service


class TestVectorRetriever:
    """向量检索器测试"""

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, mock_db):
        """测试空查询"""
        retriever = VectorRetriever(mock_db)
        results = await retriever.retrieve("")
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_with_results(self, mock_db, mock_model_service):
        """测试正常检索"""
        # 模拟向量化响应
        mock_embed_response = MagicMock()
        mock_embed_response.embeddings = [[0.1] * 1024]
        mock_model_service.embed.return_value = mock_embed_response

        # 模拟数据库查询结果
        mock_row = MagicMock()
        mock_row.chunk_id = "chunk-1"
        mock_row.content = "测试内容"
        mock_row.doc_id = "doc-1"
        mock_row.article = "第一条"
        mock_row.sequence = 1
        mock_row.title = "测试文档"
        mock_row.issuer = "测试单位"
        mock_row.doc_number = "测试字〔2024〕1号"
        mock_row.level = "school"
        mock_row.security_level = "public"
        mock_row.status = "effective"
        mock_row.effective_date = date(2024, 1, 1)
        mock_row.expiration_date = None
        mock_row.distance = 0.2

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        with patch("app.rag.retrieval.vector.get_model_service", return_value=mock_model_service):
            retriever = VectorRetriever(mock_db)
            results = await retriever.retrieve("测试查询", top_k=10, filters={"tenant_id": "t1"})

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-1"
        assert results[0].content == "测试内容"
        assert results[0].doc_status == "effective"
        assert results[0].effective_date == date(2024, 1, 1)
        assert results[0].expiration_date is None
        assert results[0].score == pytest.approx(0.8, abs=0.01)  # 1 - 0.2


class TestKeywordRetriever:
    """关键词检索器测试"""

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, mock_db):
        """测试空查询"""
        retriever = KeywordRetriever(mock_db)
        results = await retriever.retrieve("")
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_with_fts(self, mock_db):
        """测试全文检索"""
        mock_row = MagicMock()
        mock_row.chunk_id = "chunk-1"
        mock_row.content = "测试内容"
        mock_row.doc_id = "doc-1"
        mock_row.article = "第一条"
        mock_row.sequence = 1
        mock_row.title = "测试文档"
        mock_row.issuer = "测试单位"
        mock_row.doc_number = "测试字〔2024〕1号"
        mock_row.status = "effective"
        mock_row.effective_date = date(2024, 1, 1)
        mock_row.expiration_date = None
        mock_row.level = "school"
        mock_row.security_level = "public"
        mock_row.score = 0.75

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        retriever = KeywordRetriever(mock_db, use_fts=True, use_trigram=False)
        results = await retriever.retrieve("测试", top_k=10, filters={"tenant_id": "t1"})

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-1"
        assert results[0].score == 0.75
        assert results[0].doc_status == "effective"
        assert results[0].effective_date == date(2024, 1, 1)
        assert results[0].expiration_date is None


class TestHybridRetriever:
    """混合检索器测试"""

    @pytest.mark.asyncio
    async def test_rrf_fusion(self, mock_db):
        """测试 RRF 融合算法"""
        retriever = HybridRetriever(mock_db, use_reranker=False)

        # 创建测试数据
        vector_results = [
            RetrievalResult("chunk-1", "内容1", 0.9, "doc-1"),
            RetrievalResult("chunk-2", "内容2", 0.8, "doc-1"),
            RetrievalResult("chunk-3", "内容3", 0.7, "doc-1"),
        ]

        keyword_results = [
            RetrievalResult("chunk-2", "内容2", 0.85, "doc-1"),
            RetrievalResult("chunk-1", "内容1", 0.75, "doc-1"),
            RetrievalResult("chunk-4", "内容4", 0.65, "doc-1"),
        ]

        # 执行融合
        fused = retriever._reciprocal_rank_fusion(vector_results, keyword_results, top_k=10)

        # chunk-1 和 chunk-2 应该排在前面（两个列表都有）
        assert len(fused) >= 2
        chunk_ids = [r.chunk_id for r in fused[:2]]
        assert "chunk-1" in chunk_ids
        assert "chunk-2" in chunk_ids

    @pytest.mark.asyncio
    async def test_retrieve_with_reranker(self, mock_db, mock_model_service):
        """测试带重排序的检索"""
        # 模拟向量检索结果
        vector_result = RetrievalResult(
            "chunk-1", "测试内容", 0.8, "doc-1", metadata={"security_level": "public"}
        )

        # 模拟重排响应
        mock_rerank_result = MagicMock()
        mock_rerank_result.index = 0
        mock_rerank_result.relevance_score = 0.95

        mock_rerank_response = MagicMock()
        mock_rerank_response.results = [mock_rerank_result]
        mock_model_service.rerank.return_value = mock_rerank_response

        with patch("app.rag.retrieval.hybrid.get_model_service", return_value=mock_model_service):
            with patch.object(VectorRetriever, "retrieve", return_value=[vector_result]):
                with patch.object(KeywordRetriever, "retrieve", return_value=[]):
                    retriever = HybridRetriever(mock_db, use_reranker=True)
                    results = await retriever.retrieve("测试查询", top_k=5)

        assert len(results) >= 1
        # 重排后的分数应该被更新
        assert results[0].metadata.get("rerank_score") == 0.95
