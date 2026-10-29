import { DEPARTMENTS, organizations, notices as schoolNotices, seedKnowledge } from "./data.js";
const seedDocumentIds = new Set(seedKnowledge.map((doc) => doc.id));

export const PUBLICATION_TABS = [
  { id: "all", label: "全部" },
  { id: "publicity", label: "公示事项" },
  { id: "notice", label: "通知公告" },
  { id: "document", label: "制度文件" },
];

export function publicationToday(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const part = (name) => parts.find((p) => p.type === name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function validDay(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function noticeIsPublished(record, today = publicationToday()) {
  if (record?.kind !== "notice" || record.status !== "published") return false;
  const body = record.body || {};
  const start = body.starts_on, end = body.expires_on;
  if ((start && !validDay(start)) || (end && !validDay(end))) return false;
  if (body.category === "publicity" && (!start || !end)) return false;
  return !(start && start > today) && !(end && end < today) && !(start && end && start > end);
}

export function validatePublicationDraft(values, organizationIds) {
  const title = String(values.title || "").trim(), content = String(values.content || "").trim();
  if (!title || title.length > 200) throw new Error("请填写200字以内的标题。");
  if (!content || content.length > 10000) throw new Error("请填写10000字以内的正文。");
  if (!["notice", "publicity"].includes(values.category)) throw new Error("请选择通知或公示事项。");
  if (!organizationIds.includes(values.org_unit_id)) throw new Error("接收组织不在本校授权范围内。");
  const starts_on = values.starts_on || null, expires_on = values.expires_on || null;
  if ((starts_on && !validDay(starts_on)) || (expires_on && !validDay(expires_on))) throw new Error("请填写有效的展示日期。");
  if (values.category === "publicity" && (!starts_on || !expires_on)) throw new Error("公示事项须填写开始日期和截至日期。");
  if (starts_on && expires_on && starts_on > expires_on) throw new Error("展示截至日期不能早于开始日期。");
  return { category: values.category, title, content, org_unit_id: values.org_unit_id, starts_on, expires_on };
}

export function publicationFileOwner(record) {
  return `${record.tenant_id}:publication:${record.id}`;
}

export function canDownloadDemoPublicationFile(user, record, evidence, today = publicationToday()) {
  return noticeIsPublished(record, today) && canReadDemoPublication(user, record) && !!evidence?.has_file &&
    !!evidence.local_file_id && evidence.local_owner_id === publicationFileOwner(record) &&
    (record.body?.evidence || []).some((entry) => entry.local_file_id === evidence.local_file_id && entry.local_owner_id === evidence.local_owner_id);
}

function orgInfo(id) {
  if (id === "school-1") return { name: "学校党委", scope: "全校" };
  const department = /^dept-(\d+)$/.exec(id || "");
  if (department && DEPARTMENTS[Number(department[1])]) return { name: `${DEPARTMENTS[Number(department[1])]}党委`, scope: "本院系" };
  const branch = organizations.find((o) => o.id === id);
  return branch ? { name: branch.name, scope: "本支部" } : { name: "所属党组织", scope: "组织授权范围" };
}

function pathForOrganization(orgId, tenantId) {
  if (!orgId) return [];
  if (orgId === tenantId) return [tenantId];
  const department = /^dept-(\d+)$/.exec(orgId);
  if (department && DEPARTMENTS[Number(department[1])]) return [orgId, tenantId];
  const branch = organizations.find((o) => o.id === orgId);
  if (!branch) return [orgId];
  const index = DEPARTMENTS.indexOf(branch.department);
  return [orgId, `dept-${index}`, tenantId];
}

// A notice addressed to an ancestor reaches its descendants. Administrators may
// also inspect publications in the organizations they manage, within one tenant.
export function canReadDemoPublication(user, record) {
  if (!user || !["school_admin", "department_admin", "branch_secretary", "organizer", "member", "applicant"].includes(user.role) || !record?.tenant_id || record.tenant_id !== user.tenant_id) return false;
  const target = record.org_unit_id || (record.visibility === "school" || record.visibility === "public" ? record.tenant_id : null);
  if (!target) return false;
  if (user.role === "school_admin") return true;
  const userPath = pathForOrganization(user.org_unit_id, user.tenant_id);
  if (userPath.includes(target)) return true;
  return user.role === "department_admin" && pathForOrganization(target, record.tenant_id).includes(user.org_unit_id);
}

export function normalizeNotice(record) {
  const body = record.body || {}, org = orgInfo(record.org_unit_id);
  return {
    id: `notice:${record.id}`, recordId: record.id, source: "notice",
    category: body.category === "publicity" ? "publicity" : "notice",
    title: record.title, issuer: body.issuer || record.organization_name || org.name,
    scope: body.scope_label || body.organization_name || org.scope, publishedOn: String(record.published_at || record.updated_at || record.created_at || "").slice(0, 10),
    startsOn: body.starts_on || "", expiresOn: body.expires_on || "", content: body.content || "",
    attachments: Array.isArray(body.evidence) ? body.evidence : [], pinned: !!body.pinned, raw: record,
  };
}

export function documentIsPublished(doc, today = publicationToday()) {
  return doc?.review_status === "published" && ["effective", "现行有效"].includes(doc.status) &&
    (!doc.validity || doc.validity === "effective") &&
    (!doc.effective_date || doc.effective_date <= today) && (!doc.expiration_date || doc.expiration_date >= today);
}

export function normalizeDocument(doc) {
  return {
    id: `document:${doc.doc_id || doc.id}`, recordId: doc.doc_id || doc.id, source: "document", category: "document",
    title: doc.title, issuer: doc.issuer || "文件发布单位", scope: ({ public: "公开资料", school: "全校", department: "本院系", branch: "本支部" })[doc.visibility] || "组织授权范围",
    publishedOn: doc.effective_date || doc.date || "", startsOn: "", expiresOn: "", content: doc.summary || "",
    attachments: doc.file_name ? [{ doc_id: doc.doc_id || doc.id, revision: doc.content_revision || 1, title: doc.title, file_name: doc.file_name, has_file: doc.has_file !== false }] : [],
    pinned: false, raw: doc,
  };
}

export function filterPublications(items, { category = "all", query = "" } = {}) {
  const term = query.trim().toLocaleLowerCase();
  return items.filter((item) => (category === "all" || item.category === category) && (!term || `${item.title} ${item.issuer}`.toLocaleLowerCase().includes(term)))
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || Number(b.category === "publicity") - Number(a.category === "publicity") || b.publishedOn.localeCompare(a.publishedOn) || a.id.localeCompare(b.id));
}

export function seedPublications() {
  return [
    { id: "publicity-school-202610", kind: "notice", status: "published", tenant_id: "school-1", org_unit_id: "school-1", title: "2026年下半年拟接收预备党员公示", created_at: "2026-10-26T09:00:00+08:00", body: { category: "publicity", pinned: true, starts_on: "2026-10-26", expires_on: "2026-10-30", content: "本期拟接收预备党员名单由所属组织核对后公示。请在公示期内向所属组织了解公示内容及意见反馈方式。名单原件尚未上传，请联系发布组织查阅。" } },
    { id: "publicity-department-202610", kind: "notice", status: "published", tenant_id: "school-1", org_unit_id: "dept-10", title: "土木工程学院优秀党员拟推荐名单公示", created_at: "2026-10-27T09:00:00+08:00", body: { category: "publicity", starts_on: "2026-10-27", expires_on: "2026-10-31", content: "拟推荐情况按本院工作安排公示。具体名单及意见反馈方式请向学院党组织查阅；公示记录不代替组织正式认定。" } },
    { id: "notice-branch-202610", kind: "notice", status: "published", tenant_id: "school-1", org_unit_id: "org-10-3", title: "关于开展10月主题党日活动的通知", created_at: "2026-10-27T10:00:00+08:00", body: { category: "notice", content: "请本支部党员关注组织发布的活动安排，具体时间、地点及准备要求以支部确认的信息为准。" } },
    ...schoolNotices.map((n) => ({ id: `school-notice-${n.id}`, kind: "notice", status: "published", tenant_id: "school-1", org_unit_id: "school-1", title: n.title, created_at: `2026-${n.date}T09:00:00+08:00`, body: { category: "notice", content: n.body } })),
  ];
}

export function demoPublications(data, session, today = publicationToday()) {
  const user = session?.user;
  if (!user) return [];
  const noticeRows = [...new Map([...seedPublications(), ...(data.publications || [])].map((n) => [n.id, n])).values()].filter((n) => noticeIsPublished(n, today) && canReadDemoPublication(user, n)).map(normalizeNotice);
  const documents = (data.knowledge || []).map((doc) => {
    const original = seedDocumentIds.has(doc.id);
    return { ...doc, tenant_id: doc.tenant_id || (original ? "school-1" : null), visibility: doc.visibility || (doc.level === "公开" ? "public" : "school"), org_unit_id: doc.org_unit_id || (original ? "school-1" : null), review_status: doc.review_status || (original && doc.status === "现行有效" ? "published" : "pending"), has_file: false };
  }).filter((doc) => documentIsPublished(doc, today) && canReadDemoPublication(user, doc)).map(normalizeDocument);
  return filterPublications([...noticeRows, ...documents]);
}
