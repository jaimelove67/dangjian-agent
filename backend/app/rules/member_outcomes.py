"""预备党员转正结果的情形分类。

分类依据《发展党员工作实务解读（2025.4）》P61-P62：
延长预备期四类、取消预备党员资格九种。分类只用于登记组织已经形成的情形，
系统不据分类自动作出延长、取消或转正决定。
"""

from __future__ import annotations

PROBATION_EXTENSION_REASONS: dict[str, str] = {
    "weak_progress": "入党时有某些缺点，预备期转变不明显，不完全具备条件但愿意继续接受教育考察",
    "relaxed_requirements": "入党时基本具备条件，入党后放松要求出现较严重缺点，经指出愿意改正",
    "general_error": "入党后犯一般性错误，检查认识深刻、下决心改正",
    "political_quality": "一般表现尚好但政治素质较差，组织认为应继续教育考察",
}

PROBATION_DISQUALIFICATION_REASONS: dict[str, str] = {
    "ideological_doubt": "理想信念动摇，对党的理论路线方针政策产生怀疑不能认真贯彻",
    "violate_policy": "违反党和国家政策法规或不执行党的决议，情节严重",
    "criminal": "触犯刑律或违反治安管理处罚法受刑事处罚、管制、拘役",
    "no_progress": "预备期不履行党员义务或思想落后，经教育帮助无继续进步要求",
    "refuse_correction": "出现较严重缺点或犯一般错误，经批评教育拒绝检查改正",
    "serious_error": "预备期犯严重错误或发现隐瞒入党前严重错误",
    "no_improvement_after_extension": "延长一次预备期后仍无明显进步",
    "withdraw": "因信念动摇、不愿接受党纪约束等提出退党、放弃转正",
    "other": "其他组织认为应当取消的情形",
}

PROBATION_OUTCOME_REASONS: dict[str, dict[str, str]] = {
    "extended": PROBATION_EXTENSION_REASONS,
    "disqualified": PROBATION_DISQUALIFICATION_REASONS,
}
