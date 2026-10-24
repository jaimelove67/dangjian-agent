"""Production model access requires current school approvals and exact TLS hosts."""

import pytest

from app.core.config import TenantConfig, settings
from app.core.tenant import tenant_context
from app.llm import gateway as module
from app.llm.base import DataLevel, DeploymentType, ModelConfig, ModelType


@pytest.fixture
def approved_school(monkeypatch):
    configuration = TenantConfig()
    for school in ("approved-school", "unconfirmed-school"):
        configuration.set(school, "_tenant_type", "school")
    for approval in ("registration", "organization_approval", "it_approval", "secrecy_approval"):
        configuration.set("approved-school", approval, {"status": "confirmed"})
    configuration.set("approved-school", "pilot_scope", "synthetic acceptance only")
    policy = {
        "external_enabled": True,
        "internal_approved": True,
        "allowed_hosts": ["external.example"],
        "local_sensitive_enabled": True,
        "local_hosts": ["local.example"],
        "evidence": "synthetic approval evidence",
    }
    configuration.set("approved-school", "model_policy", policy)
    configuration._parents["department"] = "approved-school"
    monkeypatch.setattr(module, "tenant_config", configuration)
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "ALLOWED_LOCAL_MODEL_HOSTS", ["local.example"])
    gate = module.DataLevelGateway()
    gate.allowed_external_domains = {"external.example"}
    return configuration, policy, gate


def model(deployment, endpoint):
    return ModelConfig(
        model_id="synthetic",
        model_name="synthetic",
        model_type=ModelType.LLM,
        deployment_type=deployment,
        provider="synthetic",
        endpoint=endpoint,
    )


@pytest.mark.parametrize(
    "missing",
    ["registration", "organization_approval", "it_approval", "secrecy_approval", "pilot_scope"],
)
def test_each_required_school_confirmation_blocks_model_access(approved_school, missing):
    configuration, _, gate = approved_school
    configuration.set("approved-school", missing, "" if missing == "pilot_scope" else {})
    with tenant_context("department"):
        for deployment, endpoint in (
            (DeploymentType.EXTERNAL, "https://external.example/v1"),
            (DeploymentType.LOCAL, "https://local.example/v1"),
        ):
            assert not gate.check_access(DataLevel.PUBLIC, model(deployment, endpoint))[0]


def test_approved_school_does_not_authorize_another_school(approved_school):
    _, _, gate = approved_school
    with tenant_context("unconfirmed-school"):
        assert not gate.check_access(
            DataLevel.PUBLIC, model(DeploymentType.EXTERNAL, "https://external.example/v1")
        )[0]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://local.example/v1",
        "https://local.example.attacker/v1",
        "https://user:password@local.example/v1",
        "https://local.example/v1#fragment",
    ],
)
def test_local_school_approval_never_authorizes_non_tls_or_confused_hosts(
    approved_school, endpoint
):
    _, _, gate = approved_school
    with tenant_context("approved-school"):
        assert not gate.check_access(DataLevel.SENSITIVE, model(DeploymentType.LOCAL, endpoint))[0]


def test_external_and_local_data_levels_obey_separate_approvals(approved_school):
    _, policy, gate = approved_school
    external = model(DeploymentType.EXTERNAL, "https://external.example/v1")
    local = model(DeploymentType.LOCAL, "https://local.example/v1")
    with tenant_context("department"):
        assert gate.check_access(DataLevel.PUBLIC, external)[0]
        assert gate.check_access(DataLevel.INTERNAL, external)[0]
        assert gate.check_access(DataLevel.SENSITIVE, local)[0]
        assert not gate.check_access(DataLevel.SENSITIVE, external)[0]
        assert not gate.check_access(DataLevel.CLASSIFIED, local)[0]
        policy["internal_approved"] = False
        assert not gate.check_access(DataLevel.INTERNAL, external)[0]
        assert gate.check_access(DataLevel.PUBLIC, external)[0]
        policy["external_enabled"] = False
        assert not gate.check_access(DataLevel.PUBLIC, external)[0]
        policy["local_sensitive_enabled"] = False
        assert not gate.check_access(DataLevel.SENSITIVE, local)[0]
