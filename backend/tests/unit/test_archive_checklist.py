"""卷内目录（38 项材料）与既有材料类型、程序节点的口径校验。

这组测试防的是"两份清单漂移"：
- 后端 ``ARCHIVE_MATERIAL_TYPES`` 与 ``PROCEDURE_STATUSES`` 改了名，清单里还留着旧值；
- 前端 ``frontend/src/archive-checklist.js`` 与后端条目不一致。
"""

import re
from pathlib import Path

import pytest

from app.rules.archive_checklist import (
    ARCHIVE_CHECKLIST,
    SECTION_ORDER,
    SECTION_MEMBER_STAGE,
    ArchiveItem,
    items_for_section,
    manual_only_codes,
    required_items,
    section_counts,
)
from app.services.member_archive_service import ARCHIVE_MATERIAL_TYPES
from app.services.member_service import PROCEDURE_STATUSES


class TestChecklistShape:
    def test_has_38_items_numbered_in_order(self):
        assert len(ARCHIVE_CHECKLIST) == 38
        assert [item.no for item in ARCHIVE_CHECKLIST] == list(range(1, 39))
        assert [item.code for item in ARCHIVE_CHECKLIST] == [
            f"m{no:02d}" for no in range(1, 39)
        ]

    def test_codes_are_unique_and_names_unique_within_section(self):
        """名称可跨阶段重复（材料 13 与 33 手册同名），因此只能按 code 索引。"""
        codes = [item.code for item in ARCHIVE_CHECKLIST]
        assert len(set(codes)) == len(codes)
        scoped = [(item.section, item.name) for item in ARCHIVE_CHECKLIST]
        assert len(set(scoped)) == len(scoped)
        duplicated = [i.no for i in ARCHIVE_CHECKLIST if i.name == "党内外群众意见座谈会记录"]
        assert duplicated == [13, 33]

    def test_section_counts_match_manual(self):
        # 手册五阶段：2 / 8 / 10 / 7 / 11 项
        assert section_counts() == {
            "application": 2,
            "activist": 8,
            "candidate": 10,
            "reception": 7,
            "probationary": 11,
        }
        assert sum(section_counts().values()) == 38

    def test_pages_are_ascending(self):
        pages = [item.page for item in ARCHIVE_CHECKLIST]
        assert pages == sorted(pages)

    def test_every_section_maps_to_a_member_stage(self):
        assert tuple(SECTION_MEMBER_STAGE) == SECTION_ORDER
        for section in SECTION_ORDER:
            assert items_for_section(section)


class TestMappingToExistingRules:
    def test_material_types_are_known(self):
        unknown = {
            item.code: [t for t in item.material_types if t not in ARCHIVE_MATERIAL_TYPES]
            for item in ARCHIVE_CHECKLIST
            if any(t not in ARCHIVE_MATERIAL_TYPES for t in item.material_types)
        }
        assert unknown == {}

    def test_procedure_kinds_are_known(self):
        unknown = {
            item.code: [k for k in item.procedure_kinds if k not in PROCEDURE_STATUSES]
            for item in ARCHIVE_CHECKLIST
            if any(k not in PROCEDURE_STATUSES for k in item.procedure_kinds)
        }
        assert unknown == {}

    def test_every_item_is_trackable_or_explicitly_manual(self):
        """每项必须至少有一种判定途径，或明确标为只能人工确认。"""
        for item in ARCHIVE_CHECKLIST:
            assert item.material_types or item.procedure_kinds or item.manual_only, item.code

    def test_only_truly_untrackable_items_are_manual(self):
        # 推优表、确定积极分子意见、两次支委会讨论记录、自传、宣誓情况、转正审批请示
        assert manual_only_codes() == ("m03", "m04", "m05", "m11", "m12", "m14", "m28", "m37")


class TestChecklistRules:
    def test_letter_of_inquiry_is_optional(self):
        item = next(i for i in ARCHIVE_CHECKLIST if i.no == 17)
        assert item.required is False
        assert item.code not in {i.code for i in required_items("candidate")}

    def test_placeholder_items_follow_manual_annex(self):
        by_no = {item.no: item for item in ARCHIVE_CHECKLIST}
        # 志愿书与预备党员考察表在手册里只有占位页，表体另附
        assert by_no[24].carrier == "placeholder"
        assert by_no[29].carrier == "placeholder"
        assert by_no[24].procedure_kinds == ("application_form",)

    def test_two_publicity_windows_have_different_rules(self):
        """接收阶段公示 5 个工作日，转正公示一般 7 天，口径不可互相套用。"""
        by_no = {item.no: item for item in ARCHIVE_CHECKLIST}
        assert "5 个工作日" in by_no[15].note
        assert "5 个工作日" in by_no[23].note
        assert "7 天" in by_no[35].note

    def test_all_items_are_namedtuple_with_expected_fields(self):
        assert isinstance(ARCHIVE_CHECKLIST[0], ArchiveItem)
        assert ARCHIVE_CHECKLIST[0]._fields == (
            "code",
            "no",
            "name",
            "section",
            "carrier",
            "required",
            "material_types",
            "procedure_kinds",
            "page",
            "note",
        )


_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src" / "archive-checklist.js"


@pytest.mark.skipif(not _FRONTEND.exists(), reason="前端目录不在当前工作树（容器内只跑后端）")
def test_frontend_copy_matches_backend():
    """前端副本必须与后端条目一一对应：编号、序号、名称、阶段、载体、必备。"""
    text = _FRONTEND.read_text(encoding="utf-8")
    rows = re.findall(
        r'\["(m\d{2})",\s*(\d+),\s*"([^"]+)",\s*"(\w+)",\s*"(\w+)",\s*(true|false),',
        text,
    )
    assert len(rows) == 38, "前端清单条目数应与后端一致"
    expected = [
        (i.code, str(i.no), i.name, i.section, i.carrier, "true" if i.required else "false")
        for i in ARCHIVE_CHECKLIST
    ]
    assert rows == expected
