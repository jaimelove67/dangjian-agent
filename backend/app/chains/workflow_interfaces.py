"""WF-03 / WF-04 的标准调用入口（T-WF02-13）。

引用核验（WF-03）与敏感检查（WF-04）目前在问答链路内联执行；框架 3.4 / 6.3 要求
它们后续能拆成独立工作流。拆分的前提是**契约先固定**，因此这里把两个环节收口成带
版本号的标准入口（出入参见 `app/schemas/wf.py`）：

- 现在：链路内联调用，行为与收口前一致，不阻塞 MVP 上线；
- 之后：换成独立工作流 / 独立服务时，只要契约与版本不变，调用方零改动。

口径来源：敏感规则仍由 `app/rag/privacy.py` 提供（文档入库 / 向量化路径直接使用该层
的 `require_cloud_eligible` 守卫），这里只是问答链路的**判定入口**，不另立一套规则。
本模块的入口不抛异常：把"能不能出网"作为数据返回，由调用方决定是拒答、改走本地模型
还是走人工路径。
"""

from __future__ import annotations

from dataclasses import asdict

from app.llm.base import DataLevel
from app.rag.privacy import CONFIDENTIAL_MARKER, PERSONAL_IDENTIFIERS, content_level
from app.rag.verifier import CitationVerifier, RetrievedChunk
from app.schemas.wf import (
    CitationCheckRequest,
    CitationCheckResponse,
    CitationInput,
    SensitiveCheckRequest,
    SensitiveCheckResponse,
)

CONFIDENTIAL_GUIDANCE = "涉密内容禁止进行 AI 处理：请改用线下人工路径，或先移除涉密标记后再提交"
SENSITIVE_GUIDANCE = (
    "敏感内容禁止发送到云端模型：请改用校内 / 本地模型，或先去除身份证、手机号、"
    "邮箱等个人标识后重试"
)


def to_citation_input(chunk: RetrievedChunk) -> CitationInput:
    """链路对象 → WF-03 契约对象（唯一适配点，便于日后替换实现）"""
    return CitationInput(**asdict(chunk))


def to_retrieved_chunk(item: CitationInput) -> RetrievedChunk:
    """WF-03 契约对象 → 链路对象"""
    return RetrievedChunk(**item.model_dump())


def citation_check(
    request: CitationCheckRequest, *, verifier: CitationVerifier | None = None
) -> CitationCheckResponse:
    """WF-03 标准入口：核验答案与引用（纯逻辑，不依赖数据库与模型）

    传入 `verifier` 时以注入实现为准（保留可替换性），否则按 `request.today` 新建。
    """
    result = (verifier or CitationVerifier(today=request.today)).verify(
        request.answer, [to_retrieved_chunk(item) for item in request.citations]
    )
    return CitationCheckResponse(
        answer=result.answer,
        valid=result.valid,
        citations=result.citations,
        warnings=result.warnings,
    )


def sensitive_check(request: SensitiveCheckRequest) -> SensitiveCheckResponse:
    """WF-04 标准入口：判定内容级别与能否出网，并说明原因与下一步"""
    declared = DataLevel(request.declared_level) if request.declared_level else None
    level = content_level(request.text, declared, minimum=DataLevel(request.minimum_level))

    reasons: list[str] = []
    if declared == DataLevel.CLASSIFIED:
        reasons.append("调用方声明密级为涉密（classified）")
    if CONFIDENTIAL_MARKER.search(request.text):
        reasons.append("文本命中涉密标记（涉密 / 机密 / 绝密 / 秘密）")
    if PERSONAL_IDENTIFIERS.search(request.text):
        reasons.append("文本含个人标识（身份证 / 手机号 / 邮箱）")

    cloud_allowed = level not in (DataLevel.SENSITIVE, DataLevel.CLASSIFIED)
    if level == DataLevel.CLASSIFIED:
        guidance = CONFIDENTIAL_GUIDANCE
    elif level == DataLevel.SENSITIVE:
        guidance = SENSITIVE_GUIDANCE
    else:
        guidance = ""
    if not cloud_allowed:
        reasons.append(f"判定级别 {level.value}：禁止发送到云端模型")

    return SensitiveCheckResponse(
        level=level.value,
        cloud_allowed=cloud_allowed,
        reasons=list(dict.fromkeys(reasons)),
        guidance=guidance,
    )
