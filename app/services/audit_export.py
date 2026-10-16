"""审计日志导出（T-SYS-05E / T-NFR-08）：对账包 = CSV 台账 + 导出说明 + manifest。

为什么打包而不是裸 CSV：审计复核通常要连同"这份表怎么来的"一起交接——筛选口径、导出人、
条数、字段取值含义、时区口径。这些信息塞进 CSV 表头会破坏机器可解析性，塞进文件名又写不下。
所以一个 zip 里三件东西：

- ``audit-logs.csv``：UTF-8 BOM 台账，Excel 双击即可打开；
- ``导出说明.txt``：人读；
- ``manifest.json``：机器读。

后两者由**同一份 dict** 渲染，不重复维护两套说明。

时间口径：导出按北京时间（UTC+8）展示，且**按时间正序**——对账是按时间轴读的（列表则按
最新在前，便于先看最近发生了什么）。
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Iterable

from app.core.csv_io import csv_bytes
from app.core.timeutil import local_now_text, local_time
from app.models.audit import AuditLog

#: 单次导出上限：再多就不是一份能核对的表了，提示分批导出比生成一个打不开的文件有用
MAX_EXPORT_ROWS = 5000

CSV_NAME = "audit-logs.csv"
GUIDE_NAME = "导出说明.txt"
MANIFEST_NAME = "manifest.json"

HEADERS: tuple[str, ...] = (
    "时间",
    "用户编号",
    "用户名",
    "动作",
    "对象类型",
    "对象编号",
    "数据级别",
    "结果",
    "来源地址",
    "请求编号",
    "失败原因",
    "变更前",
    "变更后",
)

RESULT_NOTES = "success 成功；failed 失败；denied 拒绝"
LEVEL_NOTES = "public 公开；internal 内部；sensitive 敏感；classified 涉密"


def _json_text(value: Any) -> str:
    """JSON 字段压成一行文本：CSV 单元格里换行会把一行拆成两行"""
    if value in (None, {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def row_values(row: AuditLog) -> list[str]:
    """审计行 → CSV 单元格（顺序与 :data:`HEADERS` 一一对应）"""
    return [
        local_time(row.created_at),
        row.user_id or "",
        row.user_name or "",
        row.action or "",
        row.resource_type or "",
        row.resource_id or "",
        row.data_level or "",
        row.result or "",
        row.ip_address or "",
        row.request_id or "",
        row.error_message or "",
        _json_text(row.old_value),
        _json_text(row.new_value),
    ]


def build_manifest(*, rows: int, scope_note: str, exported_by: str) -> dict[str, Any]:
    """导出说明内容（文本版与 JSON 版都从这里来）"""
    return {
        "导出时间": local_now_text(),
        "时区": "北京时间（UTC+8）；系统内部按 UTC 存储并比较",
        "导出人": exported_by or "未记录",
        "导出条数": rows,
        "筛选口径": scope_note or "本租户全部审计记录",
        "排序": "按时间正序（对账按时间轴读）；页面列表按最新在前",
        "包含文件": {
            CSV_NAME: "审计台账（UTF-8 BOM，Excel 可直接打开）",
            GUIDE_NAME: "本说明的文本版",
            MANIFEST_NAME: "本说明的机器可读版",
        },
        "字段": list(HEADERS),
        "结果取值": RESULT_NOTES,
        "数据级别": LEVEL_NOTES,
        "说明": (
            "本包是审计记录的数据副本，与库内记录一致（审计表只追加不修改）。"
            "变更前 / 变更后在写入审计时已按数据级别脱敏，不包含未脱敏的敏感值。"
            "导出行为本身也会写入一条审计记录（动作 export，对象类型 audit_log）。"
        ),
    }


def _render_value(value: Any) -> list[str]:
    """说明文本里一个值的排布（dict 逐行、列表用顿号连起来）"""
    if isinstance(value, dict):
        return [f"  - {key}：{item}" for key, item in value.items()]
    if isinstance(value, (list, tuple)):
        return ["  - " + "、".join(str(item) for item in value)]
    return [str(value)]


def guide_text(manifest: dict[str, Any]) -> str:
    """把说明 dict 渲染成人读文本（同一份内容的另一种呈现，不是第二份口径）"""
    lines: list[str] = []
    for key, value in manifest.items():
        rendered = _render_value(value)
        if len(rendered) == 1:
            lines.append(f"{key}：{rendered[0]}")
        else:
            lines.append(f"{key}：")
            lines.extend(rendered)
    return "\n".join(lines) + "\n"


def build_audit_package(
    rows: Iterable[AuditLog], *, scope_note: str = "", exported_by: str = ""
) -> bytes:
    """构造审计导出对账包（zip 字节）"""
    items = list(rows)
    manifest = build_manifest(rows=len(items), scope_note=scope_note, exported_by=exported_by)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(CSV_NAME, csv_bytes(HEADERS, [row_values(row) for row in items]))
        archive.writestr(GUIDE_NAME, guide_text(manifest))
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue()
