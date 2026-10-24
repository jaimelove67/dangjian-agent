import { request } from "./api.js";

const json = (body) => ({ method: "POST", body: JSON.stringify(body) });
const tenant = (id) => `?tenant_id=${encodeURIComponent(id)}`;
export const accountSecurityApi = {
  own: () => request("/auth/password-state"),
  change: (body) => request("/auth/password-change", json(body)),
  apply: (reason) => request("/auth/password-requests", json({ reason })),
  requests: (tenantId) => request("/admin/password-requests" + tenant(tenantId)),
  review: (id, tenantId, decision, comment, version) => request(`/admin/password-requests/${encodeURIComponent(id)}/review` + tenant(tenantId), json({ decision, comment, version })),
  sessions: (tenantId) => request("/admin/login-sessions" + tenant(tenantId)),
  revoke: (id, tenantId) => request(`/admin/login-sessions/${encodeURIComponent(id)}/revoke` + tenant(tenantId), json({})),
};
