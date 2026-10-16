"""问答记录导出（T-SYS-06）：Excel 台账 + 导出说明。

导出的是问答内容的**数据副本**（谁问的、问什么、答什么、有没有依据、用的什么级别），
用于合规复核与交接；不含被引原文文件与原始材料。

说明页必须写明筛选口径、条数与导出人：这份表"按什么条件、什么时候、由谁导出"要能自证，
否则复核时只能靠回忆。时间展示统一走 `qa_record_service.local_time`（UTC → 北京时间），
导出与列表筛选说明因此不会出现两套口径。
"""

from __future__ import annotations

import io
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.timeutil import local_now_text, local_time
from app.services.qa_record_service import versions_text

RECORD_SHEET = "问答记录"
GUIDE_SHEET = "导出说明"
HEADERS: tuple[str, ...] = (
    "时间",
    "提问人",
    "登录账号",
    "数据级别",
    "结果",
    "依据",
    "状态",
    "版本",
    "检索片段",
    "使用片段",
    "引用数",
    "问题",
    "回答",
)
_WIDTHS = (18, 12, 16, 10, 12, 10, 14, 34, 10, 10, 10, 40, 60)
_LEVEL_LABELS = {"public": "公开", "internal": "内部", "sensitive": "敏感", "classified": "涉密"}


def level_label(value: str) -> str:
    """数据级别中文名；未知取值原样保留，不把异常数据藏起来。"""
    return _LEVEL_LABELS.get(value, value)


def build_qa_records(rows: Iterable[Any], *, scope_note: str = "", exported_by: str = "") -> bytes:
    """导出问答记录：台账页 + 导出说明页"""
    items = list(rows)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = RECORD_SHEET

    fill = PatternFill("solid", fgColor="DDEBF7")
    for position, name in enumerate(HEADERS, start=1):
        cell = sheet.cell(row=1, column=position, value=name)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
        sheet.column_dimensions[get_column_letter(position)].width = _WIDTHS[position - 1]
    sheet.freeze_panes = "A2"

    for row_no, item in enumerate(items, start=2):
        values = (
            local_time(item.created_at),
            item.asker,
            item.username,
            level_label(item.data_level),
            "无依据拒答" if item.refused else "已作答",
            "有依据" if item.has_sufficient_evidence else "无依据",
            "提问人已删除" if item.is_deleted else "正常",
            versions_text(getattr(item, "versions", None)) or "未留痕",
            item.retrieved_count,
            item.used_count,
            item.citation_count,
            item.question,
            item.answer,
        )
        for position, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_no, column=position, value=value)
            if position in (1, 2, 3):
                cell.number_format = "@"

    guide = workbook.create_sheet(GUIDE_SHEET)
    guide.column_dimensions["A"].width = 100
    lines = [
        "导出说明",
        f"导出时间：{local_now_text()}（北京时间）",
        f"导出人：{exported_by or '未记录'}",
        f"导出条数：{len(items)}",
        f"筛选口径：{scope_note or '全部未删除的问答记录'}",
        "记录时间与筛选口径里的时间均按北京时间（UTC+8）显示；系统内部以 UTC 存储。",
        "本表为问答内容的数据副本，不含被引原文文件与原始材料；引用情况以系统内记录为准。",
        "「结果」为「无依据拒答」表示系统按无依据处理、没有生成实质回答；"
        "「依据」表示本次问答是否有足够的可引用依据。",
        "「状态」为「提问人已删除」表示提问人在自己的记录里软删除了这条；"
        "软删除只是不再显示，记录仍保留用于复核。",
        "「版本」为本次回答的版本留痕（提示词版本与工作流契约版本，SEC-11）；"
        "「未留痕」表示该记录早于版本留痕功能上线，系统不按当前版本倒推，避免把旧答案"
        "说成新版本产出的。被引文档的修订号见系统内的问答记录明细。",
    ]
    for row_no, text in enumerate(lines, start=1):
        cell = guide.cell(row=row_no, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if row_no == 1:
            cell.font = Font(bold=True)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
