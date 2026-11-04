"""外部党建资料白名单解析与摘要提取。"""

from datetime import datetime

from app.services.external_update_service import (
    _links,
    _published_date,
    _summary_from_page,
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
