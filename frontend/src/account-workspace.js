import {
  ROLE_INFO,
  accountOrganizations,
  canAccess,
  hasPermission,
  isSelfService,
  recordInScope,
  scopedOrganizations,
} from "./roles.js";

const records = (value) =>
  Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];
const tenantOf = (record) => record.tenant_id || "school-1";
const timeValue = (value) => {
  const parsed = Date.parse(value || "");
  return Number.isNaN(parsed) ? 0 : parsed;
};
const returnedStatus = (status) =>
  ["已退回", "待补充", "returned", "rejected"].includes(status);
const statusLabel = (record) =>
  record.status ||
  ({ pending: "待审核", approved: "已完成", rejected: "已退回" }[
    record.review_status
  ] || "待登记");

// A read-only view of existing demo records. Counts are personal, while pending
// work additionally follows the same scope and independent-review rules as its page.
export function accountWorkspace(data = {}, session = {}) {
  data ||= {};
  const user = session?.user;
  const empty = {
    organization: "未关联组织",
    scope: "未设置",
    pending: 0,
    submitted: 0,
    returned: 0,
    pendingItems: [],
    submittedItems: [],
    returnedItems: [],
    items: [],
    recent: [],
    recentAll: [],
    lastLogin: null,
    workRoute: "dashboard",
    canReview: false,
  };
  if (!user?.id || !ROLE_INFO[user.role]) return empty;

  const tenant = user.tenant_id || (user.role === "system_admin" ? "platform-1" : "school-1");
  const units = accountOrganizations();
  const tenantRecord = records(data.tenants).find((item) => item.id === tenant);
  const unit = units.find((item) => item.id === user.org_unit_id);
  const account = records(data.accounts).find(
    (item) =>
      item.id === user.id &&
      tenantOf(item) === tenant &&
      item.org_unit_id === user.org_unit_id,
  );
  const organization =
    user.org_name ||
    account?.org_name ||
    (tenant === "school-1" ? unit?.name : null) ||
    tenantRecord?.name ||
    user.department ||
    empty.organization;
  const orgs = scopedOrganizations(session);
  const scope =
    user.role === "system_admin"
      ? "平台授权范围"
      : user.role === "school_admin"
        ? orgs.length ? `全校 ${orgs.length} 个党支部` : "全校"
        : user.role === "department_admin"
          ? orgs.length ? `本院 ${orgs.length} 个党支部` : "本院"
          : isSelfService(user)
            ? "仅本人"
            : "本支部";
  const self = isSelfService(user);
  const platform = user.role === "system_admin";
  const meetingAccess = canAccess(session, { id: "meetings", permission: "meeting.query" });
  const materialAccess = canAccess(session, {
    id: "self-materials",
    roles: ["member", "applicant"],
    permission: "member.material_submit",
  });
  const schoolAccess = user.role === "school_admin" && hasPermission(session, "admin.review");
  const meetingReview = meetingAccess && hasPermission(session, "meeting.review") && hasPermission(session, "admin.review");
  const canReview = !platform && !self && (meetingReview || schoolAccess);
  const workRoute = platform
    ? "dashboard"
    : materialAccess
      ? "self-materials"
      : canAccess(session, { id: "reviews", permission: "admin.review" })
        ? "reviews"
        : meetingAccess
          ? "meetings"
          : "dashboard";

  const orgName = (record) => {
    const orgId = record.orgId || record.org_unit_id;
    return record.organization || record.org_name ||
      (tenant === "school-1" ? units.find((item) => item.id === orgId)?.name : null) ||
      organization;
  };
  const meetings = meetingAccess
    ? records(data.meetings).filter(
        (item) => tenantOf(item) === tenant && recordInScope(user, item),
      )
    : [];
  const schoolItems = schoolAccess
    ? records(data.schoolWorkItems).filter((item) => tenantOf(item) === tenant)
    : [];
  const materials = materialAccess
    ? records(data.personalMaterials).filter(
        (item) => item.owner_id === user.id && (!item.tenant_id || item.tenant_id === tenant),
      )
    : [];
  const meetingItem = (item) => ({
    id: item.id,
    title: item.title || "组织生活记录",
    organization: orgName(item),
    status: statusLabel(item),
    route: "meetings",
    params: { id: item.id },
  });
  const schoolItem = (item) => ({
    id: item.id,
    title: item.title || "学校业务事项",
    organization: orgName(item),
    status: statusLabel(item),
    route: "reviews",
    params: { recordId: item.id, year: item.year || "", status: "" },
  });
  const materialItem = (item) => ({
    id: item.id,
    title: item.title || "个人材料",
    organization,
    status: ({ submitted: "已提交", returned: "待补充", rejected: "已退回", approved: "已通过" }[item.status] || item.status || "已提交"),
    route: "self-materials",
  });
  const pendingItems = [
    ...meetings.filter((item) => meetingReview && statusLabel(item) === "待审核" && item.submitted_by !== user.id).map(meetingItem),
    ...schoolItems.filter((item) => item.status === "待审核" && item.submittedBy !== user.id).map(schoolItem),
  ];
  const submittedItems = [
    ...meetings.filter((item) => item.submitted_by === user.id).map(meetingItem),
    ...schoolItems.filter((item) => item.submittedBy === user.id).map(schoolItem),
    ...materials.map(materialItem),
  ];
  const returnedItems = submittedItems.filter((item) => returnedStatus(item.status));
  const unique = (items) => [...new Map(items.filter((item) => item.id).map((item) => [item.id, item])).values()];
  const items = unique([...pendingItems, ...returnedItems, ...submittedItems]).slice(0, 3);
  const resourceRecords = [...meetings, ...schoolItems];
  const recentAll = records(data.auditEntries)
    .filter((entry) => entry.user_id === user.id && tenantOf(entry) === tenant)
    .sort((a, b) => timeValue(b.created_at) - timeValue(a.created_at))
    .map((entry) => ({
      id: entry.id,
      title: entry.action || "业务操作",
      organization: orgName(resourceRecords.find((item) => item.id === entry.resource_id) || entry),
      createdAt: entry.created_at || "",
      tone: entry.result && entry.result !== "success" || /失败|拒绝/.test(entry.action || "")
        ? "red"
        : /退回/.test(entry.action || "")
          ? "orange"
          : /通过|归档/.test(entry.action || "")
            ? "green"
            : "blue",
    }));
  const ownSessions = records(data.platform?.sessions)
    .filter((item) => item.user_id === user.id && tenantOf(item) === tenant)
    .map((item) => item.created_at)
    .filter((value) => timeValue(value) > 0)
    .sort((a, b) => timeValue(b) - timeValue(a));

  return {
    organization,
    scope,
    pending: unique(pendingItems).length,
    submitted: unique(submittedItems).length,
    returned: unique(returnedItems).length,
    pendingItems: unique(pendingItems),
    submittedItems: unique(submittedItems),
    returnedItems: unique(returnedItems),
    items,
    recent: recentAll.slice(0, 3),
    recentAll,
    lastLogin: ownSessions[0] || null,
    workRoute,
    canReview,
  };
}
