"""会议文书模板：按会议类型分开生成，未知决议留给人工补充。"""

from datetime import date
from types import SimpleNamespace

from app.services.activity_service import (
    _agenda_text,
    _balanced_topics,
    _meeting_notice,
    _record_template,
)


def meeting(activity_type: str, title: str = "加强党性修养") -> SimpleNamespace:
    return SimpleNamespace(
        activity_type=activity_type,
        title=title,
        scheduled_on=date(2026, 11, 20),
        host="张书记",
        participants=[
            {"participant_id": "p1", "name": "张三", "attended": True},
            {"participant_id": "p2", "name": "李四", "attended": False},
        ],
        context={
            "location": "A301",
            "meeting_time": "14:30",
            "recorder": "王组织员",
        },
    )


def source(title: str = "把加强党性修养作为终身课题") -> dict:
    return {
        "doc_id": "doc-1",
        "title": title,
        "issuer": "共产党员网",
        "source_url": "https://www.12371.cn/2026/11/02/ARTI1.shtml",
        "effective_date": "2026-11-02",
    }


def test_committee_agenda_is_an_issue_list_not_a_material_list():
    record = meeting("branch_committee_meeting")
    agenda, items = _agenda_text(record, [source()])
    assert "会议议题（草案）" in agenda
    assert "传达学习《把加强党性修养作为终身课题》" in agenda
    assert "研究贯彻落实措施" in agenda
    assert "会议议程（草稿）" not in agenda
    assert [item["type"] for item in items] == ["学习类", "研究类", "待定"]


def test_lecture_uses_its_own_agenda_template():
    agenda, items = _agenda_text(meeting("party_lecture"), [source()])
    assert "党课安排（草案）" in agenda
    assert "党课主题：加强党性修养" in agenda
    assert "讨论题" in agenda
    assert "会议议题（草案）" not in agenda
    assert items[0]["type"] == "党课"


def test_organization_life_keeps_its_own_process():
    agenda, _ = _agenda_text(meeting("organizational_life_meeting"), [])
    assert "查摆问题" in agenda
    assert "批评和自我批评" in agenda
    assert "整改方向" in agenda
    assert "讨论安排" not in agenda


def test_record_template_contains_placeholders_and_never_invents_a_decision():
    record = meeting("branch_member_meeting")
    template = _record_template(record, [source()])
    assert "会议记录（模板，请按实际填写）" in template
    assert "应到人数：2；实到人数：1；请假人员：李四" in template
    assert "会议决议：" in template
    assert "请人工补充具体事项" in template
    assert "会议同意" not in template


def test_notice_includes_formal_meeting_fields():
    notice = _meeting_notice(meeting("branch_committee_meeting"))
    assert "会议通知（草案）" in notice
    assert "会议时间：2026-11-20 14:30" in notice
    assert "会议地点：A301" in notice
    assert "记录人：王组织员" in notice
    assert "供支部委员会研究确定" in notice


def test_topic_selection_prefers_different_meeting_types():
    groups = [
        {"activity_type": "party_lecture", "sort": 5},
        {"activity_type": "party_lecture", "sort": 4},
        {"activity_type": "party_lecture", "sort": 3},
        {"activity_type": "branch_committee_meeting", "sort": 2},
    ]
    selected = _balanced_topics(groups)
    assert [item["activity_type"] for item in selected] == [
        "party_lecture",
        "party_lecture",
        "branch_committee_meeting",
    ]
