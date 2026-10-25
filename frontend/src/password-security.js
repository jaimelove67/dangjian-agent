import { IS_LIVE, getSession } from "./api.js";
import { validateAdminChange } from "./platform-identity-api.js";
import { accountSecurityApi } from "./account-security-api.js";
import { normalizeSystemAuditCopy } from "./system-copy.js";
import { approvedResetPassword } from "./default-password.js";

export const PASSWORD_STORAGE_KEY = "dangjian.demo-password-security.v1";
export const PASSWORD_EVENT = "dangjian:password-security";
const SELF_PASSWORD_ROLES = new Set([
  "branch_secretary",
  "organizer",
  "member",
  "applicant",
]);
const ITERATIONS = 210000;
const encoder = new TextEncoder();
const accountKey = (user) => JSON.stringify([user.tenant_id, user.id]);
const emptyState = () => ({
  version: 1,
  accounts: {},
  requests: [],
  audit: [],
});

export function canChangeOwnPassword(user) {
  return SELF_PASSWORD_ROLES.has(user?.role);
}

export function validateNewPassword(current, password, confirmation) {
  if (!current) throw new Error("请输入当前密码。");
  if (
    typeof password !== "string" ||
    password.length < 8 ||
    encoder.encode(password).length > 72
  )
    throw new Error("新密码需至少8位，且 UTF-8 编码不超过72字节。");
  if (password !== confirmation) throw new Error("两次输入的新密码不一致。");
  if (password === current) throw new Error("新密码不能与当前密码相同。");
}

export function accountPasswordChange(form, { required = false } = {}) {
  const password = form.get("password") || "";
  const confirmation = form.get("password_confirmation") || "";
  if (!required && !password && !confirmation) return undefined;
  if (
    typeof password !== "string" ||
    Array.from(password).length < 8 ||
    encoder.encode(password).length > 72
  )
    throw new Error("新密码需至少8位，且 UTF-8 编码不超过72字节。");
  if (password.trim() !== password)
    throw new Error("新密码首尾不能包含空白字符。");
  if (password !== confirmation) throw new Error("两次输入的新密码不一致。");
  return password;
}

// This is an isolated local-demo service, never an authorization boundary for live accounts.
// Keep the verifier, lifetime allowance, one-use grants and audit in one atomic storage write.
export function createDemoPasswordService({
  storage,
  crypto,
  lock,
  directory,
  currentSession,
  publish = () => {},
}) {
  function read() {
    const raw = storage.getItem(PASSWORD_STORAGE_KEY);
    if (!raw) return emptyState();
    let state;
    try {
      state = JSON.parse(raw);
    } catch {
      throw new Error("本地改密记录无法读取，请联系管理员处理。");
    }
    if (
      state?.version !== 1 ||
      !state.accounts ||
      typeof state.accounts !== "object" ||
      Array.isArray(state.accounts) ||
      !Array.isArray(state.requests) ||
      !Array.isArray(state.audit)
    )
      throw new Error("本地改密记录格式异常，请联系管理员处理。");
    return state;
  }
  function write(state) {
    try {
      storage.setItem(PASSWORD_STORAGE_KEY, JSON.stringify(state));
    } catch {
      throw new Error(
        "改密记录未能保存，本次操作未生效，请检查浏览器存储权限。",
      );
    }
    publish();
  }
  function resolve(user, allowInactive = false) {
    const data = directory();
    const account = data.accounts?.find(
      (a) => a.id === user?.id && a.tenant_id === user?.tenant_id,
    );
    if (
      !account ||
      (!allowInactive && account.is_active === false) ||
      !data.tenants?.some(
        (t) => t.id === account.tenant_id && t.is_active !== false,
      )
    )
      throw new Error("账号或所属租户不可用，请重新登录。");
    return account;
  }
  function actor(user, admin = false) {
    const session = currentSession();
    if (
      session?.user?.id !== user?.id ||
      session?.user?.tenant_id !== user?.tenant_id
    )
      throw new Error("登录账号已切换，请重新打开后操作。");
    const account = resolve(user);
    if (
      (session.passwordVersion || 0) !==
      (record(read(), account).password_version || 0)
    )
      throw new Error("登录会话已失效，请使用新密码重新登录。");
    const allowedAdminRoles =
      admin === "manage" ? ["system_admin", "school_admin"] : ["system_admin"];
    if (
      admin
        ? !allowedAdminRoles.includes(account.role) ||
          !session.permissions?.includes("admin.identity")
        : !canChangeOwnPassword(account)
    )
      throw new Error(
        admin === "manage"
          ? "仅平台管理员或学校管理员可以管理账号密码。"
          : admin
            ? "仅平台管理员可以审批改密申请。"
            : "当前角色不开放自主修改密码。",
      );
    return account;
  }
  function record(state, user) {
    const value = state.accounts[accountKey(user)] || {};
    if (
      value.self_change_used != null &&
      typeof value.self_change_used !== "boolean"
    )
      throw new Error("本地改密次数记录异常，请联系管理员处理。");
    if (
      (value.credential &&
        value.self_change_used !== true &&
        !value.admin_changed_at) ||
      (value.password_version != null &&
        (!Number.isSafeInteger(value.password_version) ||
          value.password_version < 0))
    )
      throw new Error("本地改密记录不完整，请联系管理员处理。");
    return value;
  }
  function ownRequests(state, user) {
    return state.requests.filter(
      (r) => r.user_id === user.id && r.tenant_id === user.tenant_id,
    );
  }
  function allowance(state, user) {
    const used = record(state, user).self_change_used === true;
    const history = ownRequests(state, user);
    const pending = history.find((r) => r.status === "pending");
    const approved = history.find((r) => r.status === "approved");
    return { used, pending, approved, history, canChange: !used || !!approved };
  }
  function audit(state, user, action, target, detail) {
    const id = crypto.randomUUID();
    state.audit.unshift({
      id,
      request_id: `local-password-${id}`,
      created_at: new Date().toISOString(),
      user_id: user.id,
      user_name: user.name,
      action,
      resource_type: "password_request",
      resource_id: target.id,
      tenant_id: target.tenant_id,
      category: "permission",
      result: "success",
      detail,
    });
  }
  function exclusive(action) {
    if (!lock)
      throw new Error(
        "当前浏览器不支持安全保存改密记录，请使用新版 Chrome 或 Edge。",
      );
    return lock("dangjian-demo-password-security", action);
  }
  const hex = (value) =>
    Array.from(new Uint8Array(value), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
  async function derive(password, salt, iterations = ITERATIONS) {
    if (!crypto?.subtle)
      throw new Error("当前环境不支持密码校验，请使用本地预览或 HTTPS 访问。");
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(password),
      "PBKDF2",
      false,
      ["deriveBits"],
    );
    return hex(
      await crypto.subtle.deriveBits(
        {
          name: "PBKDF2",
          salt: new Uint8Array(salt),
          iterations,
          hash: "SHA-256",
        },
        key,
        256,
      ),
    );
  }
  async function matches(password, credential) {
    if (!credential) return password === "123456";
    if (
      credential.algorithm !== "PBKDF2-SHA256" ||
      credential.iterations !== ITERATIONS ||
      !Array.isArray(credential.salt) ||
      credential.salt.length !== 16 ||
      typeof credential.hash !== "string" ||
      credential.hash.length !== 64
    )
      throw new Error("本地密码校验记录异常，请联系管理员重置。");
    const hash = await derive(password, credential.salt, credential.iterations);
    let diff = 0;
    for (let i = 0; i < hash.length; i++)
      diff |= hash.charCodeAt(i) ^ credential.hash.charCodeAt(i);
    return diff === 0;
  }
  return {
    snapshot() {
      try {
        return storage.getItem(PASSWORD_STORAGE_KEY) || "";
      } catch {
        return "unavailable";
      }
    },
    revision(user) {
      return record(read(), user).password_version || 0;
    },
    own(user) {
      const account = actor(user);
      const state = read();
      return {
        ...allowance(state, account),
        changedAt: record(state, account).changed_at,
      };
    },
    inbox(user, tenantId) {
      actor(user, true);
      return read().requests.filter(
        (r) => !tenantId || r.tenant_id === tenantId,
      );
    },
    audit(user) {
      actor(user, true);
      return read().audit.map(normalizeSystemAuditCopy);
    },
    async verify(user, password) {
      const account = resolve(user);
      const value = record(read(), account);
      const valid = await matches(password, value.credential);
      if ((value.password_version || 0) !== this.revision(account))
        throw new Error("密码已发生变化，请重新输入后登录。");
      resolve(user);
      return { valid, version: value.password_version || 0 };
    },
    change(user, { current, password, confirmation }) {
      return exclusive(async () => {
        const account = actor(user);
        validateNewPassword(current, password, confirmation);
        const state = read();
        const available = allowance(state, account);
        if (!available.canChange)
          throw new Error(
            "自主修改次数已用完，请先提交改密申请并等待管理员批准。",
          );
        const value = record(state, account);
        if (!(await matches(current, value.credential)))
          throw new Error("当前密码不正确，请重新输入。");
        const salt = Array.from(crypto.getRandomValues(new Uint8Array(16)));
        const hash = await derive(password, salt);
        // Recheck identity, directory and storage after the asynchronous password work.
        actor(user);
        if (JSON.stringify(read()) !== JSON.stringify(state))
          throw new Error("改密记录已变化，请重新打开后重试。");
        const now = new Date().toISOString();
        state.accounts[accountKey(account)] = {
          self_change_used: true,
          password_version: (value.password_version || 0) + 1,
          changed_at: now,
          credential: {
            algorithm: "PBKDF2-SHA256",
            iterations: ITERATIONS,
            salt,
            hash,
          },
        };
        if (available.used) {
          available.approved.status = "consumed";
          available.approved.consumed_at = now;
        }
        audit(
          state,
          account,
          "修改本人密码",
          account,
          available.used ? "使用一次审批授权修改密码" : "使用首次自主改密机会",
        );
        write(state);
      });
    },
    apply(user, reason) {
      return exclusive(() => {
        const account = actor(user);
        const state = read();
        const available = allowance(state, account);
        if (!available.used)
          throw new Error("首次修改可直接办理，无需提交申请。");
        if (available.pending || available.approved)
          throw new Error("已有待审核或已批准的申请，请先完成现有流程。");
        const text = String(reason || "").trim();
        if (text.length < 5 || text.length > 300)
          throw new Error("请填写5–300个字符的申请原因，不要填写密码。");
        const request = {
          id: crypto.randomUUID(),
          user_id: account.id,
          tenant_id: account.tenant_id,
          username: account.username,
          name: account.name,
          role: account.role,
          reason: text,
          status: "pending",
          created_at: new Date().toISOString(),
        };
        state.requests.unshift(request);
        audit(state, account, "提交改密申请", request, "申请再次修改本人密码");
        write(state);
        return request;
      });
    },
    review(user, requestId, tenantId, decision, comment) {
      return exclusive(async () => {
        const administrator = actor(user, true);
        if (!["approved", "rejected"].includes(decision))
          throw new Error("请选择批准或驳回。");
        const text = String(comment || "").trim();
        if (text.length < 2 || text.length > 300)
          throw new Error("请填写2–300个字符的处理意见。");
        const state = read();
        const request = state.requests.find(
          (r) => r.id === requestId && r.tenant_id === tenantId,
        );
        if (!request || request.status !== "pending")
          throw new Error("该申请已处理或不属于当前租户，请刷新后查看。");
        const target = resolve({
          id: request.user_id,
          tenant_id: request.tenant_id,
        });
        if (target.id === administrator.id || !canChangeOwnPassword(target))
          throw new Error("该账号当前不适用改密申请流程。");
        if (!record(state, target).self_change_used)
          throw new Error("账号改密记录已变化，请核实后处理。");
        const now = new Date().toISOString();
        if (decision === "approved") {
          const resetPassword = await approvedResetPassword(target, directory().tenants || []);
          const salt = Array.from(crypto.getRandomValues(new Uint8Array(16)));
          const hash = await derive(resetPassword, salt);
          // Recheck identity and storage after the asynchronous hash work.
          actor(user, true);
          if (JSON.stringify(read()) !== JSON.stringify(state))
            throw new Error("改密记录已变化，请重新打开后重试。");
          state.accounts[accountKey(target)] = {
            ...record(state, target),
            credential: {
              algorithm: "PBKDF2-SHA256",
              iterations: ITERATIONS,
              salt,
              hash,
            },
            admin_changed_at: now,
            changed_at: now,
            password_version: (record(state, target).password_version || 0) + 1,
          };
        }
        Object.assign(request, {
          status: decision,
          reviewed_by: administrator.id,
          reviewer_name: administrator.name,
          reviewed_at: now,
          review_comment: text,
        });
        audit(
          state,
          administrator,
          decision === "approved" ? "批准改密申请" : "驳回改密申请",
          request,
          decision === "approved"
            ? "已按学校名称和姓名拼音首字母规则恢复默认密码，并授权申请人再次修改一次密码"
            : "已驳回，申请人可补充原因后重新申请",
        );
        write(state);
      });
    },
    setPassword(user, targetUser, { password, confirmation }) {
      return exclusive(async () => {
        const administrator = actor(user, "manage"),
          target = resolve(targetUser, true);
        validateAdminChange(administrator, target, { password });
        accountPasswordChange(
          new Map([
            ["password", password],
            ["password_confirmation", confirmation],
          ]),
          { required: true },
        );
        const state = read(),
          value = record(state, target);
        const salt = Array.from(crypto.getRandomValues(new Uint8Array(16)));
        const hash = await derive(password, salt);
        validateAdminChange(actor(user, "manage"), resolve(targetUser, true), {
          password,
        });
        if (JSON.stringify(read()) !== JSON.stringify(state))
          throw new Error("改密记录已变化，请重新打开后重试。");
        const now = new Date().toISOString();
        state.accounts[accountKey(target)] = {
          ...value,
          admin_changed_at: now,
          changed_at: now,
          password_version: (value.password_version || 0) + 1,
          credential: {
            algorithm: "PBKDF2-SHA256",
            iterations: ITERATIONS,
            salt,
            hash,
          },
        };
        for (const request of ownRequests(state, target)) {
          if (["pending", "approved"].includes(request.status)) {
            request.status = "cancelled";
            request.cancelled_at = now;
          }
        }
        audit(
          state,
          administrator,
          "管理员修改账号密码",
          target,
          "设置新密码，保留累计自主改密次数并撤销未完成申请",
        );
        write(state);
      });
    },
    reset(user, targetUser) {
      return exclusive(() => {
        const administrator = actor(user, true),
          target = resolve(targetUser);
        if (administrator.id === target.id)
          throw new Error("不能从管理列表重置当前登录账号的密码。");
        const state = read(),
          value = record(state, target);
        state.accounts[accountKey(target)] = {
          ...value,
          credential: null,
          password_version: (value.password_version || 0) + 1,
        };
        for (const request of ownRequests(state, target)) {
          if (["pending", "approved"].includes(request.status)) {
            request.status = "cancelled";
            request.cancelled_at = new Date().toISOString();
          }
        }
        audit(
          state,
          administrator,
          "重置账号密码",
          target,
          "恢复初始密码，保留累计自主改密次数并撤销未完成申请",
        );
        write(state);
      });
    },
  };
}

let runtime;
const livePasswordService = {
  async change(_user, body) {
    validateNewPassword(body.current, body.password, body.confirmation);
    return accountSecurityApi.change(body);
  },
  async apply(_user, reason) {
    const result = await accountSecurityApi.apply(reason);
    window.dispatchEvent(new Event(PASSWORD_EVENT));
    return result;
  },
  async review(_user, id, tenantId, decision, comment, version) {
    const result = await accountSecurityApi.review(id, tenantId, decision, comment, version);
    window.dispatchEvent(new Event(PASSWORD_EVENT));
    return result;
  },
};
export function passwordService() {
  return IS_LIVE ? livePasswordService : demoPasswordService();
}
export function demoPasswordService() {
  if (IS_LIVE)
    throw new Error(
      "当前操作不可用，请从头像菜单办理修改密码，或联系平台管理员。",
    );
  runtime ||= createDemoPasswordService({
    storage: localStorage,
    crypto: globalThis.crypto,
    lock: globalThis.navigator?.locks?.request.bind(globalThis.navigator.locks),
    directory: () =>
      JSON.parse(localStorage.getItem("dangjian.demo.v1") || "{}"),
    currentSession: getSession,
    publish: () => window.dispatchEvent(new Event(PASSWORD_EVENT)),
  });
  return runtime;
}

export function subscribePasswordSecurity(listener) {
  const storageListener = (event) => {
    if (event.key === PASSWORD_STORAGE_KEY || event.key === null) listener();
  };
  window.addEventListener(PASSWORD_EVENT, listener);
  window.addEventListener("storage", storageListener);
  return () => {
    window.removeEventListener(PASSWORD_EVENT, listener);
    window.removeEventListener("storage", storageListener);
  };
}
