"""二级党组织会议审议与专职组织员审核签字的节点口径。

依据《发展党员工作实务解读（2025.4）》：确定发展对象、接收预备党员前的支委会审查、
接收预备党员支部大会、预备党员转正支部大会等关键节点，需要经二级党组织会议审议，
并由专职组织员审核把关、签字。本模块只定义节点和最低登记阶段，不代替组织程序。
"""

from __future__ import annotations

from app.rules.member_stages import MemberStage

SECONDARY_REVIEW_NODES: dict[str, dict[str, str | MemberStage]] = {
    "candidate_determination": {
        "label": "确定发展对象",
        "min_stage": MemberStage.ACTIVIST,
    },
    "pre_reception": {
        "label": "接收预备党员前支委会审查",
        "min_stage": MemberStage.CANDIDATE,
    },
    "reception": {
        "label": "接收预备党员支部大会",
        "min_stage": MemberStage.CANDIDATE,
    },
    "conversion": {
        "label": "预备党员转正支部大会",
        "min_stage": MemberStage.PROBATIONARY,
    },
}
