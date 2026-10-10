"""模型服务单元测试"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.base import DataLevel, EmbeddingResponse, ModelResponse, ModelType, TaskType
from app.llm.gateway import GatewayError
from app.llm.router import RouterError
from app.llm.service import ModelService


@pytest.fixture
def mock_router():
    """模拟路由器"""
    router = MagicMock()
    router.registry = MagicMock()
    router.registry.health_check_all = AsyncMock()
    return router


@pytest.fixture
def model_service(mock_router, monkeypatch):
    """创建模型服务实例"""
    # 替换全局路由器
    monkeypatch.setattr("app.llm.service.get_model_router", lambda: mock_router)
    return ModelService()


@pytest.mark.asyncio
async def test_generate_success(model_service, mock_router):
    """测试生成文本成功"""
    # 准备mock
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ModelResponse(
        content="这是生成的内容",
        model_id="test-model",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
    )
    mock_router.get_model.return_value = mock_provider

    # 调用
    response = await model_service.generate(
        prompt="测试提示词",
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
    )

    # 验证
    assert response.content == "这是生成的内容"
    assert response.model_id == "test-model"
    mock_router.get_model.assert_called_once_with(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_type=ModelType.LLM,
        context=None,
    )
    mock_provider.generate.assert_called_once()


@pytest.mark.asyncio
async def test_generate_gateway_blocked(model_service, mock_router):
    """测试生成被闸门拦截"""
    # 准备mock - 路由器抛出闸门错误
    mock_router.get_model.side_effect = GatewayError("敏感数据禁止使用外部模型")

    # 调用并验证异常
    with pytest.raises(GatewayError) as exc_info:
        await model_service.generate(
            prompt="测试提示词",
            data_level=DataLevel.SENSITIVE,
            task_type=TaskType.QA,
        )

    assert "敏感数据禁止使用外部模型" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_router_error(model_service, mock_router):
    """测试路由错误"""
    # 准备mock
    mock_router.get_model.side_effect = RouterError("没有可用模型")

    # 调用并验证异常
    with pytest.raises(RouterError) as exc_info:
        await model_service.generate(
            prompt="测试提示词",
            data_level=DataLevel.INTERNAL,
            task_type=TaskType.SUMMARIZE,
        )

    assert "没有可用模型" in str(exc_info.value)


@pytest.mark.asyncio
async def test_embed_success(model_service, mock_router):
    """测试向量化成功"""
    # 准备mock
    mock_provider = AsyncMock()
    mock_provider.embed.return_value = EmbeddingResponse(
        embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        model_id="test-embedding",
        dimensions=3,
    )
    mock_router.get_model.return_value = mock_provider

    # 调用
    response = await model_service.embed(
        texts=["文本1", "文本2"],
        data_level=DataLevel.PUBLIC,
    )

    # 验证
    assert len(response.embeddings) == 2
    assert response.dimensions == 3
    assert response.model_id == "test-embedding"
    mock_router.get_model.assert_called_once_with(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_type=ModelType.EMBEDDING,
        context=None,
    )


@pytest.mark.asyncio
async def test_embed_with_context(model_service, mock_router):
    """测试带上下文的向量化（用于审计）"""
    # 准备mock
    mock_provider = AsyncMock()
    mock_provider.embed.return_value = EmbeddingResponse(
        embeddings=[[0.1, 0.2]],
        model_id="test-embedding",
        dimensions=2,
    )
    mock_router.get_model.return_value = mock_provider

    # 调用
    context = {"user_id": "test-user", "action": "knowledge_ingest"}
    await model_service.embed(
        texts=["文档内容"],
        data_level=DataLevel.INTERNAL,
        context=context,
    )

    # 验证上下文传递
    mock_router.get_model.assert_called_once()
    call_args = mock_router.get_model.call_args
    assert call_args.kwargs["context"] == context


@pytest.mark.asyncio
async def test_health_check(model_service, mock_router):
    """测试健康检查"""
    # 准备mock
    mock_router.registry.health_check_all.return_value = {
        "model-1": True,
        "model-2": False,
        "model-3": True,
    }

    # 调用
    results = await model_service.health_check()

    # 验证
    assert results == {
        "model-1": True,
        "model-2": False,
        "model-3": True,
    }
    mock_router.registry.health_check_all.assert_called_once()


@pytest.mark.asyncio
async def test_generate_with_extra_params(model_service, mock_router):
    """测试传递额外参数给模型"""
    # 准备mock
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ModelResponse(
        content="响应",
        model_id="test-model",
    )
    mock_router.get_model.return_value = mock_provider

    # 调用带额外参数
    await model_service.generate(
        prompt="提示词",
        data_level=DataLevel.PUBLIC,
        temperature=0.9,
        max_tokens=2000,
    )

    # 验证额外参数传递
    mock_provider.generate.assert_called_once()
    call_kwargs = mock_provider.generate.call_args.kwargs
    assert call_kwargs["temperature"] == 0.9
    assert call_kwargs["max_tokens"] == 2000
