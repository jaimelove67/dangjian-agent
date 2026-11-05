"""外部党建资料审核接口契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExternalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


class ExternalPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    org_unit_id: str | None = Field(default=None, max_length=36)
    topics: list[str] = Field(default_factory=list, max_length=12)
    sources: list[str] | None = Field(default=None, max_length=10)


class ExternalBatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ids: list[str] = Field(min_length=1, max_length=50)
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)
