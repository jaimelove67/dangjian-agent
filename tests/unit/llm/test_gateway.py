"""测试数据级别出网闸门"""

import pytest
from app.llm.gateway import DataLevelGateway, GatewayError
from app.llm.base import (
    DataLevel,
    ModelConfig,
    ModelType,
    DeploymentType,
)


def create_test_config(
    model_id: str,
    deployment_type: DeploymentType,
    provider: str = "test"
) -> ModelConfig:
    """创建测试用模型配置"""
    return ModelConfig(
        model_id=model_id,
        model_name=model_id,
        model_type=ModelType.LLM,
        deployment_type=deployment_type,
        provider=provider,
    )


def test_gateway_classified_data_blocked():
    """测试涉密数据被拒绝"""
    gateway = DataLevelGateway()
    gateway.enabled = True

    local_config = create_test_config("local-model", DeploymentType.LOCAL)

    # 涉密数据即使使用本地模型也被拒绝
    allowed, reason = gateway.check_access(
        DataLevel.CLASSIFIED,
        local_config
    )

    assert not allowed
    assert "涉密数据" in reason


def test_gateway_sensitive_requires_local():
    """测试敏感数据必须使用本地模型"""
    gateway = DataLevelGateway()
    gateway.enabled = True

    local_config = create_test_config("local-model", DeploymentType.LOCAL)
    external_config = create_test_config("external-model", DeploymentType.EXTERNAL)

    # 本地模型允许
    allowed, reason = gateway.check_access(
        DataLevel.SENSITIVE,
        local_config
    )
    assert allowed
    assert reason is None

    # 外部模型拒绝
    allowed, reason = gateway.check_access(
        DataLevel.SENSITIVE,
        external_config
    )
    assert not allowed
    assert "敏感数据禁止使用外部模型" in reason


def test_gateway_internal_whitelist():
    """测试内部数据的白名单机制"""
    gateway = DataLevelGateway()
    gateway.enabled = True
    gateway.allowed_external_domains = set()  # 清空白名单

    local_config = create_test_config("local-model", DeploymentType.LOCAL)
    external_config = create_test_config(
        "external-model",
        DeploymentType.EXTERNAL,
        provider="unknown"
    )

    # 本地模型始终允许
    allowed, _ = gateway.check_access(DataLevel.INTERNAL, local_config)
    assert allowed

    # 外部模型不在白名单中被拒绝
    allowed, reason = gateway.check_access(DataLevel.INTERNAL, external_config)
    assert not allowed
    assert "不在白名单" in reason

    # 添加到白名单后允许
    gateway.add_allowed_domain("unknown")
    allowed, _ = gateway.check_access(DataLevel.INTERNAL, external_config)
    assert allowed


def test_gateway_public_data_allowed():
    """测试公开数据允许所有模型"""
    gateway = DataLevelGateway()
    gateway.enabled = True

    local_config = create_test_config("local-model", DeploymentType.LOCAL)
    external_config = create_test_config("external-model", DeploymentType.EXTERNAL)

    # 本地模型允许
    allowed, _ = gateway.check_access(DataLevel.PUBLIC, local_config)
    assert allowed

    # 外部模型也允许
    allowed, _ = gateway.check_access(DataLevel.PUBLIC, external_config)
    assert allowed


def test_gateway_disabled():
    """测试闸门禁用时全部通过"""
    gateway = DataLevelGateway()
    gateway.enabled = False

    external_config = create_test_config("external-model", DeploymentType.EXTERNAL)

    # 即使是敏感数据使用外部模型也通过
    allowed, _ = gateway.check_access(DataLevel.SENSITIVE, external_config)
    assert allowed


def test_gateway_validate_and_block():
    """测试验证并阻断方法"""
    gateway = DataLevelGateway()
    gateway.enabled = True

    external_config = create_test_config("external-model", DeploymentType.EXTERNAL)

    # 敏感数据使用外部模型应抛出异常
    with pytest.raises(GatewayError, match="敏感数据禁止使用外部模型"):
        gateway.validate_and_block(
            DataLevel.SENSITIVE,
            external_config
        )

    # 公开数据应通过
    gateway.validate_and_block(
        DataLevel.PUBLIC,
        external_config
    )


def test_gateway_domain_management():
    """测试域名管理"""
    gateway = DataLevelGateway()

    # 添加域名
    gateway.add_allowed_domain("qwen.aliyun.com")
    assert "qwen.aliyun.com" in gateway.get_allowed_domains()

    # 移除域名
    gateway.remove_allowed_domain("qwen.aliyun.com")
    assert "qwen.aliyun.com" not in gateway.get_allowed_domains()


def test_gateway_endpoint_check():
    """测试端点域名检查"""
    gateway = DataLevelGateway()
    gateway.enabled = True
    gateway.allowed_external_domains = {"dashscope.aliyuncs.com"}

    config = ModelConfig(
        model_id="qwen-model",
        model_name="qwen-turbo",
        model_type=ModelType.LLM,
        deployment_type=DeploymentType.EXTERNAL,
        provider="qwen",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    )

    # 端点在白名单中应允许
    allowed, _ = gateway.check_access(DataLevel.INTERNAL, config)
    assert allowed


def test_gateway_context_logging():
    """测试上下文信息记录"""
    gateway = DataLevelGateway()
    gateway.enabled = True

    local_config = create_test_config("local-model", DeploymentType.LOCAL)

    context = {
        "user_id": "user-123",
        "tenant_id": "tenant-456",
        "request_id": "req-789"
    }

    # 应正常通过并记录上下文
    allowed, _ = gateway.check_access(
        DataLevel.PUBLIC,
        local_config,
        context=context
    )
    assert allowed
