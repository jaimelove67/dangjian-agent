"""文档切分策略测试（框架文档 5.3）"""
import pytest

from app.rag.splitter import ChapterArticleSplitter


class TestStructureSplit:
    def test_splits_by_article(self):
        text = (
            "第一条 为了规范发展党员工作。\n"
            "第二条 发展党员必须坚持党章规定的党员标准。\n"
            "第三条 入党积极分子培养期一般不少于一年。"
        )
        chunks = ChapterArticleSplitter().split(text)

        assert len(chunks) == 3
        assert [c.article for c in chunks] == ["第一条", "第二条", "第三条"]
        assert [c.sequence for c in chunks] == [0, 1, 2]
        assert "培养期" in chunks[2].content

    def test_preface_without_article_kept(self):
        chunks = ChapterArticleSplitter().split("前言说明。\n第一条 正文内容。")

        assert len(chunks) == 2
        assert chunks[0].article is None
        assert "前言" in chunks[0].content
        assert chunks[1].article == "第一条"

    def test_no_structure_single_chunk(self):
        chunks = ChapterArticleSplitter().split("没有条款结构的普通文本。")
        assert len(chunks) == 1
        assert chunks[0].article is None

    def test_chapter_fallback(self):
        chunks = ChapterArticleSplitter().split(
            "第一章 总则\n内容甲。\n第二章 组织\n内容乙。"
        )
        assert len(chunks) == 2
        assert chunks[0].article == "第一章"

    def test_empty_returns_empty(self):
        assert ChapterArticleSplitter().split("") == []
        assert ChapterArticleSplitter().split("   ") == []


class TestSecondarySplit:
    def test_long_article_split_with_overlap(self):
        body = "。".join(["这是一句测试文本"] * 40) + "。"
        splitter = ChapterArticleSplitter(max_chunk_size=100, overlap=10)
        chunks = splitter.split("第一条 " + body)

        assert len(chunks) > 1
        assert all(len(c.content) <= 100 for c in chunks)
        assert chunks[0].article == "第一条"
        assert chunks[1].article == "第一条-2"

    def test_secondary_split_disabled(self):
        body = "。".join(["文本"] * 200) + "。"
        splitter = ChapterArticleSplitter(
            max_chunk_size=50, overlap=10, enable_secondary_split=False
        )
        chunks = splitter.split("第一条 " + body)

        assert len(chunks) == 1
        assert len(chunks[0].content) > 50

    @pytest.mark.parametrize(
        "kwargs",
        [{"max_chunk_size": 0}, {"max_chunk_size": 100, "overlap": 100}, {"overlap": -1}],
    )
    def test_invalid_config_rejected(self, kwargs):
        with pytest.raises(ValueError):
            ChapterArticleSplitter(**kwargs)
