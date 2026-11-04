"""发展党员档案卷内目录（38 项材料）。

依据《湖南科技职业学院发展党员综合资料（最终版 20241128）》
（中共湖南科技职业学院委员会组织人事部编印，2024-12）整理，材料编号与手册一致。

本模块只做三件事：定义清单、标注每项对应哪类归档材料 / 哪类已登记程序、按阶段分组。
**不做完整度判定**——缺项是否影响阶段流转由服务层按学校口径决定，默认只提示、不阻断。

口径说明：
- ``section`` 是手册的五个阶段，与党员发展阶段枚举不是一一对应：
  "预备党员的接收"发生在发展对象阶段，因此仍映射到 ``candidate``；
- ``material_types`` 命中 ``member_materials.material_type``（12 类归档材料，见
  ``services/member_archive_service.ARCHIVE_MATERIAL_TYPES``）；
- ``procedure_kinds`` 命中 ``member_procedures.kind``（已登记程序节点）；
- 两者都为空的项属于"只能人工确认已归档"（内部决议、自传、照片、请示等），
  系统不假装能识别其内容。

**一律按 ``code`` 索引，不要按名称**：材料 13（发展对象）与材料 33（预备党员）在手册中
同名"党内外群众意见座谈会记录"，按名称查找会串阶段。
"""

from __future__ import annotations

from collections.abc import Collection
from typing import NamedTuple

from app.rules.member_stages import MemberStage

#: 手册五个阶段的目录键
SECTION_APPLICATION = "application"
SECTION_ACTIVIST = "activist"
SECTION_CANDIDATE = "candidate"
SECTION_RECEPTION = "reception"
SECTION_PROBATIONARY = "probationary"

SECTION_LABELS: dict[str, str] = {
    SECTION_APPLICATION: "一、申请入党",
    SECTION_ACTIVIST: "二、入党积极分子的确定和培养教育",
    SECTION_CANDIDATE: "三、党员发展对象的确定和考察",
    SECTION_RECEPTION: "四、预备党员的接收",
    SECTION_PROBATIONARY: "五、预备党员的教育考察和转正",
}

SECTION_ORDER: tuple[str, ...] = (
    SECTION_APPLICATION,
    SECTION_ACTIVIST,
    SECTION_CANDIDATE,
    SECTION_RECEPTION,
    SECTION_PROBATIONARY,
)

#: 目录阶段 → 党员当前阶段（"接收"阶段人仍在发展对象阶段）
SECTION_MEMBER_STAGE: dict[str, MemberStage] = {
    SECTION_APPLICATION: MemberStage.APPLICANT,
    SECTION_ACTIVIST: MemberStage.ACTIVIST,
    SECTION_CANDIDATE: MemberStage.CANDIDATE,
    SECTION_RECEPTION: MemberStage.CANDIDATE,
    SECTION_PROBATIONARY: MemberStage.PROBATIONARY,
}

#: 进入哪些党员阶段后，该目录阶段才开始要求材料。
#: 未走到的阶段不报缺失——否则入党申请人一进来就会被列出 36 项"缺材料"。
SECTION_ACTIVE_STAGES: dict[str, tuple[MemberStage, ...]] = {
    SECTION_APPLICATION: (
        MemberStage.APPLICANT,
        MemberStage.ACTIVIST,
        MemberStage.CANDIDATE,
        MemberStage.PROBATIONARY,
        MemberStage.MEMBER,
    ),
    SECTION_ACTIVIST: (
        MemberStage.ACTIVIST,
        MemberStage.CANDIDATE,
        MemberStage.PROBATIONARY,
        MemberStage.MEMBER,
    ),
    SECTION_CANDIDATE: (
        MemberStage.CANDIDATE,
        MemberStage.PROBATIONARY,
        MemberStage.MEMBER,
    ),
    SECTION_RECEPTION: (MemberStage.PROBATIONARY, MemberStage.MEMBER),
    SECTION_PROBATIONARY: (MemberStage.PROBATIONARY, MemberStage.MEMBER),
}

#: 单项核对状态。archived 表示系统能对上材料或程序；unconfirmed 表示只能人工确认。
STATUS_ARCHIVED = "archived"
STATUS_MISSING = "missing"
STATUS_UNCONFIRMED = "unconfirmed"
STATUS_OPTIONAL = "optional"
STATUS_NOT_APPLICABLE = "not_applicable"

STATUS_LABELS: dict[str, str] = {
    STATUS_ARCHIVED: "已归档",
    STATUS_MISSING: "缺材料",
    STATUS_UNCONFIRMED: "待人工确认",
    STATUS_OPTIONAL: "按需",
    STATUS_NOT_APPLICABLE: "阶段未到",
}

#: 载体形式：粘贴页（原件/证书/照片）、签署页（可填表单与记录）、占位页（表体另附）
CARRIER_PASTE = "paste"
CARRIER_SIGN = "sign"
CARRIER_PLACEHOLDER = "placeholder"

CARRIER_LABELS: dict[str, str] = {
    CARRIER_PASTE: "粘贴页",
    CARRIER_SIGN: "签署页",
    CARRIER_PLACEHOLDER: "占位页",
}


class ArchiveItem(NamedTuple):
    """卷内目录中的一项材料"""

    code: str  # 目录编号 m01..m38
    no: int  # 手册材料编号 1..38
    name: str  # 材料名称，以手册正文表单名为准
    section: str  # 所属阶段键
    carrier: str  # 载体形式
    required: bool  # 该阶段是否必备
    material_types: tuple[str, ...]  # 对应归档材料类型
    procedure_kinds: tuple[str, ...]  # 对应已登记程序节点
    page: int  # 手册页码（PDF 页码 = 手册页码 + 4）
    note: str = ""

    @property
    def manual_only(self) -> bool:
        """既无归档类型也无程序节点，只能人工确认是否已归档。"""
        return not self.material_types and not self.procedure_kinds


ARCHIVE_CHECKLIST: tuple[ArchiveItem, ...] = (
    ArchiveItem(
        "m01",
        1,
        "入党申请书",
        SECTION_APPLICATION,
        CARRIER_PASTE,
        True,
        ("入党申请书",),
        (),
        3,
        "一般要求书写、本人签名；支部复印一份留存",
    ),
    ArchiveItem(
        "m02",
        2,
        "党支部派专人同入党申请人谈话记录",
        SECTION_APPLICATION,
        CARRIER_SIGN,
        True,
        ("党组织谈话记录",),
        ("contact",),
        4,
        "收到入党申请书后 1 个月内谈话，注明时间、地点、内容",
    ),
    ArchiveItem(
        "m03",
        3,
        "优秀大学生入党团组织推优（党员推荐）表",
        SECTION_ACTIVIST,
        CARRIER_PASTE,
        True,
        (),
        (),
        7,
        "团组织推优与党员推荐二选一；推优资格按年满 18 周岁、入团满 1 年核验（member_league）",
    ),
    ArchiveItem(
        "m04",
        4,
        "确定入党积极分子意见",
        SECTION_ACTIVIST,
        CARRIER_SIGN,
        True,
        (),
        (),
        8,
        "确定 1–2 名培养联系人",
    ),
    ArchiveItem(
        "m05",
        5,
        "党支部委员会讨论确定入党积极分子记录",
        SECTION_ACTIVIST,
        CARRIER_SIGN,
        True,
        (),
        (),
        9,
        "无记名投票表决，记载赞成/不赞成/弃权票数",
    ),
    ArchiveItem(
        "m06",
        6,
        "确定入党积极分子公示",
        SECTION_ACTIVIST,
        CARRIER_SIGN,
        True,
        (),
        ("publicity",),
        11,
    ),
    ArchiveItem(
        "m07",
        7,
        "确定入党积极分子基层党委备案意见",
        SECTION_ACTIVIST,
        CARRIER_SIGN,
        True,
        (),
        ("higher_record",),
        12,
        "党总支审议、基层党委备案两级",
    ),
    ArchiveItem(
        "m08",
        8,
        "入党积极分子培养考察登记表",
        SECTION_ACTIVIST,
        CARRIER_SIGN,
        True,
        ("培养考察记录",),
        (),
        13,
        "跨 5 页：培养教育情况 + 4 个季度考察 + 半年考察评价",
    ),
    ArchiveItem("m09", 9, "入党积极分子思想汇报", SECTION_ACTIVIST, CARRIER_PASTE, True, ("思想汇报",), (), 18),
    ArchiveItem(
        "m10",
        10,
        "入党积极分子培训班结业证书",
        SECTION_ACTIVIST,
        CARRIER_PASTE,
        True,
        ("党课培训证明",),
        (),
        19,
    ),
    ArchiveItem("m11", 11, "自传", SECTION_CANDIDATE, CARRIER_PASTE, True, (), (), 23),
    ArchiveItem(
        "m12",
        12,
        "确定党员发展对象人选意见",
        SECTION_CANDIDATE,
        CARRIER_SIGN,
        True,
        (),
        (),
        24,
        "须为入党积极分子满 1 年；无党小组可不填党小组意见",
    ),
    ArchiveItem(
        "m13",
        13,
        "党内外群众意见座谈会记录",
        SECTION_CANDIDATE,
        CARRIER_PASTE,
        True,
        ("群众评议材料",),
        (),
        25,
        "民主推荐或谈话推荐，记录粘贴",
    ),
    ArchiveItem(
        "m14",
        14,
        "党支部委员会讨论确定党员发展对象人选记录",
        SECTION_CANDIDATE,
        CARRIER_SIGN,
        True,
        (),
        (),
        26,
    ),
    ArchiveItem(
        "m15",
        15,
        "确定为党员发展对象公示情况",
        SECTION_CANDIDATE,
        CARRIER_SIGN,
        True,
        (),
        ("publicity",),
        28,
        "公示不少于 5 个工作日（支部讨论后、备案前）；同步确定 2 名入党介绍人",
    ),
    ArchiveItem(
        "m16",
        16,
        "确定党员发展对象基层党委备案意见",
        SECTION_CANDIDATE,
        CARRIER_SIGN,
        True,
        (),
        ("higher_record",),
        29,
    ),
    ArchiveItem(
        "m17",
        17,
        "函调材料",
        SECTION_CANDIDATE,
        CARRIER_PASTE,
        False,
        ("政治审查材料",),
        (),
        30,
        "按需形成；流动人员另需户籍地、居住地基层党组织意见",
    ),
    ArchiveItem(
        "m18",
        18,
        "政治审查情况报告",
        SECTION_CANDIDATE,
        CARRIER_PASTE,
        True,
        ("政治审查材料",),
        (),
        31,
        "未经政治审查或政治审查不合格不能发展入党",
    ),
    ArchiveItem(
        "m19",
        19,
        "党员发展对象培训班学员登记表",
        SECTION_CANDIDATE,
        CARRIER_SIGN,
        True,
        ("党课培训证明",),
        (),
        32,
        "一式两份：一份入学生档案、一份学院留存",
    ),
    ArchiveItem(
        "m20",
        20,
        "党员发展对象培训班结业证书",
        SECTION_CANDIDATE,
        CARRIER_PASTE,
        True,
        ("党课培训证明",),
        (),
        33,
    ),
    ArchiveItem(
        "m21",
        21,
        "支委会审查意见",
        SECTION_RECEPTION,
        CARRIER_PASTE,
        True,
        (),
        ("branch_committee_review",),
        37,
        "手册目录作“党支部审查意见”，说明页作“支委会审查意见”，同一材料",
    ),
    ArchiveItem(
        "m22",
        22,
        "基层党委预审意见",
        SECTION_RECEPTION,
        CARRIER_SIGN,
        True,
        (),
        ("upper_pre_review",),
        38,
        "预审合格后发放《入党志愿书》并登记编号；原件复印盖章留存",
    ),
    ArchiveItem(
        "m23",
        23,
        "接收预备党员公示情况",
        SECTION_RECEPTION,
        CARRIER_SIGN,
        True,
        (),
        ("publicity",),
        39,
        "公示不少于 5 个工作日（预审后、支部大会前）",
    ),
    ArchiveItem(
        "m24",
        24,
        "《中国共产党入党志愿书》",
        SECTION_RECEPTION,
        CARRIER_PLACEHOLDER,
        True,
        (),
        ("application_form",),
        40,
        "正式文件单独印制，本资料仅留注记页；填写规范另按 19 项核对清单",
    ),
    ArchiveItem(
        "m25",
        25,
        "党支部大会讨论接收预备党员会议记录",
        SECTION_RECEPTION,
        CARRIER_SIGN,
        True,
        (),
        ("branch_vote",),
        41,
        "到会人数须超应到会有表决权人数半数；赞成须超应到会有表决权正式党员半数",
    ),
    ArchiveItem(
        "m26",
        26,
        "对预备党员进行备案的报告",
        SECTION_RECEPTION,
        CARRIER_PASTE,
        True,
        (),
        ("higher_record",),
        43,
    ),
    ArchiveItem(
        "m27",
        27,
        "基层党委组织部备案意见",
        SECTION_RECEPTION,
        CARRIER_SIGN,
        True,
        (),
        ("higher_record",),
        44,
        "手册目录作“基层党委备案意见”",
    ),
    ArchiveItem(
        "m28",
        28,
        "预备党员参加入党宣誓情况",
        SECTION_PROBATIONARY,
        CARRIER_SIGN,
        True,
        (),
        (),
        48,
        "可粘贴宣誓照片",
    ),
    ArchiveItem(
        "m29",
        29,
        "预备党员考察表",
        SECTION_PROBATIONARY,
        CARRIER_PLACEHOLDER,
        True,
        ("预备期考察记录",),
        (),
        49,
        "手册中仅标题与空白框，表体须另附；每半年至少谈话、汇报各一次",
    ),
    ArchiveItem(
        "m30",
        30,
        "预备党员思想汇报",
        SECTION_PROBATIONARY,
        CARRIER_PASTE,
        True,
        ("思想汇报",),
        (),
        50,
        "预备党员每半年至少书面汇报一次",
    ),
    ArchiveItem(
        "m31",
        31,
        "预备党员培训班结业证书",
        SECTION_PROBATIONARY,
        CARRIER_PASTE,
        True,
        ("党课培训证明",),
        (),
        51,
    ),
    ArchiveItem(
        "m32",
        32,
        "转正申请书",
        SECTION_PROBATIONARY,
        CARRIER_PASTE,
        True,
        ("转正申请书",),
        (),
        52,
        "预备期满前 1–2 周本人书面提出；支部复印留存",
    ),
    ArchiveItem(
        "m33",
        33,
        "党内外群众意见座谈会记录",
        SECTION_PROBATIONARY,
        CARRIER_PASTE,
        True,
        ("群众评议材料",),
        (),
        53,
    ),
    ArchiveItem(
        "m34",
        34,
        "支部委员会审查意见",
        SECTION_PROBATIONARY,
        CARRIER_SIGN,
        True,
        (),
        ("branch_committee_review",),
        54,
        "含党小组意见与拟召开支部大会日期",
    ),
    ArchiveItem(
        "m35",
        35,
        "拟接收正式党员公示情况",
        SECTION_PROBATIONARY,
        CARRIER_SIGN,
        True,
        (),
        ("publicity",),
        55,
        "公示一般 7 天（支部大会前），口径与接收阶段 5 个工作日不同",
    ),
    ArchiveItem(
        "m36",
        36,
        "党支部大会讨论转为正式党员会议记录",
        SECTION_PROBATIONARY,
        CARRIER_SIGN,
        True,
        (),
        ("branch_vote",),
        56,
        "表决要求与接收预备党员支部大会相同",
    ),
    ArchiveItem(
        "m37",
        37,
        "对转为中共正式党员进行审批的请示",
        SECTION_PROBATIONARY,
        CARRIER_PASTE,
        True,
        (),
        (),
        58,
    ),
    ArchiveItem(
        "m38",
        38,
        "学校党委对预备党员转正的审批情况",
        SECTION_PROBATIONARY,
        CARRIER_SIGN,
        True,
        (),
        ("higher_record",),
        59,
        "抬头致党总支，登记“同意/不同意进行正式党员备案”",
    ),
)


def items_for_section(section: str) -> tuple[ArchiveItem, ...]:
    """按阶段取材料项（保持手册顺序）。"""
    return tuple(item for item in ARCHIVE_CHECKLIST if item.section == section)


def required_items(section: str) -> tuple[ArchiveItem, ...]:
    """按阶段取必备材料项；按需项（如函调材料）不计入缺失。"""
    return tuple(item for item in items_for_section(section) if item.required)


def section_counts() -> dict[str, int]:
    """各阶段材料项数，供界面显示"共 N 项"。"""
    return {section: len(items_for_section(section)) for section in SECTION_ORDER}


def section_active(section: str, stage: MemberStage | str) -> bool:
    """当前阶段是否已经进入该目录阶段；未进入的阶段不参与缺失统计。

    ``disqualified`` / ``rejected`` 不在任何阶段的生效范围内，由调用方给出"不核对"的说明。
    """
    current = stage if isinstance(stage, MemberStage) else MemberStage(stage)
    return current in SECTION_ACTIVE_STAGES.get(section, ())


def match_item(
    item: ArchiveItem,
    *,
    archived_types: Collection[str],
    done_kinds: Collection[str],
    active: bool,
) -> str:
    """判断单项状态：先看能否对上归档材料，再看能否对上已完成的程序节点。

    对不上且属于"只能人工确认"的项返回 ``unconfirmed``，不谎报为已归档、也不报缺材料。
    """
    if not active:
        return STATUS_NOT_APPLICABLE
    if item.material_types and set(item.material_types) & set(archived_types):
        return STATUS_ARCHIVED
    if item.procedure_kinds and set(item.procedure_kinds) & set(done_kinds):
        return STATUS_ARCHIVED
    if item.manual_only:
        return STATUS_UNCONFIRMED
    if not item.required:
        return STATUS_OPTIONAL
    return STATUS_MISSING


def manual_only_codes() -> tuple[str, ...]:
    """只能人工确认归档的项，界面须明确说明系统不校验其内容。"""
    return tuple(item.code for item in ARCHIVE_CHECKLIST if item.manual_only)
