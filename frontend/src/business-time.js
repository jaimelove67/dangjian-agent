// Backend business timestamps are UTC; date-only fields remain calendar dates.
export function formatBusinessTime(value) {
  if (!value) return "—";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const timestamp = text.replace(" ", "T");
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : timestamp + "Z";
  const date = new Date(utc);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", hour12: false });
}
