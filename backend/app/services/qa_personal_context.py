"""问答的“本人资料”上下文。

只读取当前登录账号自己的档案、基本信息采集表和个人提交材料，作为理解本人
具体情况的补充材料；它不进入制度检索、不占引用编号，也不能被当作政策依据。

隐私边界：
- 只按租户 + 当前用户 + 本人档案读取，不读取其他党员资料；
- 不把身份证号、手机号等个人标识送入模型，正文统一脱敏；
- 敏感级、涉密级个人材料不参与问答，并在回答中说明；
- 只保留来源元数据用于展示和审计，不把正文写入问答历史。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.desensitization import mask_email, mask_text
from app.llm.base import DataLevel
from app.models.member import MemberInfoCollection, MemberMaterial, MemberProfile
from app.models.user import User
from app.rules.member_stages import STAGE_LABELS, MemberStage

MAX_PERSONAL_MATERIALS = 5
MAX_PERSONAL_CHARS = 7000
MAX_MATERIAL_CHARS = 1800

_INFO_LABELS = {
    "gender": "性别",
    "ethnicity": "民族",
    "education_code": "学历代码",
    "join_party_on": "加入党组织日期",
    "full_member_on": "转为正式党员日期",
    "job_code": "工作岗位代码",
    "party_status": "党籍状态",
    "filing_type": "填报类型",
    "relation_transfer": "是否转接组织关系",
    "transfer_branch": "转入组织关系支部",
    "lost_contact": "是否失联党员",
    "floating": "是否流动党员",
    "floating_province": "外出流向省份",
    "floating_city": "外出流向城市",
    "floating_county": "外出流向县区",
}
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_TRUE_FALSE = {True: "是", False: "否"}
_PARTY_STATUS = {"normal": "正常", "suspended": "停止党籍"}
_FILING_TYPE = {"new": "当年新发展党员", "supplement": "往年党员补录"}


@dataclass(frozen=True)
class PersonalSource:
    id: str
    kind: str
    title: str
    material_type: str = ""
    occurred_on: str = ""
    version: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "material_type": self.material_type,
            "occurred_on": self.occurred_on,
            "version": self.version,
        }


@dataclass
class PersonalContext:
    text: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_level: DataLevel = DataLevel.INTERNAL
    has_profile: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip())


def _value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _TRUE_FALSE[value]
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text


def _stage_label(value: str) -> str:
    try:
        return STAGE_LABELS.get(MemberStage(value), value)
    except ValueError:
        return value


def _append(lines: list[str], label: str, value: Any) -> None:
    text = _value(value)
    if text:
        lines.append(f"{label}：{text}")


async def build_personal_context(
    db: AsyncSession,
    user: User,
    *,
    max_materials: int = MAX_PERSONAL_MATERIALS,
    max_chars: int = MAX_PERSONAL_CHARS,
) -> PersonalContext:
    """组装当前账号本人的资料块；没有本人档案时返回空上下文。"""
    profile = (
        await db.execute(
            select(MemberProfile)
            .where(
                MemberProfile.tenant_id == str(user.tenant_id),
                MemberProfile.user_id == str(user.id),
                MemberProfile.is_deleted.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if profile is None:
        return PersonalContext(has_profile=False, data_level=DataLevel.PUBLIC)

    lines = ["[本人档案]"]
    _append(lines, "姓名", profile.name)
    _append(lines, "所在组织", profile.org_name)
    _append(lines, "当前阶段", _stage_label(profile.current_stage))
    _append(lines, "进入当前阶段日期", profile.stage_joined_on)
    sources = [
        PersonalSource(
            id=str(profile.id),
            kind="profile",
            title="本人档案",
        ).as_dict()
    ]

    collection = (
        await db.execute(
            select(MemberInfoCollection)
            .where(
                MemberInfoCollection.tenant_id == str(user.tenant_id),
                MemberInfoCollection.profile_id == str(profile.id),
                MemberInfoCollection.is_deleted.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if collection is not None:
        payload = collection.payload or {}
        info_lines: list[str] = []
        for key in (
            "gender",
            "ethnicity",
            "education_code",
            "join_party_on",
            "full_member_on",
            "job_code",
            "party_status",
            "filing_type",
            "relation_transfer",
            "transfer_branch",
            "lost_contact",
            "floating",
            "floating_province",
            "floating_city",
            "floating_county",
        ):
            value = payload.get(key)
            if key == "gender":
                value = {"male": "男", "female": "女"}.get(value, value)
            elif key == "party_status":
                value = _PARTY_STATUS.get(value, value)
            elif key == "filing_type":
                value = _FILING_TYPE.get(value, value)
            _append(info_lines, _INFO_LABELS[key], value)
        if info_lines:
            lines.extend(["", f"[本人基本信息采集表 · 第{collection.version}版]"])
            lines.extend(info_lines)
        sources.append(
            PersonalSource(
                id=str(collection.id),
                kind="info_collection",
                title="本人基本信息采集表",
                version=int(collection.version or 0),
            ).as_dict()
        )

    materials = (
        (
            await db.execute(
                select(MemberMaterial)
                .options(undefer(MemberMaterial.extracted_text))
                .where(
                    MemberMaterial.tenant_id == str(user.tenant_id),
                    MemberMaterial.profile_id == str(profile.id),
                    MemberMaterial.user_id == str(user.id),
                    MemberMaterial.is_deleted.is_(False),
                )
                .order_by(MemberMaterial.created_at.desc(), MemberMaterial.id.desc())
                .limit(max_materials * 4)
            )
        )
        .scalars()
        .all()
    )
    warnings: list[str] = []
    included = 0
    used_chars = sum(len(line) + 1 for line in lines)
    for material in materials:
        if included >= max_materials or used_chars >= max_chars:
            break
        try:
            level = DataLevel(material.data_level or "internal")
        except ValueError:
            level = DataLevel.INTERNAL
        title = material.title or material.material_type or "个人材料"
        if level in {DataLevel.SENSITIVE, DataLevel.CLASSIFIED}:
            warnings.append(f"《{title}》按敏感/涉密材料管理，未参与本次问答。")
            continue
        text = str(mask_text(material.extracted_text or "") or "").strip()
        text = _EMAIL.sub(lambda match: str(mask_email(match.group(0))), text)
        if not text:
            continue
        text = text[:MAX_MATERIAL_CHARS]
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        text = text[:remaining]
        lines.extend(
            [
                "",
                f"[个人材料] {material.material_type or title}",
                f"标题：{title}",
                f"版本：{material.file_version or '未登记'}",
                f"日期：{_value(material.document_date) or '未登记'}",
            ]
        )
        if material.description:
            lines.append(f"说明：{mask_text(str(material.description)[:200])}")
        lines.append(f"正文：{text}")
        used_chars = sum(len(line) + 1 for line in lines)
        sources.append(
            PersonalSource(
                id=str(material.id),
                kind="material",
                title=title,
                material_type=material.material_type or "",
                occurred_on=_value(material.document_date),
                version=0,
            ).as_dict()
        )
        included += 1

    return PersonalContext(
        text="\n".join(lines).strip(),
        sources=sources,
        warnings=list(dict.fromkeys(warnings)),
        data_level=DataLevel.INTERNAL,
        has_profile=True,
    )
