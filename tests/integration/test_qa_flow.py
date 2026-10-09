"""集成测试：完整问答流程

测试从文档入库到问答的完整流程。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.rag.enhanced_rag_service import EnhancedRAGService
from app.rag.retrieval.base import RetrievalResult


@pytest.fixture
def mock_db():
    """模拟数据库会话"""
    return MagicMock()


@pytest.fixture
def mock_model_service():
    """模拟模型服务"""
    service = MagicMock()
    service.generate = AsyncMock()
    service.generate_stream = AsyncMock()
    return service


@pytest.fixture
def mock_retriever():
    """模拟检索器"""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock()
    return retriever


class TestEnhancedRAGIntegration:
    """完整RAG流程集成测试"""

    @pytest.mark.asyncio
    async def test_complete_qa_flow(self, mock_db, mock_retriever, mock_model_service):
        """测试完整问答流程"""
        # 模拟检索结果
        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                content="入党积极分子培养教育时间一般不少于一年。",
                score=0.85,
                doc_id="doc-1",
                article="第十四条",
                sequence=1,
                metadata={
                    "title": "中国共产党发展党员工作细则",
                    "issuer": "中共中央组织部",
                    "doc_number": "中组发〔2014〕3号",
                    "level": "central",
                    "security_level": "public",
                    "retrieval_method": "hybrid",
                },
            )
        ]
        mock_retriever.retrieve.return_value = retrieval_results

        # 模拟LLM响应
        mock_llm_response = MagicMock()
        mock_llm_response.content = """根据《中国共产党发展党员工作细则》（中组发〔2014〕3号）第十四条规定，入党积极分子培养教育时间一般不少于一年。

**具体要求**：
1. 培养期不少于一年
2. 党组织要指定培养联系人
3. 要进行经常性的培养教育

这是发展党员的重要程序性要求，确保入党积极分子充分了解党的性质、宗旨和纲领。"""
        mock_model_service.generate.return_value = mock_llm_response

        with patch("app.rag.enhanced_rag_service.get_model_service", return_value=mock_model_service):
            service = EnhancedRAGService(mock_db)
            service.retriever = mock_retriever

            # 执行问答
            response = await service.ask("入党积极分子培养期是多久？")

            # 验证结果
            assert "一年" in response.answer
            assert len(response.citations) == 1
            assert response.citations[0].title == "中国共产党发展党员工作细则"
            assert response.citations[0].article == "第十四条"
            assert response.retrieved_count == 1
            assert response.used_count == 1
            assert response.has_sufficient_evidence is True

    @pytest.mark.asyncio
    async def test_refusal_when_no_evidence(self, mock_db, mock_retriever):
        """测试无依据时的拒答"""
        # 模拟无检索结果
        mock_retriever.retrieve.return_value = []

        service = EnhancedRAGService(mock_db)
        service.retriever = mock_retriever

        response = await service.ask("明天天气怎么样？")

        # 验证拒答
        assert "无法回答" in response.answer or "未找到" in response.answer
        assert len(response.citations) == 0
        assert response.has_sufficient_evidence is False

    @pytest.mark.asyncio
    async def test_stream_qa_flow(self, mock_db, mock_retriever, mock_model_service):
        """测试流式问答"""
        # 模拟检索结果
        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                content="测试内容",
                score=0.85,
                doc_id="doc-1",
                metadata={
                    "title": "测试文档",
                    "issuer": "测试单位",
                    "retrieval_method": "hybrid",
                },
            )
        ]
        mock_retriever.retrieve.return_value = retrieval_results

        # 模拟流式响应
        async def mock_stream():
            for chunk in ["这是", "流式", "生成", "的答案"]:
                yield chunk

        mock_model_service.generate_stream = mock_stream

        with patch("app.rag.enhanced_rag_service.get_model_service", return_value=mock_model_service):
            service = EnhancedRAGService(mock_db)
            service.retriever = mock_retriever

            # 执行流式问答
            chunks = []
            async for chunk in service.ask_stream("测试问题"):
                chunks.append(chunk)

            # 验证流式输出
            assert len(chunks) > 0
            full_answer = "".join(chunks)
            assert len(full_answer) > 0

    @pytest.mark.asyncio
    async def test_low_relevance_filtering(self, mock_db, mock_retriever):
        """测试低相关度过滤"""
        # 模拟低相关度检索结果
        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                content="不相关的内容",
                score=0.15,  # 低于默认阈值0.3
                doc_id="doc-1",
                metadata={"title": "不相关文档"},
            )
        ]
        mock_retriever.retrieve.return_value = retrieval_results

        service = EnhancedRAGService(mock_db, min_relevance_score=0.3)
        service.retriever = mock_retriever

        response = await service.ask("测试问题")

        # 验证被拒答
        assert "相关度较低" in response.answer or "无法回答" in response.answer
        assert response.has_sufficient_evidence is False
