"""党员本人档案和提交材料的接口契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.member import MemberRosterItem

MaterialCategory = Literal["thought_report", "study_note", "certificate", "other"]
MaterialReviewDecision = Literal["approved", "returned"]


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
    #: pending=待支部书记审核；approved=审核通过；returned=已退回。
    review_status: Literal["pending", "approved", "returned"] = "pending"
    review_note: str = ""
    reviewed_at: datetime | None = None
    reviewer_name: str | None = None
    #: 退回后重新提交时指向前一条材料；旧记录和旧审核记录继续保留。
    previous_material_id: str | None = None
    #: 当前查看账号是否已点“完成查阅”；组织材料接收列表据此显示“已查阅”。
    my_viewed_at: datetime | None = None
    #: 材料所有者看到的最近一次组织查阅时间；组织账号也可看到同范围的最近查阅。
    last_viewed_at: datetime | None = None
    #: 已查阅的账号数，只用于“已查阅”摘要，不返回查阅人姓名。
    viewer_count: int = 0


class MaterialReceipt(BaseModel):
    material_id: str
    viewed_at: datetime
    view_count: int


class MaterialReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: MaterialReviewDecision
    opinion: str = Field(default="", max_length=2000)


class MaterialReviewItem(BaseModel):
    id: str
    decision: MaterialReviewDecision
    opinion: str
    reviewer_name: str
    created_at: datetime


class MaterialPrevious(BaseModel):
    id: str
    title: str
    created_at: datetime
    review_status: Literal["pending", "approved", "returned"]
    review_note: str = ""
    reviewed_at: datetime | None = None
    reviewer_name: str | None = None
    reviews: list[MaterialReviewItem] = Field(default_factory=list)


class MaterialReviewHistory(BaseModel):
    material: PersonalMaterial
    reviews: list[MaterialReviewItem] = Field(default_factory=list)
    previous_material: MaterialPrevious | None = None


class MaterialList(BaseModel):
    items: list[PersonalMaterial]
    total: int
    page: int
    page_size: int
