import { DEPARTMENTS, organizations, seedMembers } from "./data.js";

// Role permissions follow app/core/security.py in the reference project.
const selfPermissions = [
  "qa.ask",
  "knowledge.query",
  "member.self_query",
  "member.material_submit",
];
const branchPermissions = [
  "qa.ask",
  "knowledge.query",
  "member.query",
  "member.stage_transition",
  "member.scoring",
  "meeting.query",
  "meeting.manage",
  "meeting.review",
  "meeting.archive",
  "assessment.query",
  "assessment.manage",
  "assessment.export",
  "admin.review",
];
const managerPermissions = [
  ...branchPermissions,
  "knowledge.manage",
  "knowledge.review",
  "study.query",
  "study.manage",
  "study.review",
  "assessment.review",
];
const schoolPermissions = [
  ...managerPermissions,
  "admin.archive_confirm",
  "assessment.configure",
  "admin.config",
  "admin.audit",
  "admin.identity",
];
export const ROLE_INFO = {
  system_admin: {
    label: "平台管理员",
    scope: "all",
    subtitle: "维护账号与租户，守好系统运行和审计边界",
    permissions: [...schoolPermissions, "admin.ops"],
  },
  school_admin: {
    label: "校级管理员",
    scope: "school",
    subtitle: "统筹全校党建工作，掌握基层组织运行情况",
    permissions: schoolPermissions,
  },
  department_admin: {
    label: "院系管理员",
    scope: "department",
    subtitle: "聚焦本院工作进度，推动支部任务落地",
    permissions: managerPermissions,
  },
  branch_secretary: {
    label: "支部书记",
    scope: "branch",
    subtitle: "抓好组织生活与人工审核，让支部工作落到实处",
    permissions: [...branchPermissions, "assessment.review"],
  },
  organizer: {
    label: "组织员",
    scope: "branch",
    subtitle: "做好材料接收、培养记录和党务办理",
    permissions: branchPermissions,
  },
  member: {
    label: "普通党员",
    scope: "self",
    subtitle: "查看本人档案、提交个人材料、查阅制度依据",
    permissions: selfPermissions,
  },
  applicant: {
    label: "入党申请人",
    scope: "self",
    subtitle: "了解本人登记进度，按组织要求提交材料",
    permissions: selfPermissions,
  },
};
export const SELF_ROUTES = new Set([
  "dashboard",
  "self-archive",
  "self-materials",
  "assistant",
]);
export const PLATFORM_NAV_SPEC = [
  { id: "dashboard", label: "平台工作台" },
  { id: "tenants", label: "租户管理", permission: "admin.identity" },
  { id: "accounts", label: "账号与权限", permission: "admin.identity" },
  { id: "operations", label: "系统运维", permission: "admin.ops" },
  { id: "configuration", label: "平台配置", permission: "admin.config" },
  { id: "audit", label: "安全审计", permission: "admin.audit" },
];
export const PLATFORM_ROUTES = new Set([
  ...PLATFORM_NAV_SPEC.map((n) => n.id),
  "profile",
]);
export function isSelfService(user) {
  return ["member", "applicant"].includes(user?.role);
}
export function roleLabel(user) {
  if (user?.role === "member")
    return user.person_type === "teacher"
      ? "教师党员"
      : user.person_type === "student"
        ? "学生党员"
        : "普通党员";
  return ROLE_INFO[user?.role]?.label || "未识别角色";
}
export function hasPermission(session, permission) {
  return (
    !!ROLE_INFO[session?.user?.role]?.permissions.includes(permission) &&
    !!session?.permissions?.includes(permission)
  );
}
export function canAccess(session, item, live = false) {
  if (!session?.user || !item || !ROLE_INFO[session.user.role]) return false;
  if (session.user.role === "system_admin" && !PLATFORM_ROUTES.has(item.id))
    return false;
  if (item.demo && live) return false;
  if (item.roles && !item.roles.includes(session.user.role)) return false;
  if (isSelfService(session.user) && !SELF_ROUTES.has(item.id)) return false;
  return !item.permission || hasPermission(session, item.permission);
}
const branch = organizations.find((org) => org.id === seedMembers.at(-1).orgId);
const teacher = seedMembers.find(
  (member) => member.orgId === branch.id && member.number.startsWith("T"),
);
const student = seedMembers.find(
  (member) =>
    member.orgId === branch.id &&
    !member.number.startsWith("T") &&
    member.stage === "正式党员",
);
const applicant = seedMembers.at(-1);
function persona(id, role, name, username, extra = {}) {
  return {
    id,
    title: extra.title || ROLE_INFO[role].label,
    user: {
      id: "demo-" + id,
      name,
      username,
      role,
      tenant_id: role === "system_admin" ? "platform-1" : "school-1",
      org_unit_id:
        role === "system_admin"
          ? null
          : role === "school_admin"
            ? "school-1"
            : role === "department_admin"
              ? "dept-10"
              : branch.id,
      department: branch.department,
      ...extra,
    },
  };
}
export const DEMO_PERSONAS = [
  persona("school", "school_admin", "李老师", "admin", { title: "校级管理员" }),
  persona("platform", "system_admin", "平台管理员", "platform"),
  persona("department", "department_admin", "赵老师", "department"),
  persona("secretary", "branch_secretary", "周书记", "secretary"),
  persona("organizer", "organizer", "王组织员", "organizer"),
  persona("teacher", "member", teacher.name, "teacher", {
    title: "教师党员",
    person_type: "teacher",
    profile_id: teacher.id,
    org_unit_id: teacher.orgId,
    department: teacher.department,
  }),
  persona("student", "member", student.name, "student", {
    title: "学生党员",
    person_type: "student",
    profile_id: student.id,
    org_unit_id: student.orgId,
    department: student.department,
  }),
  persona("applicant", "applicant", applicant.name, "applicant", {
    profile_id: applicant.id,
    org_unit_id: applicant.orgId,
    department: applicant.department,
  }),
];
export function demoSession(personaId = "school") {
  const p = DEMO_PERSONAS.find((p) => p.id === personaId) || DEMO_PERSONAS[0];
  return {
    mode: "demo",
    personaId: p.id,
    user: { ...p.user },
    permissions: [...ROLE_INFO[p.user.role].permissions],
  };
}
export function sessionForAccount(account, passwordVersion = 0) {
  return {
    mode: "demo",
    passwordVersion,
    personaId: DEMO_PERSONAS.find((p) => p.user.id === account.id)?.id || null,
    user: { ...account, tenant_id: account.tenant_id || "school-1" },
    permissions: [...(ROLE_INFO[account.role]?.permissions || [])],
  };
}
export function demoAccountAvailable(account, tenants = []) {
  return (
    !!account?.is_active &&
    (!tenants.length ||
      tenants.some(
        (t) => t.id === (account.tenant_id || "school-1") && t.is_active,
      ))
  );
}
export function normalizeDemoSession(saved, accounts = [], tenants = []) {
  if (!saved || saved.mode !== "demo") return demoSession();
  const account = accounts.find((a) => a.id === saved.user?.id);
  return demoAccountAvailable(account, tenants)
    ? sessionForAccount(account, saved.passwordVersion || 0)
    : null;
}
export function scopeLabel(user) {
  const scope = ROLE_INFO[user?.role]?.scope;
  return scope === "all"
    ? "平台授权范围"
    : scope === "school"
      ? "全校"
      : scope === "department"
        ? user.department || "所属院系"
        : scope === "branch"
          ? organizations.find((o) => o.id === user.org_unit_id)?.name ||
            "所属支部"
          : "仅本人";
}
export function memberInScope(user, member) {
  const scope = ROLE_INFO[user?.role]?.scope;
  if (!scope) return false;
  if (scope === "all") return true;
  if ((user.tenant_id || "school-1") !== (member.tenant_id || "school-1"))
    return false;
  if (scope === "school") return true;
  if (scope === "department") return member.department === user.department;
  if (scope === "branch")
    return (member.orgId || member.org_unit_id) === user.org_unit_id;
  return !!user.profile_id && member.id === user.profile_id;
}
export function scopedMembers(data, session, live = false) {
  return live
    ? data.members
    : data.members.filter((m) => memberInScope(session?.user, m));
}
export function memberMatchesOrganization(member, org, orgIds = []) {
  const ids =
    orgIds instanceof Set ? orgIds : new Set((orgIds || []).filter(Boolean));
  if (ids.size)
    return ids.has(String(member.orgId || member.org_unit_id || ""));
  return !org || member.organization === org || member.department === org;
}
export function recordInScope(user, record) {
  const org = organizations.find(
    (o) => o.id === (record.orgId || record.org_unit_id),
  );
  return memberInScope(user, {
    orgId: org?.id,
    department: org?.department,
    tenant_id: record.tenant_id || org?.tenant_id || "school-1",
    id: record.profile_id,
  });
}
export function scopedMeetings(data, session, live = false) {
  return live
    ? data.meetings
    : data.meetings.filter((m) => recordInScope(session?.user, m));
}
export function scopedOrganizations(session) {
  const u = session?.user;
  const scope = ROLE_INFO[u?.role]?.scope;
  return organizations.filter((o) =>
    memberInScope(u, {
      orgId: o.id,
      department: o.department,
      tenant_id: o.tenant_id || "school-1",
    }),
  );
}
export function accountOrganizations() {
  return [
    { id: "school-1", name: "高校党委", org_type: "school" },
    ...DEPARTMENTS.map((name, i) => ({
      id: `dept-${i}`,
      name,
      org_type: "department",
    })),
    ...organizations.map((o) => ({ ...o, org_type: "branch" })),
  ];
}
