"""知识库入库元数据抽取提示词。

只做"从正文里抄出已经写明的事实"，不做推断：
发文机关、文号、生效日期这几项一旦被模型编造，后面检索出的每一条引用都会带着
错误的出处，比让用户自己填更糟。因此提示词里反复强调"没写就留空"，
并在服务层对枚举、日期再做一次校验，不合格一律丢弃。
"""

from __future__ import annotations

import json

#: 抽取字段的枚举约束：与 app/core/constants 的层级定义保持一致
LEVELS = ("central", "provincial", "school", "department")

FIELDS = (
    "title",
    "doc_number",
    "issuer",
    "level",
    "issue_date",
    "effective_date",
    "expiration_date",
    "tags",
    "summary",
)

_EXAMPLE = {
    "title": "关于加强发展党员政治审查工作的实施办法",
    "doc_number": "校党发〔2026〕5号",
    "issuer": "中共湖南科技职业学院委员会",
    "level": "school",
    "issue_date": "2026-03-01",
    "effective_date": "2026-03-01",
    "expiration_date": "",
    "tags": ["发展党员", "政治审查"],
    "summary": "明确发展对象政治审查的内容、程序与责任分工，自印发之日起施行。",
}


def build_prompt(text: str) -> str:
    """把正文拼成抽取提示词（正文已截断，避免超上下文）"""
    return (
        "你是党建工作文件管理员。请从下面这份文件的正文中**抄录**入库需要的元数据，"
        "只输出一个 JSON 对象，不要输出解释、不要用代码块包裹。\n"
        "字段与取值规则：\n"
        "- title：文件标题（去掉书名号《》，没有则空字符串）\n"
        "- doc_number：发文字号，照抄原文（如 校党发〔2026〕5号）；没有则空\n"
        "- issuer：发文机关全称，照抄原文（如 中共XX大学委员会）；没有则空\n"
        f"- level：效力层级，只能是 {'/'.join(LEVELS)} 之一"
        "（党中央及部委=central，省级=provincial，学校党委/行政=school，院系=department）；"
        "判断不了就空字符串\n"
        "- issue_date：印发日期，格式 YYYY-MM-DD；没有则空\n"
        "- effective_date：生效日期，格式 YYYY-MM-DD；"
        "正文写“自发布之日起施行”时取 issue_date；找不到依据就留空\n"
        "- expiration_date：失效日期或“有效期至”，格式 YYYY-MM-DD；没有则空\n"
        '- tags：3 个以内主题词数组，词要短（如 ["发展党员","政治审查"]）\n'
        "- summary：80 字以内的内容摘要，只概括正文写了什么\n"
        "硬性要求：不要编造任何字段。正文里没写的，一律留空字符串或空数组；"
        "日期无法确定就留空。宁可少填，也不要猜。\n"
        f"输出示例：{json.dumps(_EXAMPLE, ensure_ascii=False)}\n"
        f"<文件正文>\n{text}\n</文件正文>\n"
        "JSON："
    )
