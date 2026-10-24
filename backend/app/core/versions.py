"""提示词 / 工作流版本登记（SEC-11 / T-SEC-11）。

为什么集中到一处：**版本号只能有一个来源**。提示词的出厂默认版本写在
``app/prompts/qa.py``、工作流契约版本写在 ``app/schemas/wf.py``；这里只回答
"当前租户实际生效的是哪个版本"以及"一次问答应该留下什么版本指纹"。
如果界面、接口、问答链路各自拼一份版本字符串，改一处漏一处，留痕就会对不上。

留痕口径（与需求文档 SEC-11 一一对应）：

- **提示词**：租户配置 ``prompt_versions`` 覆盖出厂默认（默认 v1）。改配置的动作
  由 ``config_revisions`` 表 + 配置审计留痕，本模块只负责"现在生效的是哪个版本"。
- **工作流**：WF-03 / WF-04 的契约版本（代码常量，改契约才升版本）。它的变更历史
  在代码与发布记录里，不在数据库——查询侧不编造。
- **知识库**：文档修订号（``content_revision``）跟着**每一条引用**记录，见
  ``app/rag/verifier.py`` 的 ``Citation.content_revision``：一条答案引了哪一版，
  只有跟着引用走才说得清；在这里再登记一份必然对不上。
"""

from __future__ import annotations

from typing import Any

from app.prompts.qa import QA_SYSTEM_PROMPT_VERSION, REWRITE_PROMPT_VERSION
from app.schemas.wf import WF03_VERSION, WF03_WORKFLOW, WF04_VERSION, WF04_WORKFLOW

#: 提示词种类与出厂默认版本（租户未配置时生效）
PROMPT_DEFAULTS: dict[str, str] = {
    "qa": QA_SYSTEM_PROMPT_VERSION,
    "rewrite": REWRITE_PROMPT_VERSION,
}

#: 提示词种类的显示名。导出文件与界面共用一套说法，避免同一事实两种叫法。
PROMPT_LABELS: dict[str, str] = {"qa": "问答提示词", "rewrite": "追问改写"}

#: 已登记的工作流与用途。版本号取自契约常量，不在这里重写一遍。
WORKFLOW_VERSIONS: tuple[dict[str, str], ...] = (
    {"workflow": WF03_WORKFLOW, "name": "引用核验", "version": WF03_VERSION},
    {"workflow": WF04_WORKFLOW, "name": "敏感信息检查", "version": WF04_VERSION},
)


def prompt_versions(tenant_id: str | None) -> dict[str, str]:
    """当前租户生效的提示词版本（配置覆盖 + 出厂默认）

    缺省项显式回落到默认版本，不返回空串：否则界面显示空白，使用者无法判断
    "用的是默认版本"还是"留痕丢了"。
    """
    from app.core.config import tenant_config

    configured: dict[str, Any] = (
        tenant_config.get(tenant_id, "prompt_versions", {}) if tenant_id else {}
    )
    return {kind: str(configured.get(kind) or default) for kind, default in PROMPT_DEFAULTS.items()}


def workflow_versions() -> list[dict[str, str]]:
    """已登记工作流与契约版本（只读清单）"""
    return [dict(item) for item in WORKFLOW_VERSIONS]


def version_fingerprint(tenant_id: str | None) -> dict[str, Any]:
    """一次问答的版本指纹：提示词 + 工作流；知识库版本随每条引用单独记录

    大小写与键名固定，便于后续比对"同一条问题在不同版本下的回答"。
    """
    return {
        "prompt": prompt_versions(tenant_id),
        "workflow": {item["workflow"]: item["version"] for item in WORKFLOW_VERSIONS},
    }
