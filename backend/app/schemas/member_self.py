"""党员本人档案和提交材料的接口契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.member import MemberRosterItem

MaterialCategory = Literal["thought_report", "study_note", "certificate", "other"]


class PersonalArchive(BaseModel):
    profile: MemberRosterItem | None
    max_upload_size: int


class AccountLinkRequest(BaseModel):
    """本人档案关联请求：账号可为党员或申请人，须与档案同组织。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=1, max_length=50)


class MaterialSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    category: MaterialCategory
    description: str = Field(default="", max_length=2000)


class PersonalMaterial(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    category: MaterialCategory
    description: str
    file_name: str
    file_size: int
    created_at: datetime
    status: Literal["submitted"] = "submitted"


class MaterialList(BaseModel):
    items: list[PersonalMaterial]
    total: int
    page: int
    page_size: int
