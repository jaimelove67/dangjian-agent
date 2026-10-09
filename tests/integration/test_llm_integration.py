"""LLM模块集成测试

测试模型注册、路由、闸门的完整集成流程。
"""
import pytest

from app.llm.base import (
    DataLevel,
    TaskType,
    ModelType,
    DeploymentType,
    ModelConfig,
    ModelResponse,
    EmbeddingResponse,
)
from app.llm.registry import ModelRegistry
from app.llm.router import ModelRouter, RouterError
from app.llm.gateway import DataLevelGateway, GatewayError
from app.llm.service import ModelService


# ============================================================
# 假模型提供者（用于测试）
# ============================================================

class FakeLLMProvider:
    """假LLM提供者"""
    def __init__(self, config: ModelConfig):
        self.config = config

    async def generate(self, prompt: str, **kwargs) -> ModelResponse:
        return ModelResponse(
            content=f"假响应: {prompt[:20]}",
            model_id=self.config.model_id,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    async def embed(self, texts: list[str], **kwargs) -> EmbeddingResponse:
        return EmbeddingResponse(
            embeddings=[[0.1] * 128 for _ in texts],
            model_id=self.config.model_id,
            dimensions=128,
        )

    async def health_check(self) -> bool:
        return True

    def get_model_id(self) -> str:
        return self.config.model_id

    def get_deployment_type(self) -> DeploymentType:
        return self.config.deployment_type


@pytest.fixture
def registry():
    """创建干净的注册表"""
    return ModelRegistry()


@pytest.fixture
def gateway():
    """创建闸门（启用）"""
    gateway = DataLevelGateway()
    gateway.enabled = True
    return gateway


@pytest.fixture
def router(registry, gateway, monkeypatch):
    """创建路由器"""
    # 替换单例
    monkeypatch.setattr("app.llm.router.get_model_registry", lambda: registry)
    monkeypatch.setattr("app.llm.router.get_gateway", lambda: gateway)
    return ModelRouter()


def test_register_and_list_models(registry):
    """测试注册和列出模型"""
    # 注册本地LLM
    local_llm = FakeLLMProvider(
        ModelConfig(
            model_id="local-llm",
            model_name="本地大模型",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.LOCAL,
            provider="local",
        )
    )
    registry.register(local_llm)

    # 注册外部Embedding
    external_emb = FakeLLMProvider(
        ModelConfig(
            model_id="external-embedding",
            model_name="外部向量化",
            model_type=ModelType.EMBEDDING,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
            api_key="fake-key",
        )
    )
    registry.register(external_emb)

    # 验证列表
    all_models = registry.list_models()
    assert len(all_models) == 2
    assert "local-llm" in all_models
    assert "external-embedding" in all_models

    # 按类型过滤
    llm_models = registry.list_models(model_type=ModelType.LLM)
    assert llm_models == ["local-llm"]

    embedding_models = registry.list_models(model_type=ModelType.EMBEDDING)
    assert embedding_models == ["external-embedding"]

    # 按部署类型过滤
    local_models = registry.list_models(deployment_type=DeploymentType.LOCAL)
    assert local_models == ["local-llm"]


def test_router_strategy_sensitive_data(registry, router):
    """测试路由策略：敏感数据必须使用本地模型"""
    # 只注册外部模型
    external_llm = FakeLLMProvider(
        ModelConfig(
            model_id="external-llm",
            model_name="外部LLM",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
        )
    )
    registry.register(external_llm)

    # 敏感数据应该无法路由（没有本地模型）
    with pytest.raises(RouterError) as exc_info:
        router.get_model(
            data_level=DataLevel.SENSITIVE,
            task_type=TaskType.QA,
            model_type=ModelType.LLM,
        )

    assert "No available model" in str(exc_info.value)


def test_router_strategy_public_data(registry, router):
    """测试路由策略：公开数据优先外部模型"""
    # 注册本地和外部模型
    local_llm = FakeLLMProvider(
        ModelConfig(
            model_id="local-llm",
            model_name="本地LLM",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.LOCAL,
            provider="local",
        )
    )
    external_llm = FakeLLMProvider(
        ModelConfig(
            model_id="external-llm",
            model_name="外部LLM",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="dashscope",
        )
    )
    registry.register(local_llm)
    registry.register(external_llm)

    # 公开数据应该选择外部模型（降低成本）
    provider = router.get_model(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_type=ModelType.LLM,
    )

    assert provider.get_model_id() == "external-llm"


def test_gateway_blocks_classified_data(gateway):
    """测试闸门拦截涉密数据"""
    model_config = ModelConfig(
        model_id="any-model",
        model_name="任意模型",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="test",
    )

    # 涉密数据应该被直接拒绝
    allowed, reason = gateway.check_access(
        data_level=DataLevel.CLASSIFIED,
        model_config=model_config,
    )

    assert not allowed
    assert "涉密数据禁止进行AI处理" in reason


def test_gateway_blocks_sensitive_with_external(gateway):
    """测试闸门拦截敏感数据使用外部模型"""
    external_model = ModelConfig(
        model_id="external-llm",
        model_name="外部LLM",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="dashscope",
    )

    # 敏感数据+外部模型应该被拦截
    allowed, reason = gateway.check_access(
        data_level=DataLevel.SENSITIVE,
        model_config=external_model,
    )

    assert not allowed
    assert "敏感数据禁止使用外部模型" in reason


def test_gateway_allows_sensitive_with_local(gateway):
    """测试闸门允许敏感数据使用本地模型"""
    local_model = ModelConfig(
        model_id="local-llm",
        model_name="本地LLM",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.LOCAL,
        provider="local",
    )

    # 敏感数据+本地模型应该通过
    allowed, reason = gateway.check_access(
        data_level=DataLevel.SENSITIVE,
        model_config=local_model,
    )

    assert allowed
    assert reason is None


def test_gateway_whitelist(gateway):
    """测试闸门白名单机制"""
    # 添加到白名单
    gateway.add_allowed_domain("dashscope.aliyuncs.com")

    external_model = ModelConfig(
        model_id="external-llm",
        model_name="Qwen",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="dashscope",
        endpoint="https://dashscope.aliyuncs.com/api/v1",
    )

    # 内部数据+白名单外部模型应该通过
    allowed, reason = gateway.check_access(
        data_level=DataLevel.INTERNAL,
        model_config=external_model,
    )

    assert allowed
    assert reason is None


@pytest.mark.asyncio
async def test_registry_health_check(registry):
    """测试注册表健康检查"""
    # 注册两个模型
    model1 = FakeLLMProvider(
        ModelConfig(
            model_id="model-1",
            model_name="模型1",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        )
    )
    model2 = FakeLLMProvider(
        ModelConfig(
            model_id="model-2",
            model_name="模型2",
            model_type=ModelType.EMBEDDING,
            deployment_type=DeploymentType.LOCAL,
            provider="test",
        )
    )
    registry.register(model1)
    registry.register(model2)

    # 健康检查
    results = await registry.health_check_all()

    assert len(results) == 2
    assert results["model-1"] is True
    assert results["model-2"] is True


def test_router_with_configured_rules(registry, router):
    """测试路由器配置规则"""
    # 注册模型
    model = FakeLLMProvider(
        ModelConfig(
            model_id="special-qa-model",
            model_name="专用问答模型",
            model_type=ModelType.LLM,
            deployment_type=DeploymentType.EXTERNAL,
            provider="custom",
        )
    )
    registry.register(model)

    # 注册路由规则
    router.register_route(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_id="special-qa-model",
    )

    # 获取模型应该使用配置的规则
    provider = router.get_model(
        data_level=DataLevel.PUBLIC,
        task_type=TaskType.QA,
        model_type=ModelType.LLM,
    )

    assert provider.get_model_id() == "special-qa-model"


def test_registry_stats(registry):
    """测试注册表统计信息"""
    # 注册多个模型
    registry.register(
        FakeLLMProvider(
            ModelConfig(
                model_id="llm-1",
                model_name="LLM1",
                model_type=ModelType.LLM,
                deployment_type=DeploymentType.LOCAL,
                provider="test",
            )
        )
    )
    registry.register(
        FakeLLMProvider(
            ModelConfig(
                model_id="emb-1",
                model_name="EMB1",
                model_type=ModelType.EMBEDDING,
                deployment_type=DeploymentType.EXTERNAL,
                provider="test",
            )
        )
    )
    registry.register(
        FakeLLMProvider(
            ModelConfig(
                model_id="emb-2",
                model_name="EMB2",
                model_type=ModelType.EMBEDDING,
                deployment_type=DeploymentType.LOCAL,
                provider="test",
            )
        )
    )

    # 获取统计
    stats = registry.get_stats()

    assert stats["total"] == 3
    assert stats["by_type"]["llm"] == 1
    assert stats["by_type"]["embedding"] == 2
    assert stats["by_deployment"]["local"] == 2
    assert stats["by_deployment"]["external"] == 1
