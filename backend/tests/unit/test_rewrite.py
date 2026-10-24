"""追问改写测试（框架文档 5.8）"""
import pytest

from app.chains.rewrite import rewrite_question
from app.chains.session import QATurn


async def test_no_history_returns_original():
    assert await rewrite_question("培养期多久？") == "培养期多久？"


async def test_no_llm_returns_original():
    history = [QATurn.create("入党积极分子培养期是多久？", "一般不少于一年。")]
    assert await rewrite_question("那预备期呢？", history, llm_call=None) == "那预备期呢？"


async def test_rewrite_uses_llm_with_history():
    captured = {}

    async def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "预备党员的预备期是多久？"

    history = [QATurn.create("入党积极分子培养期是多久？", "一般不少于一年。")]
    result = await rewrite_question("那预备期呢？", history, llm_call=fake_llm)

    assert result == "预备党员的预备期是多久？"
    assert "那预备期呢？" in captured["prompt"]
    assert "入党积极分子培养期是多久？" in captured["prompt"]


async def test_empty_llm_output_falls_back_to_original():
    async def empty_llm(prompt: str) -> str:
        return "   "

    history = [QATurn.create("q", "a")]
    assert await rewrite_question("追问", history, llm_call=empty_llm) == "追问"


async def test_empty_question_raises():
    with pytest.raises(ValueError):
        await rewrite_question("   ")
