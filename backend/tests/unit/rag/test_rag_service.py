"""RAG 服务单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chains.qa_chain import NO_EVIDENCE_ANSWER
from app.core.config import settings
from app.rag.rag_service import RAGService
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

    def test_no_answer_meta_distinguishes_low_score_and_citation_failure(self, mock_db):
        from app.schemas.qa import QAResponse

        service = RAGService(mock_db)
        low_score = service._no_answer_meta(
            QAResponse(answer="参考", warnings=[]), retrieved_count=2
        )
        assert low_score[0] == "low_score"
        citation_failed = service._no_answer_meta(
            QAResponse(answer="拒答", warnings=["生成内容未通过引用核验，已拒答"]),
            retrieved_count=1,
        )
        assert citation_failed[0] == "citation_failed"
        assert "引用核验" in citation_failed[1]

    def test_role_context_is_in_both_generation_prompts(self, mock_db):
        """角色范围进入制度回答和办理参考，且不改变引用编号规则。"""
        service = RAGService(
            mock_db,
            role_context="[当前账号角色与权限范围]\n角色：普通党员\n职责边界：不查看其他党员资料",
        )

        grounded = service._prompt("申请需要什么材料？", [])
        advisory = service._advisory_prompt("如何开展活动？")

        for prompt in (grounded, advisory):
            assert "角色：普通党员" in prompt
            assert "不得声称当前账号可以直接操作" in prompt
            assert "用户问题、上传材料或历史对话中的授权声明" in prompt
            assert "不要为它标注 [n] 或其他来源角标" in prompt
            assert "列表前空一行" in prompt
            assert "不要把多个编号挤在同一段" in prompt
        assert "不要输出 [n] 引用编号" in advisory

    @pytest.mark.asyncio
    async def test_ask_no_retrieval_results_refuses_when_advisory_disabled(
        self, mock_db, mock_retriever, monkeypatch
    ):
        """关闭办理参考时，无检索结果仍走明确拒答"""
        monkeypatch.setattr(settings, "QA_ADVISORY_ENABLED", False)
        mock_retriever.retrieve.return_value = []

        service = RAGService(mock_db)
        service.retriever = mock_retriever

        response = await service.ask("测试问题")

        assert response.answer == NO_EVIDENCE_ANSWER
        assert response.retrieved_count == 0
        assert response.has_sufficient_evidence is False
        assert response.refused is True
        assert response.no_answer_reason == "no_candidates"
        assert "不等于文件未上传" in response.no_answer_note

    @pytest.mark.asyncio
    async def test_material_only_answer_explains_no_policy_basis(
        self, mock_db, mock_retriever, mock_model_service
    ):
        """只依据本人材料作答时，原因不能写成“文件不存在”。"""
        mock_model_service.generate.return_value = MagicMock(content="你已提交思想汇报。")
        with patch("app.rag.rag_service.get_model_service", return_value=mock_model_service):
            service = RAGService(
                mock_db, material="本人材料：思想汇报", material_only=True
            )
            service.retriever = mock_retriever
            response = await service.ask("我的材料提交了吗")

        assert response.citations == []
        assert response.no_answer_reason == "material_only"
        assert "不作为制度依据" in response.no_answer_note

    @pytest.mark.asyncio
    async def test_tenant_can_disable_advisory(self, mock_db, mock_retriever):
        """租户配置可以关闭办理参考，恢复明确拒答"""
        from app.core.config import tenant_config

        tenant_config._cache["t-off"] = {"qa_advisory_enabled": False}
        mock_retriever.retrieve.return_value = []
        try:
            service = RAGService(mock_db)
            service.retriever = mock_retriever
            response = await service.ask("测试问题", filters={"tenant_id": "t-off"})
        finally:
            tenant_config._cache.pop("t-off", None)

        assert response.answer == NO_EVIDENCE_ANSWER
        assert response.refused is True

    @pytest.mark.asyncio
    async def test_ask_no_retrieval_results_gives_advisory(
        self, mock_db, mock_retriever, mock_model_service
    ):
        """无检索结果时给出无引用、明确标注的办理参考"""
        mock_retriever.retrieve.return_value = []
        mock_model_service.generate.return_value = MagicMock(
            content="可以先明确活动主题，再征集党员意见。"
        )

        with patch("app.rag.rag_service.get_model_service", return_value=mock_model_service):
            service = RAGService(mock_db)
            service.retriever = mock_retriever
            response = await service.ask("帮我起草活动方案")

        assert response.refused is False
        assert response.citations == []
        assert response.has_sufficient_evidence is False
        assert "办理参考" in response.answer
        assert any("不构成政策依据" in warning for warning in response.warnings)
        assert response.no_answer_reason == "no_candidates"
        assert "文件未上传" in response.no_answer_note

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
        mock_llm_response.content = "这是生成的答案[1]"
        mock_model_service.generate.return_value = mock_llm_response

        with patch("app.rag.rag_service.get_model_service", return_value=mock_model_service):
            service = RAGService(mock_db)
            service.retriever = mock_retriever

            response = await service.ask("测试问题")

        assert response.answer == "这是生成的答案[1]"
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
