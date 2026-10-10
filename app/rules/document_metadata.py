"""知识文档元数据校验规则

对应框架文档 5.2.1（元数据必填项）与 5.2.2（入库校验规则）：

- 必填项缺失即拒绝入库（不允许"先入库后补元数据"）；
- 涉密材料不入向量库（validation 结果携带 ``embedding_allowed``）；
- 中央级文件必须标注公开密级；
- 层级 / 可见范围 / 保密级别 / 状态取值必须合法；
- 失效日期不得早于生效日期。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional

from app.core.constants import DataLevel, DocumentLevel, DocumentStatus, DocumentVisibility

REQUIRED_FIELDS: tuple[str, ...] = (
    "doc_id",
    "file_name",
    "title",
    "issuer",
    "level",
    "visibility",
    "security_level",
    "effective_date",
    "status",
)


class MetadataValidationError(Exception):
    """元数据校验失败"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class MetadataValidationResult:
    """校验结果"""

    embedding_allowed: bool  # 是否允许进入向量库（涉密材料为 False）


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def validate_document_metadata(data: Mapping[str, Any]) -> MetadataValidationResult:
    """校验文档元数据

    Returns:
        MetadataValidationResult

    Raises:
        MetadataValidationError: 存在校验错误时，携带全部错误信息
    """
    errors: list[str] = []
    level_values = {e.value for e in DocumentLevel}
    visibility_values = {e.value for e in DocumentVisibility}
    security_values = {e.value for e in DataLevel}
    status_values = {e.value for e in DocumentStatus}

    # 必填项
    for field in REQUIRED_FIELDS:
        if _is_missing(data.get(field)):
            errors.append(f"缺少必填字段: {field}")

    # 主题标签：必填且非空
    tags = data.get("tags")
    if not isinstance(tags, (list, tuple)) or len(tags) == 0:
        errors.append("缺少必填字段: tags（主题标签）")
    elif any(_is_missing(tag) for tag in tags):
        errors.append("主题标签存在空值")

    # 枚举取值
    for field, maximum in {
        "doc_id": 100,
        "file_name": 255,
        "title": 500,
        "issuer": 200,
        "doc_number": 100,
    }.items():
        if data.get(field) is not None and len(str(data[field])) > maximum:
            errors.append(f"字段 {field} 超过长度限制（{maximum}）")

    level = data.get("level")
    if not _is_missing(level) and level not in level_values:
        errors.append(f"层级非法: {level}（应为 {'/'.join(sorted(level_values))}）")

    visibility = data.get("visibility")
    if not _is_missing(visibility) and visibility not in visibility_values:
        errors.append(f"可见范围非法: {visibility}")

    security = data.get("security_level")
    if not _is_missing(security) and security not in security_values:
        errors.append(f"保密级别非法: {security}")

    status = data.get("status")
    if not _is_missing(status) and status not in status_values:
        errors.append(f"文件状态非法: {status}")

    # 日期
    effective = _coerce_date(data.get("effective_date"))
    if not _is_missing(data.get("effective_date")) and effective is None:
        errors.append("生效日期格式非法（应为 YYYY-MM-DD）")

    expiration_raw = data.get("expiration_date")
    expiration = _coerce_date(expiration_raw)
    if not _is_missing(expiration_raw) and expiration is None:
        errors.append("失效日期格式非法（应为 YYYY-MM-DD）")
    if effective is not None and expiration is not None and expiration < effective:
        errors.append("失效日期不能早于生效日期")

    # 中央级文件必须标注公开密级
    if level == DocumentLevel.CENTRAL.value and not _is_missing(security):
        if security != DataLevel.PUBLIC.value:
            errors.append("中央级文件必须标注公开密级（security_level=public）")

    if errors:
        raise MetadataValidationError(errors)

    # 涉密材料不入向量库
    embedding_allowed = security != DataLevel.CLASSIFIED.value
    return MetadataValidationResult(embedding_allowed=embedding_allowed)
