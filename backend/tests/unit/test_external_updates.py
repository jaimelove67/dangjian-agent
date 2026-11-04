"""外部党建资料白名单解析与摘要提取。"""

from datetime import datetime

from app.services.activity_service import _topic_for
from app.services.external_update_service import (
    DEFAULT_FOCUS_TOPICS,
    _links,
    _published_date,
    _summary_from_page,
    matches_focus,
    normalize_focus_topics,
)


def test_only_whitelisted_dated_article_links_are_collected():
    page = """
    <a href="/2026/11/03/ARTI1.shtml">中共中央关于进一步加强党的建设的通知</a>
    <a href="https://evil.example/2026/11/03/ARTI2.shtml">外部站点文章标题</a>
    <a href="/2026/11/03/ARTI3.shtml">更多</a>
    """
    rows = _links(page, "https://www.12371.cn/", "12371.cn")
    assert [row["url"] for row in rows] == ["https://www.12371.cn/2026/11/03/ARTI1.shtml"]


def test_publication_date_comes_from_article_url():
    assert _published_date("https://www.12371.cn/2026/11/03/ARTI1.shtml") == datetime(2026, 11, 3)
    assert _published_date("https://www.12371.cn/20261103/ARTI1.shtml") == datetime(2026, 11, 3)
    assert _published_date("https://www.12371.cn/not-dated.shtml") is None


def test_summary_prefers_meta_description_and_strips_markup():
    page = '<meta name="description" content="来源摘要 &amp; 重点内容">' "<p>正文不应优先</p>"
    assert _summary_from_page(page) == "来源摘要 & 重点内容"


def test_topic_rules_map_latest_article_to_meeting_type():
    assert _topic_for("中共中央关于全面从严治党的重要决定")[1] == "party_lecture"
    assert _topic_for("加强基层党组织建设的工作要求")[1] == "branch_committee_meeting"
    assert "学习《" in _topic_for("其他党建资料")[0]
    assert _topic_for("系列节目《思想的力量》")[0] == "学习系列节目《思想的力量》"


def test_focus_topics_are_normalized_and_unknown_tags_are_ignored():
    assert normalize_focus_topics(["发展党员", "不存在的方向", "发展党员"]) == ["发展党员"]
    assert normalize_focus_topics([]) == []
    assert normalize_focus_topics(None) == list(DEFAULT_FOCUS_TOPICS)


def test_focus_matching_uses_title_and_summary_keywords():
    assert matches_focus("加强基层党组织建设", ["基层组织建设"]) is True
    assert matches_focus("学校开展专题学习", ["师德师风"]) is True
    assert matches_focus("学校开展专题学习", ["科技创新"]) is False
    assert matches_focus("任何内容", []) is True
