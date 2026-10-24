import { useEffect, useState, useSyncExternalStore } from "react";
import { IS_LIVE } from "./api.js";
import { demoPasswordService, subscribePasswordSecurity } from "./password-security.js";
import { accountSecurityApi } from "./account-security-api.js";

const snapshot = () => IS_LIVE ? "" : demoPasswordService().snapshot();

export function usePasswordState(user, { admin = false, tenantId } = {}) {
  useSyncExternalStore(subscribePasswordSecurity, snapshot, snapshot);
  const [live, setLive] = useState({ requests: [], audit: [], loading: IS_LIVE });
  useEffect(() => {
    if (!IS_LIVE || (admin && user.role !== "system_admin")) return;
    let active = true;
    const refresh = () => {
      setLive((s) => ({ ...s, loading: true, error: null }));
      (admin ? accountSecurityApi.requests(tenantId || user.tenant_id) : accountSecurityApi.own())
        .then((result) => { if (active) setLive(admin ? { requests: result.items, audit: [], loading: false } : { ...result, requests: [], audit: [], loading: false }); })
        .catch((error) => { if (active) setLive({ requests: [], audit: [], error, loading: false }); });
    };
    refresh();
    const unsubscribe = subscribePasswordSecurity(refresh);
    return () => { active = false; unsubscribe(); };
  }, [user.id, user.tenant_id, user.role, admin, tenantId]);
  if (IS_LIVE) return live;
  try {
    const service = demoPasswordService();
    return admin ? { requests: service.inbox(user, tenantId), audit: service.audit(user), error: null } : { ...service.own(user), error: null };
  } catch (error) { return { requests: [], audit: [], error }; }
}
