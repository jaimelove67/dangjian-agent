import { request } from "./api.js";

const key = encodeURIComponent;
const json = (method, body) => ({ method, body: JSON.stringify(body) });
const query = (params = {}) => {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== "" && value != null),
  );
  const suffix = new URLSearchParams(clean).toString();
  return suffix ? `?${suffix}` : "";
};

// Only operations verified against the reference API are exposed here.
export const platformIdentityApi = {
  tenants: () => request("/admin/tenants"),
  createTenant: (body) => request("/admin/tenants", json("POST", body)),
  updateTenant: (id, body) =>
    request(`/admin/tenants/${key(id)}`, json("PATCH", body)),
  users: (tenantId) => request("/admin/users" + query({ tenant_id: tenantId })),
  orgs: (tenantId) =>
    request("/admin/org-units" + query({ tenant_id: tenantId })),
  createUser: (tenantId, body) =>
    request(
      "/admin/users" + query({ tenant_id: tenantId }),
      json("POST", body),
    ),
  updateUser: (tenantId, id, body) =>
    request(
      `/admin/users/${key(id)}` + query({ tenant_id: tenantId }),
      json("PATCH", body),
    ),
  audit: (params) => request("/admin/audit-logs" + query(params)),
  exportAudit: (params) =>
    request("/admin/audit-logs/export" + query(params), { download: true }),
};

export const ADMIN_ROLES = [
  "system_admin",
  "school_admin",
  "department_admin",
  "branch_secretary",
  "organizer",
];
export const ACCOUNT_ROLES = [...ADMIN_ROLES, "member", "applicant"];
export function accountRolesForTenant(tenant, { create = false } = {}) {
  if (tenant?.tenant_type === "platform") return ["system_admin"];
  if (tenant?.tenant_type !== "school") return [];
  return (create ? ADMIN_ROLES : ACCOUNT_ROLES).filter(
    (role) => role !== "system_admin",
  );
}
export function accountOrgTypes(role) {
  return role === "system_admin"
    ? []
    : role === "school_admin"
      ? ["school"]
      : role === "department_admin"
        ? ["department"]
        : role === "organizer"
          ? ["branch", "department"]
          : ["branch"];
}
export function validSchoolAdmin(account, tenantId) {
  return (
    !!account &&
    account.role === "school_admin" &&
    account.tenant_id === tenantId &&
    account.is_active !== false
  );
}
export function validateAdminChange(actor, account, changes) {
  if (!["system_admin", "school_admin"].includes(actor?.role))
    throw new Error("仅平台管理员或学校管理员可以管理账号。");
  if (
    actor.role === "school_admin" &&
    (actor.tenant_id !== account.tenant_id ||
      account.role === "system_admin" ||
      changes.role === "system_admin")
  )
    throw new Error("学校管理员只能管理本校账号，不能授予平台权限。");
  if (
    actor.id === account.id &&
    (changes.is_active === false ||
      (changes.role && changes.role !== actor.role) ||
      (changes.org_unit_id !== undefined &&
        changes.org_unit_id !== account.org_unit_id))
  )
    throw new Error("不能停用当前账号或修改当前账号的权限范围。");
  if (changes.role && !ACCOUNT_ROLES.includes(changes.role))
    throw new Error("请选择有效的账号角色。");
}

export function validateAccountUpdate(
  actor,
  account,
  changes,
  { tenant, accounts = [], orgs = [] },
) {
  if (!account) throw new Error("账号已不存在，请刷新后重新选择。");
  validateAdminChange(actor, account, changes);
  if (!tenant || account.tenant_id !== tenant.id)
    throw new Error("账号不属于当前管理租户，请重新选择账号。");
  if (tenant.is_active === false)
    throw new Error("该学校已停用，请先启用学校租户。");
  if (changes.username !== undefined && changes.username !== account.username)
    throw new Error("登录账号作为身份标识不能修改。");
  if (
    changes.tenant_id !== undefined &&
    changes.tenant_id !== account.tenant_id
  )
    throw new Error("不能通过属性编辑迁移账号所属租户。");
  if (
    changes.name !== undefined &&
    (!changes.name.trim() || changes.name.trim().length > 50)
  )
    throw new Error("姓名需为1–50个字符。");
  if (changes.is_active !== undefined && typeof changes.is_active !== "boolean")
    throw new Error("请选择有效的账号状态。");
  const next = { ...account, ...changes };
  if (!accountRolesForTenant(tenant).includes(next.role))
    throw new Error("该租户不支持选择的账号角色。");
  if (changes.role !== undefined || changes.org_unit_id !== undefined) {
    if (
      next.role === "system_admin"
        ? next.org_unit_id != null
        : !orgs.some(
            (org) =>
              org.id === next.org_unit_id &&
              org.is_active !== false &&
              accountOrgTypes(next.role).includes(org.org_type),
          )
    )
      throw new Error("请选择与角色类型匹配的组织范围。");
    if (
      account.profile_id &&
      ["member", "applicant"].includes(account.role) &&
      ["member", "applicant"].includes(next.role) &&
      next.org_unit_id !== account.org_unit_id
    )
      throw new Error(
        "账号已关联本人档案，请先完成档案组织调整，再修改账号组织归属。",
      );
  }
  const adminRole =
    tenant.tenant_type === "platform" ? "system_admin" : "school_admin";
  const removesAdmin =
    account.role === adminRole &&
    account.is_active !== false &&
    (next.role !== adminRole || next.is_active === false);
  if (
    removesAdmin &&
    !accounts.some(
      (other) =>
        other.id !== account.id &&
        other.tenant_id === tenant.id &&
        other.role === adminRole &&
        other.is_active !== false,
    )
  )
    throw new Error("不能停用或移除该租户最后一位有效管理员。");
  if (removesAdmin && tenant.school_admin_user_id === account.id)
    throw new Error("请先在租户管理中指定其他主要管理员，再调整该账号。");
}
