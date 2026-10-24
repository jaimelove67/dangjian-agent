// 建议只填空白；换文件时仅清除仍未被人工改动的建议。
export function adoptMaterialSuggestions(draft, fields, allowed) {
  const next = { ...draft }, adopted = {};
  for (const key of allowed) {
    if (!String(next[key] || "").trim() && fields[key]) {
      next[key] = fields[key];
      adopted[key] = fields[key];
    }
  }
  return { draft: next, adopted };
}
export function clearMaterialSuggestions(draft, adopted) {
  const next = { ...draft };
  for (const [key, value] of Object.entries(adopted))
    if (next[key] === value) next[key] = "";
  return next;
}
