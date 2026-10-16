"""评分 / 选优 / 结论类输出的统一决策边界标注（T-SEC-13）。

SEC-10 与 FR-MEM-10 要求：涉及评分、选优、党员发展结论的辅助输出必须**强制标注**
辅助性质、保留可溯源的评价依据，且**未经人工终审不得流转**。标注是合规项而不是
装饰：各模块各写一套话术时，新增出口极易漏标或口径漂移，因此文案只保留这一处来源，
并由 tests 强制覆盖所有相关出口（见 tests/unit/test_decision_boundary.py）。
"""

from __future__ import annotations

#: 统一标注的公共前缀：任何评分 / 选优 / 结论 / 问答出口都必须以它开头
ASSISTED_REFERENCE_PREFIX = "辅助参考，以正式文件与组织决定为准"

#: 所有评分 / 选优 / 结论类出口共用的统一标注（SEC-10 / FR-MEM-10）
ASSISTED_REFERENCE_NOTE = (
    f"{ASSISTED_REFERENCE_PREFIX}；不构成组织认定或选拔结论，未经人工终审不得流转"
)

#: 知识问答标注（FR-QA-11：标注“辅助参考，以正式文件为准”）
QA_DISCLAIMER = f"{ASSISTED_REFERENCE_PREFIX}；回答内容不构成组织认定"

#: 阶段流转专用补充（FR-MEM-10：AI 输出强制标注辅助性质，不自动决断）
STAGE_TRANSITION_NOTE = (
    f"{ASSISTED_REFERENCE_NOTE}；阶段流转仅可通过人工接口，由具备权限的组织人员依规操作"
)


def evidence_note(location: str) -> str:
    """依据保留位置说明：让使用者知道去哪里逐条核对，而不是只看到一句免责。"""
    return f"评价依据保留在{location}，可逐条溯源；不以模型自动结论替代组织决定"


def pending_review_message(what: str, state: str, next_step: str) -> str:
    """未经人工终审却要流转时的可执行提示（409 用）。"""
    return f"{what}尚未通过人工终审（当前状态：{state}），按决策边界不得流转；{next_step}"
