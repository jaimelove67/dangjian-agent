"""党员基本信息采集表接口契约。

本模块只处理采集表字段，不返回完整身份证号。身份证号、出生日期、所在支部和
人员类别由档案提供，采集表只保存脱敏快照和业务字段。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Gender = Literal["male", "female"]
PartyStatus = Literal["normal", "suspended"]
FilingType = Literal["new", "supplement"]
CollectionStatus = Literal[
    "draft",
    "submitted",
    "branch_approved",
    "department_approved",
    "archived",
    "returned",
]


class SelfInfoPayload(BaseModel):
    """本人填写的 7 类信息及条件字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    gender: Gender | None = None
    ethnicity: str | None = Field(None, max_length=30)
    education_code: str | None = Field(None, max_length=10)
    mobile: str | None = Field(None, max_length=20)
    phone_area: str | None = Field(None, max_length=6)
    phone_number: str | None = Field(None, max_length=12)
    address: str | None = Field(None, max_length=200)
    lost_contact: bool | None = None
    lost_contact_on: date | None = None
    floating: bool | None = None
    floating_province: str | None = Field(None, max_length=50)
    floating_city: str | None = Field(None, max_length=50)
    floating_county: str | None = Field(None, max_length=50)


class InfoPayload(SelfInfoPayload):
    """采集表全部字段；支部补录字段由组织人员填写。"""

    join_party_on: date | None = None
    full_member_on: date | None = None
    job_code: str | None = Field(None, max_length=10)
    party_status: PartyStatus | None = None
    filing_type: FilingType | None = None
    supplement_reason: str | None = Field(None, max_length=500)
    relation_transfer: bool | None = None
    transfer_branch: str | None = Field(None, max_length=200)


class SelfInfoSubmit(SelfInfoPayload):
    confirmed: bool = False


class InfoReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approve", "return", "archive"]
    opinion: str = Field(min_length=1, max_length=1000)
    payload: InfoPayload | None = None


class InfoCollectionOut(BaseModel):
    id: str
    profile_id: str
    member_name: str
    member_stage: str
    member_stage_label: str
    org_unit_id: str | None
    org_name: str
    department: str
    id_card_masked: str
    birth_date: date | None
    stage_joined_on: date | None
    status: CollectionStatus
    version: int
    payload: InfoPayload
    history: list[dict]
    collector_name: str
    member_confirmed_at: datetime | None
    submitted_at: datetime | None
    branch_reviewed_at: datetime | None
    branch_reviewed_by_name: str
    branch_opinion: str
    department_reviewed_at: datetime | None
    department_reviewed_by_name: str
    department_opinion: str
    archived_at: datetime | None
    archived_by_name: str
    returned_at: datetime | None
    returned_by_name: str
    return_reason: str
    return_stage: str
    created_at: datetime
    updated_at: datetime


class InfoCollectionSummary(BaseModel):
    id: str
    profile_id: str
    member_name: str
    member_stage: str
    member_stage_label: str
    org_unit_id: str | None
    org_name: str
    department: str
    status: CollectionStatus
    version: int
    submitted_at: datetime | None
    updated_at: datetime
    return_reason: str


class InfoCollectionList(BaseModel):
    items: list[InfoCollectionSummary]
    total: int
    counts: dict[str, int]


class SelfInfoProfile(BaseModel):
    id: str
    name: str
    org_name: str
    stage: str
    stage_label: str
    id_card_masked: str
    birth_date: date | None
    stage_joined_on: date | None
    person_category: str
    suggested_join_party_on: date | None = None
    suggested_full_member_on: date | None = None


class SelfInfoOut(BaseModel):
    profile: SelfInfoProfile
    collection: InfoCollectionOut | None
    can_edit: bool
    can_submit: bool
