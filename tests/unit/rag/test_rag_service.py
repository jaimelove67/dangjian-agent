"""RAG 服务单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.rag.rag_service import RAGService, RAGResponse, Citation
from app.rag.retrieval.base import RetrievalResult
from app.llm.base import DataLevel


@pytest.fixture
def mock_db():
    """模拟数据库会话"""
    return MagicMock()


@pytest.fixture
def mock_model_service():
    """模拟模型服务"""
    service = MagicMock()
    service.generate = AsyncMock()
    return service


@pytest.fixture
def mock_retriever():
    """模拟检索器"""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock()
    return retriever


class TestRAGService:
    """RAG 服务测试"""

    @pytest.mark.asyncio
    async def test_ask_empty_question(self, mock_db):
        """测试空问题"""
        service = RAGService(mock_db)
        response = await service.ask("")

        assert "请输入您的问题" in response.answer
        assert response.retrieved_count == 0
        assert response.has_sufficient_evidence is False

    @pytest.mark.asyncio
    async def test_ask_no_retrieval_results(self, mock_db, mock_retriever):
        """测试无检索结果"""
        mock_retriever.retrieve.return_value = []

        service = RAGService(mock_db)
        service.retriever = mock_retriever

        response = await service.ask("测试问题")

        assert "没有找到相关信息" in response.answer
        assert response.retrieved_count == 0
        assert response.has_sufficient_evidence is False

    @pytest.mark.asyncio
    async def test_ask_with_results(self, mock_db, mock_retriever, mock_model_service):
        """测试正常问答流程"""
        # 模拟检索结果
        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                content="这是测试内容",
                score=0.85,
                doc_id="doc-1",
                article="第一条",
                sequence=1,
                metadata={
                    "title": "测试文档",
                    "issuer": "测试单位",
                    "doc_number": "测试字〔2024〕1号",
                    "level": "school",
                    "security_level": "public",
                },
            )
        ]
        mock_retriever.retrieve.return_value = retrieval_results

        # 模拟 LLM 响应
        mock_llm_response = MagicMock()
        mock_llm_response.content = "这是生成的答案"
        mock_model_service.generate.return_value = mock_llm_response

        with patch("app.rag.rag_service.get_model_service", return_value=mock_model_service):
            service = RAGService(mock_db)
            service.retriever = mock_retriever

            response = await service.ask("测试问题")

        assert response.answer == "这是生成的答案"
        assert response.retrieved_count == 1
        assert response.used_count == 1
        assert len(response.citations) == 1
        assert response.citations[0].title == "测试文档"
        assert response.has_sufficient_evidence is True

    @pytest.mark.asyncio
    async def test_build_prompt(self, mock_db):
        """测试提示词构建"""
        service = RAGService(mock_db)

        results = [
            RetrievalResult(
                chunk_id="chunk-1",
                content="测试内容1",
                score=0.9,
                doc_id="doc-1",
                article="第一条",
                metadata={
                    "title": "文档1",
                    "issuer": "单位1",
                    "doc_number": "文号1",
                },
            ),
            RetrievalResult(
                chunk_id="chunk-2",
                content="测试内容2",
                score=0.8,
                doc_id="doc-2",
                metadata={
                    "title": "文档2",
                    "issuer": "单位2",
                },
            ),
        ]

        prompt = service._build_prompt("测试问题", results)

        assert "测试问题" in prompt
        assert "文档1" in prompt
        assert "文档2" in prompt
        assert "测试内容1" in prompt
        assert "测试内容2" in prompt
        assert "第一条" in prompt

    def test_check_evidence_sufficiency(self, mock_db):
        """测试依据充分性判断"""
        service = RAGService(mock_db)

        # 有高相关度结果，答案不是拒答
        results = [
            RetrievalResult("chunk-1", "内容", 0.8, "doc-1"),
        ]
        assert service._check_evidence_sufficiency("这是答案", results) is True

        # 相关度低
        low_score_results = [
            RetrievalResult("chunk-1", "内容", 0.3, "doc-1"),
        ]
        assert service._check_evidence_sufficiency("这是答案", low_score_results) is False

        # 答案是拒答
        assert service._check_evidence_sufficiency("无法回答这个问题", results) is False

        # 没有结果
        assert service._check_evidence_sufficiency("答案", []) is False
