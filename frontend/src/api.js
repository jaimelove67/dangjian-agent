// Verified against jaimelove67/dangjian-agent master API contracts on 2026-10-23.
import { questionText } from "./contracts.js";
import { resolveApiBase } from "./api-config.js";

export const IS_LIVE = import.meta.env?.VITE_DATA_MODE === "live";
const API_BASE = resolveApiBase(import.meta.env?.VITE_API_BASE_URL);
const SESSION_KEY = "dangjian.auth.v1";
export class ApiError extends Error {
  constructor(message, { status = 0, code, traceId = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}
function readSession(storage) {
  try {
    return JSON.parse(storage.getItem(SESSION_KEY) || "null");
  } catch {
    return null;
  }
}
export function getSession() {
  const saved = readSession(sessionStorage);
  return IS_LIVE && saved?.mode === "demo" ? null : saved;
}
export function saveSession(session) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}
export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}
let refreshPromise;
export async function request(path, options = {}, retried = false) {
  const { rawJson, acceptNotReady, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 60000);
  const token = getSession()?.tokens?.access_token;
  const identity = getSession()?.user?.id;
  let response;
  try {
    response = await fetch(API_BASE + path, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    throw new ApiError(
      error.name === "AbortError"
        ? "请求超时，请稍后重试。"
        : "系统服务暂时无法连接，请稍后重试；如持续失败，请联系管理员。",
    );
  } finally {
    clearTimeout(timer);
  }
  if (identity && getSession()?.user?.id !== identity)
    throw new ApiError("会话已变更，请在当前账号下重试。", { status: 401 });
  const saved = getSession();
  if (
    response.status === 401 &&
    !retried &&
    !path.startsWith("/auth/") &&
    saved?.tokens?.refresh_token
  ) {
    refreshPromise ||= request(
      "/auth/refresh",
      {
        method: "POST",
        headers: { Authorization: `Bearer ${saved.tokens.refresh_token}` },
      },
      true,
    )
      .then((tokens) => {
        if (getSession()?.tokens?.refresh_token === saved.tokens.refresh_token)
          saveSession({ ...saved, tokens });
        return tokens;
      })
      .finally(() => {
        refreshPromise = null;
      });
    try {
      await refreshPromise;
      if (identity && getSession()?.user?.id !== identity)
        throw new ApiError("会话已变更，请在当前账号下重试。", { status: 401 });
      return request(path, options, true);
    } catch (error) {
      if (
        error.status === 401 &&
        (!identity || getSession()?.user?.id === identity)
      ) {
        clearSession();
        window.dispatchEvent(new Event("dangjian:expired"));
      }
      throw error;
    }
  }
  if (response.status === 401 && !path.startsWith("/auth/")) {
    clearSession();
    window.dispatchEvent(new Event("dangjian:expired"));
  }
  if (options.download && response.ok) return response.blob();
  const body = await response.json().catch(() => ({}));
  if (
    identity &&
    getSession()?.user?.id !== identity &&
    response.status !== 401
  )
    throw new ApiError("会话已变更，请在当前账号下重试。", { status: 401 });
  // The protected readiness endpoint uses HTTP 503 to carry diagnostic checks.
  // Keep that exception specific: other failed requests must still throw.
  const healthNotReady =
    rawJson &&
    acceptNotReady &&
    path === "/admin/health/ready" &&
    response.status === 503 &&
    body.status === "not_ready" &&
    body.checks &&
    typeof body.checks === "object";
  if (
    (!response.ok && !healthNotReady) ||
    (body.code != null && body.code !== 0)
  )
    throw new ApiError(
      typeof body.message === "string"
        ? body.message
        : `请求失败（HTTP ${response.status}）`,
      {
        status: response.status,
        code: body.code,
        traceId: body.trace_id || response.headers.get("x-request-id") || "",
      },
    );
  return rawJson ? body : body.code === 0 ? body.data : body;
}
export const backend = {
  login: async (username, password) => {
    const tokens = await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    saveSession({ tokens });
    try {
      const [user, permissions] = await Promise.all([
        request("/auth/me"),
        request("/auth/codes"),
      ]);
      return { tokens, user, permissions };
    } catch (error) {
      clearSession();
      throw error;
    }
  },
  logout: () => request("/auth/logout", { method: "POST" }),
  organizations: () => request("/member/org-units"),
  members: () => request("/member/roster?page=1&page_size=100"),
  createMember: (payload) =>
    request("/member/roster", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  meetings: () => request("/meeting/records?page=1&page_size=100"),
  createMeeting: (payload) =>
    request("/meeting/records", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateMeeting: (id, payload) =>
    request(`/meeting/records/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  ask: async (payload) =>
    request("/qa", {
      method: "POST",
      body: JSON.stringify({
        data_level: "public",
        use_reranker: true,
        top_k: 5,
        ...payload,
        question: questionText(payload.question),
      }),
    }),
  knowledge: () => request("/knowledge-docs?page=1&page_size=100"),
  uploadKnowledge: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/knowledge-docs", { method: "POST", body });
  },
  self: () => request("/member/self/archive"),
  assessmentOrgs: () => request("/assessment/org-units"),
  assessment: (org, year) =>
    request(
      `/assessment/workspace?org_unit_id=${encodeURIComponent(org)}&year=${year}`,
    ),
  exportRoster: () => request("/member/roster/export", { download: true }),
  rosterTemplate: () => request("/member/roster/template", { download: true }),
  importRoster: ({ file, sourceNote, dryRun = true }) => {
    const body = new FormData();
    body.append("file", file);
    body.append("source_note", sourceNote);
    body.append("dry_run", String(dryRun));
    return request("/member/roster/import", { method: "POST", body });
  },
  health: () => request("/health/ready"),
};
