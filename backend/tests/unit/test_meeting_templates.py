"""会议文书模板：章节顺序、标题和说明固定规则。"""

from app.services.meeting_template_service import (
    default_schema,
    normalize_schema,
)


def test_template_preserves_custom_order_and_titles():
    schema = normalize_schema(
        {
            "sections": [
                {"key": "record", "title": "会议纪要", "enabled": True},
                {"key": "notice", "title": "会议通知", "enabled": False},
            ],
            "labels": {"host": "主持人姓名"},
        }
    )
    assert [item["key"] for item in schema["sections"][:2]] == ["record", "notice"]
    assert schema["sections"][0]["title"] == "会议纪要"
    assert schema["sections"][1]["enabled"] is False
    assert schema["labels"]["host"] == "主持人姓名"


def test_footer_is_always_last_and_cannot_be_hidden():
    schema = normalize_schema(
        {
            "sections": [
                {"key": "footer", "title": "说明", "enabled": False},
                {"key": "record", "title": "会议记录", "enabled": True},
            ]
        }
    )
    assert schema["sections"][-1]["key"] == "footer"
    assert schema["sections"][-1]["enabled"] is True


def test_missing_sections_fall_back_to_defaults():
    schema = normalize_schema({"sections": [], "labels": {}})
    assert len(schema["sections"]) == 6
    assert schema == default_schema()
