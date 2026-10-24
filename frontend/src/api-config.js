export function resolveApiBase(value) {
  const base = (value?.trim() || "/api/v1").replace(/\/+$/, "");
  if (/^\/(?!\/)[^?#\\]*$/.test(base)) return base;
  let url;
  try {
    url = new URL(base);
  } catch {
    throw new Error("VITE_API_BASE_URL must be an HTTP(S) URL or an absolute path.");
  }
  if (
    !/^https?:\/\//i.test(base) || !["http:", "https:"].includes(url.protocol) ||
    url.username || url.password || url.search || url.hash || base.includes("\\")
  ) {
    throw new Error("VITE_API_BASE_URL must not include credentials, query parameters or a fragment.");
  }
  return base;
}
