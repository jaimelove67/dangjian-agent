"""卷内目录核对（MemberDevelopment.archive_checklist）的分支测试。

不连数据库：用 AsyncMock 顶掉取档案、取材料、取程序记录三处，只验证判定与汇总口径。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.member_service import MemberDevelopment


def _service(*, stage: str, materials: list[dict] | None = None, procedures: list | None = None):
    svc = object.__new__(MemberDevelopment)
    svc.tenant_id = "t-1"
    svc.user = None
    svc.db = None
    svc.profile = AsyncMock(return_value=SimpleNamespace(id="p-1", current_stage=stage))
    svc.list_materials = AsyncMock(return_value=materials or [])
    svc._procedure_rows = AsyncMock(return_value=procedures or [])
    return svc


def _material(material_type: str, status: str = "approved", legacy: bool = False, mid: str = "m-1"):
    return {
        "id": mid,
        "material_type": material_type,
        "review_status": status,
        "legacy_material": legacy,
        "document_date": None,
    }


def _procedure(kind: str, status: str):
    return SimpleNamespace(kind=kind, status=status)


@pytest.mark.asyncio
async def test_totals_cover_all_38_items():
    result = await _service(stage="applicant").archive_checklist("p-1")
    assert result["total"] == 38
    assert sum(section["total"] for section in result["sections"]) == 38
    assert len(result["sections"]) == 5


@pytest.mark.asyncio
async def test_missing_items_reported_without_blocking():
    result = await _service(stage="candidate").archive_checklist("p-1")
    assert result["missing"] > 0
    assert result["status"] == "pending"
    assert result["label"] == "待补"
    assert result["hard_gate"] is False
    assert "不阻断阶段流转" in result["message"]


@pytest.mark.asyncio
async def test_approved_material_marks_item_archived():
    svc = _service(
        stage="applicant",
        materials=[_material("入党申请书"), _material("党组织谈话记录", mid="m-2")],
    )
    result = await svc.archive_checklist("p-1")
    application = next(s for s in result["sections"] if s["key"] == "application")
    assert [row["status"] for row in application["items"]] == ["archived", "archived"]
    assert application["archived"] == 2
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_unreviewed_or_legacy_material_does_not_count():
    svc = _service(
        stage="applicant",
        materials=[
            _material("入党申请书", status="pending"),
            _material("党组织谈话记录", legacy=True),
        ],
    )
    result = await svc.archive_checklist("p-1")
    application = next(s for s in result["sections"] if s["key"] == "application")
    assert [row["status"] for row in application["items"]] == ["missing", "missing"]


@pytest.mark.asyncio
async def test_only_final_procedure_status_counts():
    """公示进行中不算完成；completed 才算。"""
    in_progress = _service(stage="activist", procedures=[_procedure("publicity", "draft")])
    result = await in_progress.archive_checklist("p-1")
    m06 = next(
        row
        for section in result["sections"]
        for row in section["items"]
        if row["code"] == "m06"
    )
    assert m06["status"] == "missing"

    done = _service(stage="activist", procedures=[_procedure("publicity", "completed")])
    result = await done.archive_checklist("p-1")
    m06 = next(
        row
        for section in result["sections"]
        for row in section["items"]
        if row["code"] == "m06"
    )
    assert m06["status"] == "archived"


@pytest.mark.asyncio
async def test_manual_only_items_are_not_reported_as_missing():
    result = await _service(stage="activist").archive_checklist("p-1")
    m03 = next(
        row
        for section in result["sections"]
        for row in section["items"]
        if row["code"] == "m03"
    )
    # 推优表只能人工确认，不谎报缺材料
    assert m03["status"] == "unconfirmed"
    assert m03["status_label"] == "待人工确认"


@pytest.mark.asyncio
async def test_later_sections_are_not_applicable_for_applicant():
    result = await _service(stage="applicant").archive_checklist("p-1")
    for section in result["sections"]:
        expected = "not_applicable" if section["key"] != "application" else None
        if expected:
            assert all(row["status"] == expected for row in section["items"])
    assert result["not_applicable"] == 36


@pytest.mark.asyncio
async def test_optional_item_is_not_counted_as_missing():
    result = await _service(stage="candidate").archive_checklist("p-1")
    m17 = next(
        row
        for section in result["sections"]
        for row in section["items"]
        if row["code"] == "m17"
    )
    assert m17["status"] == "optional"
    assert m17["required"] is False


@pytest.mark.asyncio
async def test_rejected_stage_is_not_tracked():
    result = await _service(stage="rejected").archive_checklist("p-1")
    assert result["status"] == "not_applicable"
    assert result["label"] == "不核对"
    assert result["archived"] == 0 and result["missing"] == 0


@pytest.mark.asyncio
async def test_rows_carry_manual_reference():
    result = await _service(stage="probationary").archive_checklist("p-1")
    first = result["sections"][0]["items"][0]
    assert first["code"] == "m01"
    assert first["page"] == 3
    assert first["carrier_label"] == "粘贴页"
    assert result["notice"].startswith("卷内目录按手册五阶段核对")
