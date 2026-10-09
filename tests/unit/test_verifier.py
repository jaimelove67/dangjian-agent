"""引用核验模块测试（框架文档 5.7）"""
from datetime import date

from app.rag.verifier import CitationVerifier, RetrievedChunk


def _chunk(index: int = 1, **overrides) -> RetrievedChunk:
    base = {
        "index": index,
        "doc_id": f"d{index}",
        "doc_name": f"文件{index}",
        "content": "第一条 内容。",
        "article": "第一条",
        "status": "effective",
    }
    base.update(overrides)
    return RetrievedChunk(**base)


class TestCitationNumberValidity:
    def test_valid_index_kept(self):
        chunks = [_chunk(1, content="第一条 培养期一般不少于一年。")]
        result = CitationVerifier().verify("根据第一条，培养期不少于一年[1]。", chunks)
        assert result.valid is True
        assert len(result.citations) == 1
        assert result.citations[0].index == 1

    def test_invalid_index_removed_with_warning(self):
        result = CitationVerifier().verify("结论[9]", [_chunk(1)])
        assert "[9]" not in result.answer
        assert any("引用[9]不存在" in w for w in result.warnings)
        assert result.valid is False
        assert result.citations == []

    def test_short_answer_without_citation_ok(self):
        result = CitationVerifier().verify("简短回答。", [])
        assert result.warnings == []
        assert result.valid is True

    def test_long_answer_without_citation_warns(self):
        long_answer = "这是一段较长的回答内容，用于触发引用完整性检查。" * 5
        result = CitationVerifier().verify(long_answer, [])
        assert any("未标注任何来源" in w for w in result.warnings)


class TestArticleTruthfulness:
    def test_article_present_no_warning(self):
        chunk = _chunk(1, article="第十四条", content="第十四条 培养期一般不少于一年。")
        result = CitationVerifier().verify("根据第十四条，培养期不少于一年[1]。", [chunk])
        assert not any("条款" in w for w in result.warnings)

    def test_article_absent_warns(self):
        chunk = _chunk(1, article="第一条", content="第一条 内容。")
        result = CitationVerifier().verify("根据第十四条，应如此办理[1]。", [chunk])
        assert any("第十四条" in w and "不存在" in w for w in result.warnings)


class TestTimeliness:
    def test_abolished_warns(self):
        result = CitationVerifier().verify("依据[1]", [_chunk(1, status="abolished")])
        assert any("已废止" in w for w in result.warnings)

    def test_expired_date_warns(self):
        result = CitationVerifier().verify("依据[1]", [_chunk(1, expiration_date=date(2020, 1, 1))])
        assert any("失效" in w for w in result.warnings)

    def test_expiring_soon_warns(self):
        verifier = CitationVerifier(today=date(2026, 1, 1))
        chunk = _chunk(1, expiration_date=date(2026, 1, 15))
        result = verifier.verify("依据[1]", [chunk])
        assert any("即将" in w for w in result.warnings)

    def test_far_expiration_no_warning(self):
        verifier = CitationVerifier(today=date(2026, 1, 1))
        chunk = _chunk(1, expiration_date=date(2030, 1, 1))
        result = verifier.verify("依据[1]", [chunk])
        assert not any("失效" in w for w in result.warnings)


class TestCitationList:
    def test_citation_fields_mapped(self):
        chunk = _chunk(
            2,
            doc_name="发展党员工作细则",
            article="第三条",
            doc_number="中办发〔2014〕33号",
            issuer="中共中央办公厅",
            effective_date=date(2014, 6, 10),
        )
        result = CitationVerifier().verify("内容[2]", [chunk])
        citation = result.citations[0]
        assert citation.doc_name == "发展党员工作细则"
        assert citation.article == "第三条"
        assert citation.doc_number == "中办发〔2014〕33号"
        assert citation.issuer == "中共中央办公厅"
        assert citation.effective_date == date(2014, 6, 10)
