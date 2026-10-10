"""测试模型路由器"""

import pytest

from app.llm.base import (
    BaseModelProvider,
    DataLevel,
    DeploymentType,
    EmbeddingResponse,
    ModelConfig,
    ModelResponse,
    ModelType,
    TaskType,
)
from app.llm.gateway import GatewayError
from app.llm.registry import ModelRegistry
from app.llm.router import ModelRouter, RouterError


class MockProvider(BaseModelProvider):
    """模拟模型提供者"""

    async def generate(self, prompt: str, **kwargs) -> ModelResponse:
        return ModelResponse(
            content="test response",
            model_id=self.config.model_id,
        )

    async def embed(self, texts: list[str], **kwargs) -> EmbeddingResponse:
        return EmbeddingResponse(
            embeddings=[[0.1] * 768 for _ in texts],
            model_id=self.config.model_id,
            dimensions=768,
        )

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def setup_models():
    """设置测试模型"""
    registry = ModelRegistry()

    # 本地 LLM
    local_llm_config = ModelConfig(
        model_id="local-llm",
        model_name="Local LLM",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="local",
    )
    registry.register(MockProvider(local_llm_config))

    # 外部 LLM
    external_llm_config = ModelConfig(
        model_id="external-llm",
        model_name="External LLM",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="qwen",
    )
    registry.register(MockProvider(external_llm_config))

    # 本地 Embedding
    local_embed_config = ModelConfig(
        model_id="local-embedding",
        model_name="Local Embedding",
        model_type=ModelType.EMBEDDING,
        deployment_type=DeploymentType.LOCAL,
        provider="sentence-transformers",
    )
    registry.register(MockProvider(local_embed_config))

    return registry


def test_router_sensitive_data_uses_local(setup_models):
    """测试敏感数据使用本地模型"""
    router = ModelRouter()
    router.registry = setup_models

    provider = router.get_model(
        data_level=DataLevel.SENSITIVE, task_type=TaskType.QA, model_type=ModelType.LLM
    )

    assert provider.config.model_id == "local-llm"
    assert provider.config.deployment_type == DeploymentType.LOCAL


def test_router_sensitive_data_no_local_fails(setup_models):
    """测试敏感数据无本地模型时失败"""
    router = ModelRouter()
    router.registry = setup_models

    # 注销本地 LLM
    setup_models.unregister("local-llm")

    with pytest.raises(RouterError, match="No available model"):
        router.get_model(
            data_level=DataLevel.SENSITIVE, task_type=TaskType.QA, model_type=ModelType.LLM
        )


def test_router_internal_data_prefers_local(setup_models):
    """测试内部数据优先本地模型"""
    router = ModelRouter()
    router.registry = setup_models

    provider = router.get_model(
        data_level=DataLevel.INTERNAL, task_type=TaskType.QA, model_type=ModelType.LLM
    )

    # 应该选择本地模型
    assert provider.config.model_id == "local-llm"


def test_router_public_data_prefers_external(setup_models):
    """测试公开数据优先外部模型（成本优化）"""
    router = ModelRouter()
    router.registry = setup_models

    provider = router.get_model(
        data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_type=ModelType.LLM
    )

    # 应该选择外部模型以降低成本
    assert provider.config.model_id == "external-llm"


def test_router_custom_route(setup_models):
    """测试自定义路由规则"""
    router = ModelRouter()
    router.registry = setup_models

    # 注册自定义规则：公开数据的QA任务使用本地模型
    router.register_route(data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_id="local-llm")

    provider = router.get_model(
        data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_type=ModelType.LLM
    )

    # 应该按自定义规则选择本地模型
    assert provider.config.model_id == "local-llm"


def test_router_gateway_blocks_sensitive_external(setup_models):
    """测试闸门拦截敏感数据使用外部模型"""
    router = ModelRouter()
    router.registry = setup_models

    # 强制指定外部模型
    router.register_route(
        data_level=DataLevel.SENSITIVE, task_type=TaskType.QA, model_id="external-llm"
    )

    # 应被闸门拦截
    with pytest.raises(GatewayError, match="敏感数据禁止使用外部模型"):
        router.get_model(
            data_level=DataLevel.SENSITIVE, task_type=TaskType.QA, model_type=ModelType.LLM
        )


def test_router_embedding_model(setup_models):
    """测试向量化模型路由"""
    router = ModelRouter()
    router.registry = setup_models

    provider = router.get_model(
        data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_type=ModelType.EMBEDDING
    )

    assert provider.config.model_id == "local-embedding"
    assert provider.config.model_type == ModelType.EMBEDDING


def test_router_remove_route(setup_models):
    """测试移除路由规则"""
    router = ModelRouter()
    router.registry = setup_models

    # 注册规则
    router.register_route(
        data_level=DataLevel.PUBLIC, task_type=TaskType.SUMMARIZE, model_id="local-llm"
    )

    # 验证规则存在
    rules = router.get_routing_rules()
    assert (DataLevel.PUBLIC, TaskType.SUMMARIZE, ModelType.LLM) in rules

    # 移除规则
    router.remove_route(data_level=DataLevel.PUBLIC, task_type=TaskType.SUMMARIZE)

    # 验证规则已移除
    rules = router.get_routing_rules()
    assert (DataLevel.PUBLIC, TaskType.SUMMARIZE) not in rules


def test_router_no_model_available():
    """测试无可用模型时抛出异常"""
    router = ModelRouter()
    router.registry = ModelRegistry()  # 空注册表

    with pytest.raises(RouterError, match="No available model"):
        router.get_model(
            data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_type=ModelType.LLM
        )


def test_router_model_not_in_registry(setup_models):
    """测试配置的模型不在注册表中"""
    router = ModelRouter()
    router.registry = setup_models

    # 注册一个不存在的模型ID
    router.register_route(
        data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_id="non-existent-model"
    )

    with pytest.raises(RouterError, match="not found in registry"):
        router.get_model(
            data_level=DataLevel.PUBLIC, task_type=TaskType.QA, model_type=ModelType.LLM
        )


def test_router_context_passed_to_gateway(setup_models):
    """测试上下文信息传递到闸门"""
    router = ModelRouter()
    router.registry = setup_models

    context = {"user_id": "user-123", "request_id": "req-456"}

    # 应正常通过并记录上下文
    provider = router.get_model(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_type=ModelType.LLM,
        context=context,
    )

    assert provider is not None
