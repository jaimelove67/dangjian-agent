"""敏感数据出网安全测试（框架文档 10.1 / B2 红线）

出网闸门依赖 structlog（模型接入层），未安装时跳过（完整环境会执行）。
"""
import pytest

pytest.importorskip("structlog")

from app.llm.base import (  # noqa: E402
    DataLevel,
    DeploymentType,
    ModelConfig,
    ModelType,
)
from app.llm.gateway import DataLevelGateway, GatewayError  # noqa: E402

pytestmark = pytest.mark.security


def _config(deployment: DeploymentType) -> ModelConfig:
    return ModelConfig(
        model_id="m",
        model_name="m",
        model_type=ModelType.LLM,
        deployment_type=deployment,
        provider="external-provider",
    )


def test_public_external_allowed():
    allowed, _ = DataLevelGateway().check_access(
        DataLevel.PUBLIC, _config(DeploymentType.EXTERNAL)
    )
    assert allowed is True


def test_sensitive_external_blocked():
    allowed, reason = DataLevelGateway().check_access(
        DataLevel.SENSITIVE, _config(DeploymentType.EXTERNAL)
    )
    assert allowed is False
    assert reason


def test_sensitive_local_allowed():
    allowed, _ = DataLevelGateway().check_access(
        DataLevel.SENSITIVE, _config(DeploymentType.LOCAL)
    )
    assert allowed is True


def test_classified_blocked():
    allowed, _ = DataLevelGateway().check_access(
        DataLevel.CLASSIFIED, _config(DeploymentType.LOCAL)
    )
    assert allowed is False


def test_validate_and_block_raises():
    with pytest.raises(GatewayError):
        DataLevelGateway().validate_and_block(
            DataLevel.SENSITIVE, _config(DeploymentType.EXTERNAL)
        )
