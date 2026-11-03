"""政治审查核对口径。

依据《发展党员工作实务解读（2025.4）》P32：政审内容四方面、政审不合格八种情形。
系统只保存组织已经核对的事实和结论，不根据勾选项自动作出合格 / 不合格结论。
"""

from __future__ import annotations

POLITICAL_REVIEW_ASPECTS: dict[str, str] = {
    "party_line": "对党的路线方针政策的态度",
    "political_history": "政治历史和重大政治斗争中的表现",
    "law_and_ethics": "遵纪守法和遵守社会公德情况",
    "relatives": "直系亲属和主要社会关系的政治情况",
}

POLITICAL_REVIEW_NEGATIVE_CATEGORIES: dict[str, str] = {
    "religion": "不信仰马克思主义 / 信仰宗教",
    "unsteady": "重大政治斗争中立场不坚定",
    "violation": "涉嫌违纪违法",
    "mass_line": "群众观念淡薄，不起带头作用",
    "morality": "道德品质、生活作风问题",
    "dishonesty": "对党不忠诚老实、政审弄虚作假或不配合",
    "relatives_risk": "直系亲属和主要社会关系有危害国家安全、民族分裂、暴恐、宗教极端、邪教、严重违法违纪行为而本人不能划清界限",
    "other": "其他情形",
}
