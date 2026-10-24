"""入库元数据识别的边界测试：只抄不猜，模型给的脏值一律丢弃。"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

from app.services.knowledge_meta_service import (
    _clean_tags,
    _parse_date,
    _parse_json,
    extract_text,
    normalize_suggestion,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-01", "2026-09-01"),
        ("2026年9月1日", "2026-09-01"),
        ("2026/9/1", "2026-09-01"),
        ("2026.9.1", "2026-09-01"),
        ("自2026年9月1日起施行", "2026-09-01"),
        ("", None),
        ("未注明", None),
        ("2026-13-40", None),  # 非法日期不能"修正"成别的日子
        (None, None),
    ],
)
def test_parse_date(raw, expected):
    assert _parse_date(raw) == expected


def test_normalize_drops_invalid_enum_and_cleans_text():
    result = normalize_suggestion(
        {
            "title": "《关于加强政治审查的办法》",
            "doc_number": " 校党发〔2026〕5号 ",
            "issuer": "中共某大学委员会",
            "level": "SCHOOL",  # 大写应被接受（统一小写）
            "effective_date": "2026年9月1日",
            "tags": "发展党员，政治审查、发展党员",  # 字符串 + 重复
            "summary": "说明" * 100,  # 超长需截断
        }
    )
    assert result["title"] == "关于加强政治审查的办法"
    assert result["doc_number"] == "校党发〔2026〕5号"
    assert result["level"] == "school"
    assert result["effective_date"] == "2026-09-01"
    assert result["tags"] == ["发展党员", "政治审查"]
    assert len(result["summary"]) <= 120


def test_normalize_rejects_unknown_level():
    assert normalize_suggestion({"level": "国家级"})["level"] == ""
    assert normalize_suggestion({"level": ""})["level"] == ""


def test_clean_tags_limits_count_and_length():
    tags = _clean_tags(["发展党员", "政治审查", "x" * 40, "标签3", "标签4", "标签5", "标签6"])
    assert len(tags) <= 5
    assert all(len(tag) <= 16 for tag in tags)


def test_parse_json_tolerates_code_fences_and_chatter():
    assert _parse_json('```json\n{"title": "A"}\n```') == {"title": "A"}
    assert _parse_json('好的，结果如下：{"title": "B"} 以上。') == {"title": "B"}
    with pytest.raises(ValueError):
        _parse_json("完全不是 JSON")


def test_extract_text_rejects_empty_and_unsupported():
    with pytest.raises(HTTPException) as unsupported:
        extract_text(b"PK\x03\x04", file_name="名单.xlsx")
    assert unsupported.value.status_code == 415

    with pytest.raises(HTTPException) as empty:
        extract_text("   \n\n ".encode(), file_name="空白.txt")
    assert empty.value.status_code == 422
    assert empty.value.detail["code"] == "EMPTY_TEXT"


def test_extract_text_reads_docx():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("第一条 为规范发展党员工作，制定本办法。")
    buffer = io.BytesIO()
    document.save(buffer)

    text, total = extract_text(buffer.getvalue(), file_name="办法.docx")
    assert "发展党员" in text
    assert total == len(text)
