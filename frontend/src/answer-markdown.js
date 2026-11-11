/**
 * 规范模型常见的行内列表写法：把“依据如下： * 第一条”拆成真正的 Markdown 列表。
 *
 * 只处理冒号后紧跟列表标记的情况，避免把正文中的乘号、斜体或代码误判为列表。
 */
export function normalizeAnswerMarkdown(markdown) {
  if (!markdown) return "";
  return String(markdown)
    .split(/(```[\s\S]*?```|`[^`\n]+`)/g)
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part.replace(
        /([：:])([ \t]+)([*+-]|\d{1,3}[.)])([ \t]+)/g,
        "$1\n\n$3$4",
      );
    })
    .join("");
}

/**
 * 把回答里的数字引用 [n] 转成 ReactMarkdown 可识别的内部链接。
 *
 * - 只转换本次回答真实存在的引用编号，避免把普通方括号误做成角标；
 * - 跳过围栏代码块和行内代码，代码里的 [1] 保持原样；
 * - 已经是 Markdown 链接或引用定义的写法不处理。
 */
export function withCitationLinks(markdown, citationIndexes = []) {
  const valid = new Set(
    (citationIndexes || [])
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0),
  );
  if (!markdown || valid.size === 0) return markdown || "";

  return String(markdown)
    .split(/(```[\s\S]*?```|`[^`\n]+`)/g)
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part.replace(
        /(?<!\\)\[(\d+)\](?!\s*[:(])/g,
        (match, raw) =>
          valid.has(Number(raw)) ? `[${raw}](citation:${raw})` : match,
      );
    })
    .join("");
}
