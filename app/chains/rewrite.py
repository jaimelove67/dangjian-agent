"""追问改写

框架文档 5.8：追问先改写为独立问题再检索，提升召回质量。
改写通过注入的 LLM 调用实现（模型接入由开发者B提供），本模块只负责提示词组织
与结果清洗，因此可脱离模型单测。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional, Sequence

from app.prompts.qa import REWRITE_PROMPT

# LLM 调用签名：给定提示词，返回生成文本
LLMCall = Callable[[str], Awaitable[str]]


async def rewrite_question(
    question: str,
    history: Optional[Sequence[object]] = None,
    *,
    llm_call: Optional[LLMCall] = None,
    max_history_turns: int = 3,
) -> str:
    """将追问改写为可独立检索的问题

    Args:
        question: 用户当前问题
        history: 会话历史（``QATurn`` 序列）
        llm_call: 异步 LLM 调用；为空时不改写
        max_history_turns: 参与改写的历史轮次上限

    Returns:
        独立问题；无历史或无 LLM 时返回原问题
    """
    current = (question or "").strip()
    if not current:
        raise ValueError("问题不能为空")

    turns = list(history or [])[-max_history_turns:]
    if not turns or llm_call is None:
        return current

    history_text = "\n".join(
        f"问：{getattr(turn, 'question', '')}\n答：{getattr(turn, 'answer', '')}"
        for turn in turns
    )
    prompt = REWRITE_PROMPT.format(history=history_text, question=current)
    rewritten = (await llm_call(prompt) or "").strip()
    return rewritten or current
