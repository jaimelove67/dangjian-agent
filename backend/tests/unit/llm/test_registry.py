"""测试模型注册表"""

import pytest
from app.llm.registry import ModelRegistry
from app.llm.base import (
    ModelConfig,
    ModelType,
    DeploymentType,
    BaseModelProvider,
    ModelResponse,
    EmbeddingResponse,
)


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


def test_registry_register():
    """测试注册模型"""
    registry = ModelRegistry()

    config = ModelConfig(
        model_id="test-model-1",
        model_name="Test Model 1",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    provider = MockProvider(config)
    registry.register(provider)

    assert registry.get_provider("test-model-1") is not None
    assert registry.get_config("test-model-1") == config


def test_registry_duplicate_register():
    """测试重复注册抛出异常"""
    registry = ModelRegistry()

    config = ModelConfig(
        model_id="test-model-2",
        model_name="Test Model 2",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    provider1 = MockProvider(config)
    provider2 = MockProvider(config)

    registry.register(provider1)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider2)


def test_registry_unregister():
    """测试注销模型"""
    registry = ModelRegistry()

    config = ModelConfig(
        model_id="test-model-3",
        model_name="Test Model 3",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    provider = MockProvider(config)
    registry.register(provider)
    registry.unregister("test-model-3")

    assert registry.get_provider("test-model-3") is None


def test_registry_list_models():
    """测试列出模型"""
    registry = ModelRegistry()

    # 注册多个模型
    configs = [
        ModelConfig(
            model_id="llm-local",
            model_name="LLM Local",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        ),
        ModelConfig(
            model_id="llm-external",
            model_name="LLM External",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="test",
        ),
        ModelConfig(
            model_id="embedding-local",
            model_name="Embedding Local",
            model_type=ModelType.EMBEDDING,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        ),
    ]

    for config in configs:
        provider = MockProvider(config)
        registry.register(provider)

    # 测试过滤
    llm_models = registry.list_models(model_type=ModelType.LLM)
    assert len(llm_models) == 2
    assert "llm-local" in llm_models
    assert "llm-external" in llm_models

    local_models = registry.list_models(deployment_type=DeploymentType.LOCAL)
    assert len(local_models) == 2
    assert "llm-local" in local_models
    assert "embedding-local" in local_models

    llm_local = registry.list_models(
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL
    )
    assert len(llm_local) == 1
    assert "llm-local" in llm_local


def test_registry_has_local_model():
    """测试检查本地模型"""
    registry = ModelRegistry()

    config = ModelConfig(
        model_id="embedding-local",
        model_name="Embedding Local",
        model_type=ModelType.EMBEDDING,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    assert not registry.has_local_model(ModelType.EMBEDDING)

    provider = MockProvider(config)
    registry.register(provider)

    assert registry.has_local_model(ModelType.EMBEDDING)
    assert not registry.has_local_model(ModelType.LLM)


@pytest.mark.asyncio
async def test_registry_health_check():
    """测试健康检查"""
    registry = ModelRegistry()

    config = ModelConfig(
        model_id="test-model-health",
        model_name="Test Model Health",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    provider = MockProvider(config)
    registry.register(provider)

    results = await registry.health_check_all()

    assert "test-model-health" in results
    assert results["test-model-health"] is True


def test_registry_stats():
    """测试统计信息"""
    registry = ModelRegistry()

    configs = [
        ModelConfig(
            model_id="llm-1",
            model_name="LLM 1",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        ),
        ModelConfig(
            model_id="llm-2",
            model_name="LLM 2",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="test",
        ),
        ModelConfig(
            model_id="embedding-1",
            model_name="Embedding 1",
            model_type=ModelType.EMBEDDING,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        ),
    ]

    for config in configs:
        provider = MockProvider(config)
        registry.register(provider)

    stats = registry.get_stats()

    assert stats["total"] == 3
    assert stats["by_type"]["llm"] == 2
    assert stats["by_type"]["embedding"] == 1
    assert stats["by_deployment"]["local"] == 2
    assert stats["by_deployment"]["external"] == 1
