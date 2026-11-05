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

    topics: list[str] = Field(default_factory=list, max_length=12)


class ExternalBatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ids: list[str] = Field(min_length=1, max_length=50)
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)
