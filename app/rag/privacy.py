"""内容分级下限；账号权限与内容密级分别判断。

未标明的问题保守按内部处理。明确分级和常见个人标识只能提高等级；
规则不能代替组织对材料的完整保密审查。
"""

import re

from app.llm.base import DataLevel
from app.llm.gateway import GatewayError

LEVELS = [DataLevel.PUBLIC, DataLevel.INTERNAL, DataLevel.SENSITIVE, DataLevel.CLASSIFIED]
PERSONAL_IDENTIFIERS = re.compile(
    r"(?<!\d)(?:\d{17}[\dXx]|1[3-9]\d{9})(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)
CONFIDENTIAL_MARKER = re.compile(
    r"(?:^|\n)\s*(?:密级\s*[:：]\s*)?(?:涉密|机密|绝密|秘密)(?:\s|[:：]|$)"
)


def content_level(
    text: str, declared: DataLevel | None = None, *, minimum: DataLevel = DataLevel.INTERNAL
) -> DataLevel:
    detected = DataLevel.PUBLIC
    if CONFIDENTIAL_MARKER.search(text):
        detected = DataLevel.CLASSIFIED
    elif PERSONAL_IDENTIFIERS.search(text):
        detected = DataLevel.SENSITIVE
    return max([minimum, declared or DataLevel.PUBLIC, detected], key=LEVELS.index)


def require_cloud_eligible(level: DataLevel) -> None:
    if level in (DataLevel.SENSITIVE, DataLevel.CLASSIFIED):
        raise GatewayError("敏感与涉密内容禁止发送到云端模型，请改用公开或获准的内部材料")
