"""学校配置与准入状态。配置能力与正式审批证据分开记录。"""

import ipaddress
import logging
import re
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings, tenant_config
from app.core.constants import REVIEW_CYCLE_MAX_DAYS, REVIEW_CYCLE_MIN_DAYS, DocumentAuthority
from app.llm.registry import get_model_registry
from app.models.governance import ConfigRevision
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.governance import StrictInput
from app.services.archive_service import archive_policy
from app.services.member_service import _load_scoring_rules

logger = logging.getLogger(__name__)


def exact_host(value: str) -> str:
    value = value.lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            value,
        ):
            raise ValueError("白名单只能包含精确主机名或 IP，不能包含 URL、路径或通配符")
        return value


class Approval(StrictInput):
    status: Literal["pending", "confirmed", "revoked"] = "pending"
    evidence: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def evidence_required(self) -> "Approval":
        if self.status == "confirmed" and not self.evidence:
            raise ValueError("确认必须提供学校认可的依据")
        return self


class ModelPolicy(StrictInput):
    external_enabled: bool = False
    internal_approved: bool = False
    local_sensitive_enabled: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=20)
    local_hosts: list[str] = Field(default_factory=list, max_length=20)
    evidence: str = Field(default="", max_length=2000)

    @field_validator("allowed_hosts", "local_hosts")
    @classmethod
    def hosts(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(exact_host(value) for value in values))

    @model_validator(mode="after")
    def valid_approval(self) -> "ModelPolicy":
        if (
            self.external_enabled or self.local_sensitive_enabled or self.internal_approved
        ) and not self.evidence:
            raise ValueError("模型使用确认必须提供审批依据")
        if self.internal_approved and not self.external_enabled:
            raise ValueError("内部资料出网确认需要同时启用外部模型")
        return self


class RetentionPolicy(StrictInput):
    file_days: int = Field(default=365, ge=365, le=36500)
    audit_days: int = Field(default=365, ge=365, le=36500)
    physical_purge: Literal["disabled", "approval_required"] = "disabled"
    evidence: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def approved_purge(self) -> "RetentionPolicy":
        if self.physical_purge != "disabled" and not self.evidence:
            raise ValueError("物理清理策略需要留存审批依据")
        return self


class SupplyRule(StrictInput):
    """某一权威来源的供给机制（T-KB-13）

    责任部门与责任人回答"谁来维护"，更新周期回答"多久复核一次"。三者必须同时
    给出：只写周期不写责任人，到期后没人知道该找谁；只写人不写周期，机制不会
    产生任何到期提醒。
    """

    owner_unit: str = Field(min_length=1, max_length=100)
    owner_name: str = Field(min_length=1, max_length=50)
    review_cycle_days: int = Field(ge=REVIEW_CYCLE_MIN_DAYS, le=REVIEW_CYCLE_MAX_DAYS)


class GovernanceValues(StrictInput):
    registration: Approval = Field(default_factory=Approval)
    organization_approval: Approval = Field(default_factory=Approval)
    it_approval: Approval = Field(default_factory=Approval)
    secrecy_approval: Approval = Field(default_factory=Approval)
    pilot_scope: str = Field(default="", max_length=1000)
    model_policy: ModelPolicy = Field(default_factory=ModelPolicy)
    model_routes: dict[Literal["llm", "embedding", "reranker"], str] = Field(default_factory=dict)
    scoring_weights: dict[str, float] = Field(default_factory=dict)
    prompt_versions: dict[Literal["qa", "rewrite"], Literal["v1", "v2"]] = Field(
        default_factory=dict
    )
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    # 供给机制（T-KB-13）：按权威来源登记责任部门、责任人与更新周期。未登记
    # 的类别不回填日程，条目仍可按元数据维护，只是没有到期提醒。
    knowledge_supply: dict[str, SupplyRule] = Field(default_factory=dict)

    @field_validator("knowledge_supply")
    @classmethod
    def supply_authorities(cls, values: dict[str, SupplyRule]) -> dict[str, SupplyRule]:
        known = {item.value for item in DocumentAuthority}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                "供给机制只能按权威来源登记（"
                + "、".join(sorted(known))
                + "）；无法识别的类别："
                + "、".join(unknown)
            )
        return values

    @field_validator("scoring_weights")
    @classmethod
    def weights(cls, values: dict[str, float]) -> dict[str, float]:
        if values and (
            set(values) != set(_load_scoring_rules()["weights"])
            or any(value <= 0 or value > 1 for value in values.values())
            or abs(sum(values.values()) - 1) > 0.000001
        ):
            raise ValueError("评分权重必须包含现有全部维度、均为正数且总和为 1")
        return values


class GovernanceUpdate(StrictInput):
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    values: GovernanceValues


def default_values(config: dict[str, Any]) -> dict[str, Any]:
    keys = GovernanceValues.model_fields
    return GovernanceValues.model_validate(
        {key: config[key] for key in keys if key in config}
    ).model_dump()


async def supply_rules(db: AsyncSession, tenant_id: str) -> dict[str, dict[str, Any]]:
    """读取租户的供给机制（T-KB-13）：权威来源 → 责任部门 / 责任人 / 更新周期

    供给机制只是条目排定复核日程的依据，不是使用知识库的前提：租户未登记、
    或配置本身已损坏时都按"没有机制"处理，绝不让知识条目入库因此失败。治理页
    读取同一份配置时会显式报错，问题不会被悄悄掩盖。
    """
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if tenant is None or not tenant.config:
        return {}
    try:
        values = default_values(tenant.config)
    except ValidationError:
        logger.warning("governance_config_invalid", extra={"tenant_id": tenant_id}, exc_info=True)
        return {}
    return values.get("knowledge_supply") or {}


def admission(values: dict[str, Any], archive: dict[str, Any]) -> dict[str, Any]:
    pending = [
        key
        for key in ("registration", "organization_approval", "it_approval", "secrecy_approval")
        if values.get(key, {}).get("status") != "confirmed"
    ]
    if not values.get("pilot_scope"):
        pending.append("pilot_scope")
    return {
        "status": "pending" if pending else "configured",
        "pending": pending,
        "electronic_archive": "confirmed" if archive.get("enabled") is True else "pending",
        "notice": "配置记录不能代替学校正式评审；试点按批准范围执行。",
    }


async def read_governance(db: AsyncSession, user: User) -> dict[str, Any]:
    tenant = (
        await db.execute(
            select(Tenant).where(Tenant.id == str(user.tenant_id), Tenant.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if tenant is None:
        return {
            "version": 0,
            "values": GovernanceValues().model_dump(),
            "admission": admission({}, {}),
            "inherited": {},
            "model_catalog": [],
        }
    await tenant_config.load(db, str(user.tenant_id))
    values = default_values(tenant.config or {})
    inherited = {
        key: tenant_config.get(str(user.tenant_id), key, {})
        for key in ("model_routes", "scoring_weights", "prompt_versions")
    }
    catalog = []
    registry = get_model_registry()
    for model_id in registry.list_models():
        model = registry.get_config(model_id)
        if model is None:
            continue
        catalog.append(
            {
                "id": model_id,
                "type": model.model_type.value,
                "deployment": model.deployment_type.value,
                "provider": model.provider,
            }
        )
    policy = await archive_policy(db, str(user.tenant_id))
    return {
        "version": tenant.config_version,
        "values": values,
        "inherited": inherited,
        "admission": admission(values, policy),
        "archive_policy": policy,
        "model_catalog": catalog,
    }


async def save_governance(db: AsyncSession, user: User, body: GovernanceUpdate) -> dict[str, Any]:
    row = (
        await db.execute(
            select(Tenant)
            .where(Tenant.id == str(user.tenant_id), Tenant.is_deleted.is_(False))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "学校尚未登记，请先完成租户配置")
    if body.expected_version != row.config_version:
        raise HTTPException(409, "配置已修改，请刷新后重新提交")
    values = body.values.model_dump()
    if row.tenant_type != "school" and any(
        value.get("status") == "confirmed"
        for key, value in values.items()
        if key.endswith("_approval") or key == "registration"
    ):
        raise HTTPException(422, "正式确认必须登记在学校租户，不能继承平台确认")
    policy = body.values.model_policy
    if policy.external_enabled or policy.local_sensitive_enabled:
        if row.tenant_type != "school":
            raise HTTPException(422, "模型使用审批必须登记在学校租户")
        if (
            admission(values, (row.config or {}).get("electronic_archive", {}))["status"]
            != "configured"
        ):
            raise HTTPException(422, "启用模型前须完成学校登记、三方确认与试点范围")
    if not set(policy.allowed_hosts).issubset(
        {exact_host(host) for host in settings.ALLOWED_EXTERNAL_MODELS}
    ):
        raise HTTPException(422, "学校白名单不能超出部署批准的主机范围")
    if not set(policy.local_hosts).issubset(
        {exact_host(host) for host in settings.ALLOWED_LOCAL_MODEL_HOSTS}
    ):
        raise HTTPException(422, "校内主机必须先纳入部署批准范围")
    registry = get_model_registry()
    for kind, model_id in body.values.model_routes.items():
        model = registry.get_config(model_id)
        if model is None or model.model_type.value != kind:
            raise HTTPException(422, "模型标识不存在或类型不符")
    row.config_version += 1
    config = {**(row.config or {}), **values}
    for key in ("model_routes", "scoring_weights", "prompt_versions"):
        if not config.get(key):
            config.pop(key, None)
    row.config = config
    db.add(
        ConfigRevision(
            tenant_id=str(row.id),
            version=row.config_version,
            actor_id=str(user.id),
            reason=body.reason,
            values=values,
        )
    )
    await db.flush()
    await tenant_config.load(db, str(row.id))
    return await read_governance(db, user)
