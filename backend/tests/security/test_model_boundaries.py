"""不能由配置开关、域名相似或能力路由绕过的模型边界。"""

from types import SimpleNamespace

import pytest

from app.llm.base import DataLevel, DeploymentType, ModelConfig, ModelType, TaskType
from app.llm.gateway import DataLevelGateway
from app.llm.registry import ModelRegistry
from app.llm.router import ModelRouter


def config(kind=ModelType.LLM, endpoint=None):
    return ModelConfig(
        "external", "external", kind, DeploymentType.EXTERNAL, "qwen", endpoint=endpoint
    )


@pytest.mark.parametrize("level", [DataLevel.SENSITIVE, DataLevel.CLASSIFIED, DataLevel.INTERNAL])
def test_disabled_gateway_still_enforces_data_policy(level):
    gateway = DataLevelGateway()
    gateway.enabled = False
    gateway.allowed_external_domains = set()
    assert gateway.check_access(level, config())[0] is False


@pytest.mark.parametrize(
    "endpoint",
    ["https://dashscope.aliyuncs.com.evil.test/v1", "https://evil.test/dashscope.aliyuncs.com"],
)
def test_whitelist_matches_host_not_substring(endpoint):
    gateway = DataLevelGateway()
    gateway.enabled = True
    gateway.allowed_external_domains = {"dashscope.aliyuncs.com"}
    assert gateway.check_access(DataLevel.INTERNAL, config(endpoint=endpoint))[0] is False


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_cloud_vector_and_rerank_follow_data_policy(kind):
    gateway = DataLevelGateway()
    gateway.allowed_external_domains = {"dashscope.aliyuncs.com"}
    model = config(kind, "https://dashscope.aliyuncs.com/v1")
    assert gateway.check_access(DataLevel.PUBLIC, model)[0] is True
    assert gateway.check_access(DataLevel.INTERNAL, model)[0] is True
    assert gateway.check_access(DataLevel.SENSITIVE, model)[0] is False
    assert gateway.check_access(DataLevel.CLASSIFIED, model)[0] is False


def test_llm_route_does_not_capture_embedding_requests():
    router = ModelRouter()
    router.registry = ModelRegistry()
    llm_config = config()
    embedding_config = ModelConfig(
        "local-embedding", "local-embedding", ModelType.EMBEDDING, DeploymentType.LOCAL, "test"
    )
    for model_config in (llm_config, embedding_config):
        router.registry.register(
            SimpleNamespace(config=model_config, get_model_id=lambda c=model_config: c.model_id)
        )
    router.register_route(DataLevel.PUBLIC, TaskType.QA, "external")
    assert (
        router.get_model(DataLevel.PUBLIC, model_type=ModelType.EMBEDDING).config
        == embedding_config
    )
