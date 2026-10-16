"""组织生活会纪要栏目单元测试（T-ORG-11：查摆问题 / 批评意见 / 整改方向与三会一课分开）。"""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.meeting_service import (
    DEFAULT_MINUTES_SECTIONS,
    ORG_LIFE_MINUTES_SECTIONS,
    extract_minutes,
    minutes_missing,
    minutes_sections,
    validate_minutes,
)


def record(activity_type="organizational_life_meeting", **overrides):
    values = {
        "activity_type": activity_type,
        "minutes": {},
        "held_on": date(2026, 4, 10),
        "host": "合成书记",
        "participants": [{"name": "合成党员", "attended": True}],
        "transcript": "查摆问题：班子学习安排不够固定。",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_organizational_life_uses_its_own_sections():
    assert minutes_sections("organizational_life_meeting") == ORG_LIFE_MINUTES_SECTIONS
    assert minutes_sections("branch_member_meeting") == DEFAULT_MINUTES_SECTIONS
    # 老记录可能没有 activity_type（中心组学习的单元测试就是这么构造的）：按缺省口径
    assert minutes_sections(None) == DEFAULT_MINUTES_SECTIONS


def test_organizational_life_transcript_extracts_its_three_sections():
    transcript = (
        "查摆问题：学习安排不够固定。\n"
        "批评意见：班子对年轻党员关心不够。\n"
        "整改方向：每季度固定一次集中学习。\n"
        "学习要点：这句属于三会一课栏目，组织生活会不提取。\n"
    )
    minutes = extract_minutes(transcript, ORG_LIFE_MINUTES_SECTIONS)
    assert [note["text"] for note in minutes["problems"]] == ["学习安排不够固定。"]
    assert [note["text"] for note in minutes["criticisms"]] == ["班子对年轻党员关心不够。"]
    assert [note["text"] for note in minutes["rectifications"]] == ["每季度固定一次集中学习。"]
    assert "learning_points" not in minutes
    validate_minutes(transcript, minutes)


def test_default_extraction_ignores_organizational_life_labels():
    transcript = "查摆问题：不该进三会一课纪要。\n学习要点：应当提取。\n"
    minutes = extract_minutes(transcript)
    assert [note["text"] for note in minutes["learning_points"]] == ["应当提取。"]
    assert "problems" not in minutes


def test_organizational_life_missing_names_its_own_sections():
    assert minutes_missing(record(minutes={})) == [
        "查摆问题待补",
        "批评意见待补",
        "整改方向待补",
    ]


def test_organizational_life_missing_uses_meeting_wording_not_study_wording():
    # 组织生活会是"会议"，不是"学习"：原先共用文案把它也叫"参学记录"
    missing = minutes_missing(record(held_on=None, participants=[]))
    assert "实际召开日期待补" in missing
    assert "参会人员待补" in missing
    assert "实际学习日期待补" not in missing
    assert "参学记录待补" not in missing


def test_study_records_keep_study_wording():
    missing = minutes_missing(record(activity_type="center_group", held_on=None, participants=[]))
    assert "实际学习日期待补" in missing
    assert "参学记录待补" in missing


def test_three_meeting_sections_do_not_satisfy_an_organizational_life():
    minutes = extract_minutes("学习要点：学习。\n讨论共识：共识。\n工作要求：要求。\n")
    assert minutes_missing(record(minutes=minutes)) == [
        "查摆问题待补",
        "批评意见待补",
        "整改方向待补",
    ]


def test_item_cap_still_applies_to_the_new_sections():
    transcript = "".join(f"批评意见：第 {index} 条意见。\n" for index in range(61))
    with pytest.raises(HTTPException):
        extract_minutes(transcript, ORG_LIFE_MINUTES_SECTIONS)
