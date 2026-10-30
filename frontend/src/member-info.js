import { DEMO_PERSONAS, recordInScope } from "./roles.js";
import { organizations, seedMembers } from "./data.js";

export const INFO_STATUS = {
  draft: { label: "草稿", tone: "gray" },
  submitted: { label: "待支部初核", tone: "orange" },
  branch_approved: { label: "待院系复核", tone: "blue" },
  department_approved: { label: "待学校备案", tone: "blue" },
  archived: { label: "已备案", tone: "green" },
  returned: { label: "已退回", tone: "orange" },
};

export const INFO_STATUS_ORDER = [
  "draft",
  "submitted",
  "branch_approved",
  "department_approved",
  "archived",
  "returned",
];

export const STAGE_CODE_BY_LABEL = {
  入党申请人: "applicant",
  入党积极分子: "activist",
  发展对象: "candidate",
  预备党员: "probationary",
  正式党员: "member",
};

export const STAGE_LABEL_BY_CODE = {
  applicant: "入党申请人",
  activist: "入党积极分子",
  candidate: "发展对象",
  probationary: "预备党员",
  member: "正式党员",
  rejected: "退回",
};

export const SELF_FIELD_KEYS = [
  "gender",
  "ethnicity",
  "education_code",
  "mobile",
  "phone_area",
  "phone_number",
  "address",
  "lost_contact",
  "lost_contact_on",
  "floating",
  "floating_province",
  "floating_city",
  "floating_county",
];

export const BRANCH_FIELD_KEYS = [
  "join_party_on",
  "full_member_on",
  "job_code",
  "party_status",
  "filing_type",
  "supplement_reason",
  "relation_transfer",
  "transfer_branch",
];

export const ALL_FIELD_KEYS = [...SELF_FIELD_KEYS, ...BRANCH_FIELD_KEYS];

export const INFO_FIELD_LABELS = {
  gender: "性别",
  ethnicity: "民族",
  education_code: "学历代码",
  mobile: "手机号",
  phone_area: "固定电话区号",
  phone_number: "固定电话号码",
  address: "家庭住址",
  lost_contact: "是否失联党员",
  lost_contact_on: "失去联系日期",
  floating: "是否流动党员",
  floating_province: "外出流向省份",
  floating_city: "外出流向城市",
  floating_county: "外出流向县区",
  join_party_on: "加入党组织日期",
  full_member_on: "转为正式党员日期",
  job_code: "工作岗位代码",
  party_status: "党籍状态",
  filing_type: "填报类型",
  supplement_reason: "补录原因",
  relation_transfer: "是否转接组织关系",
  transfer_branch: "转入组织关系支部全称",
};

export function stageCode(stage) {
  return STAGE_CODE_BY_LABEL[stage] || stage || "";
}

export function stageLabel(stage) {
  return STAGE_LABEL_BY_CODE[stageCode(stage)] || "未登记";
}

export function personCategory(stage) {
  const code = stageCode(stage);
  if (code === "probationary") return "预备党员";
  if (code === "member") return "正式党员";
  return "尚未成为预备党员";
}

export function isEligibleProfile(profile) {
  return ["probationary", "member"].includes(stageCode(profile?.stage));
}

export function emptyInfoPayload() {
  return {
    gender: "",
    ethnicity: "",
    education_code: "",
    mobile: "",
    phone_area: "",
    phone_number: "",
    address: "",
    lost_contact: false,
    lost_contact_on: "",
    floating: false,
    floating_province: "",
    floating_city: "",
    floating_county: "",
    join_party_on: "",
    full_member_on: "",
    job_code: "",
    party_status: "",
    filing_type: "",
    supplement_reason: "",
    relation_transfer: null,
    transfer_branch: "",
  };
}

export function normalizeInfoPayload(payload = {}) {
  return { ...emptyInfoPayload(), ...payload };
}

export function infoStatusLabel(status) {
  return INFO_STATUS[status]?.label || "未填写";
}

export function infoStatusTone(status) {
  return INFO_STATUS[status]?.tone || "gray";
}

export function infoProfile(profile) {
  if (!profile) return null;
  return {
    id: profile.id,
    name: profile.name,
    org_name: profile.organization || profile.org_name || "未登记",
    org_unit_id: profile.orgId || profile.org_unit_id || "",
    department: profile.department || "",
    stage: stageCode(profile.stage),
    stage_label: stageLabel(profile.stage),
    id_card_masked: profile.id_card_masked || "档案未登记",
    birth_date: profile.birth_date || "",
    stage_joined_on: profile.joined || profile.stage_joined_on || "",
    person_category: personCategory(profile.stage),
  };
}

export function infoProfileFromCollection(collection) {
  return {
    id: collection.profile_id,
    name: collection.member_name,
    org_name: collection.org_name,
    org_unit_id: collection.org_unit_id,
    department: collection.department,
    stage: collection.member_stage,
    stage_label: stageLabel(collection.member_stage),
    id_card_masked: collection.id_card_masked || "档案未登记",
    birth_date: collection.birth_date || "",
    stage_joined_on: collection.stage_joined_on || "",
    person_category: personCategory(collection.member_stage),
  };
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function validDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
}

function textError(errors, key, value, label, min = 1, max = 200) {
  const text = String(value || "").trim();
  if (!text) errors[key] = `请填写${label}`;
  else if (text.length < min) errors[key] = `${label}至少填写${min}个字`;
  else if (text.length > max) errors[key] = `${label}不能超过${max}个字`;
}

export function validateSelfInfo(payload) {
  const values = normalizeInfoPayload(payload);
  const errors = {};
  if (!["male", "female"].includes(values.gender))
    errors.gender = "请选择性别";
  textError(errors, "ethnicity", values.ethnicity, "民族", 1, 30);
  textError(errors, "education_code", values.education_code, "学历代码", 1, 10);
  if (
    values.education_code &&
    !/^[0-9A-Za-z]{1,10}$/.test(String(values.education_code).trim())
  )
    errors.education_code = "学历代码只能填写数字或字母";

  const mobile = String(values.mobile || "").trim();
  const area = String(values.phone_area || "").trim();
  const number = String(values.phone_number || "").trim();
  if (mobile && !/^1[3-9]\d{9}$/.test(mobile))
    errors.mobile = "请填写有效的 11 位手机号";
  if (area || number) {
    if (!/^\d{3,4}$/.test(area)) errors.phone_area = "区号应为 3 至 4 位数字";
    if (!/^\d{7,8}$/.test(number))
      errors.phone_number = "固定电话号码应为 7 至 8 位数字";
  }
  if (!mobile && !(area && number))
    errors.mobile = "手机号或固定电话至少填写一项";

  textError(errors, "address", values.address, "家庭住址", 2, 200);

  if (typeof values.lost_contact !== "boolean")
    errors.lost_contact = "请选择是否失联";
  if (values.lost_contact) {
    if (!validDate(values.lost_contact_on))
      errors.lost_contact_on = "请选择失去联系日期";
    else if (values.lost_contact_on > todayIso())
      errors.lost_contact_on = "失去联系日期不能晚于今天";
  }

  if (typeof values.floating !== "boolean")
    errors.floating = "请选择是否流动";
  if (values.floating) {
    textError(errors, "floating_province", values.floating_province, "外出流向省份", 1, 50);
    textError(errors, "floating_city", values.floating_city, "外出流向城市", 1, 50);
    textError(errors, "floating_county", values.floating_county, "外出流向县区", 1, 50);
  }
  return errors;
}

export function validateCompleteInfo(payload, profile) {
  const values = normalizeInfoPayload(payload);
  const errors = validateSelfInfo(values);
  const code = stageCode(profile?.stage);

  if (!validDate(values.join_party_on))
    errors.join_party_on = "请填写加入党组织日期";
  else if (values.join_party_on > todayIso())
    errors.join_party_on = "加入党组织日期不能晚于今天";

  if (code === "member") {
    if (!validDate(values.full_member_on))
      errors.full_member_on = "正式党员须填写转为正式党员日期";
    else if (values.full_member_on > todayIso())
      errors.full_member_on = "转正日期不能晚于今天";
  } else if (values.full_member_on) {
    errors.full_member_on = "预备党员不填写转为正式党员日期";
  }

  if (
    validDate(values.join_party_on) &&
    validDate(values.full_member_on) &&
    values.full_member_on < values.join_party_on
  )
    errors.full_member_on = "转正日期不能早于加入党组织日期";

  const birth = profile?.birth_date || "";
  if (
    validDate(birth) &&
    validDate(values.join_party_on) &&
    values.join_party_on < birth
  )
    errors.join_party_on = "加入党组织日期不能早于出生日期";

  textError(errors, "job_code", values.job_code, "工作岗位代码", 1, 10);
  if (values.job_code && !/^[0-9A-Za-z]{1,10}$/.test(String(values.job_code).trim()))
    errors.job_code = "工作岗位代码只能填写数字或字母";

  if (!["normal", "suspended"].includes(values.party_status))
    errors.party_status = "请选择党籍状态";
  if (!["new", "supplement"].includes(values.filing_type))
    errors.filing_type = "请选择填报类型";
  if (values.filing_type === "supplement")
    textError(errors, "supplement_reason", values.supplement_reason, "补录原因", 2, 500);

  if (typeof values.relation_transfer !== "boolean")
    errors.relation_transfer = "请选择是否转接组织关系";
  if (values.relation_transfer)
    textError(errors, "transfer_branch", values.transfer_branch, "转入组织关系支部全称", 2, 200);

  return errors;
}

export function validationMessage(errors) {
  const first = Object.values(errors || {})[0];
  return first || "请检查填写内容";
}

function mergeKeys(payload, source, keys) {
  const next = normalizeInfoPayload(payload);
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source || {}, key))
      next[key] = source[key];
  }
  return next;
}

export function mergeSelfPayload(payload, source) {
  return mergeKeys(payload, source, SELF_FIELD_KEYS);
}

export function mergeBranchPayload(payload, source) {
  return mergeKeys(payload, source, ALL_FIELD_KEYS);
}

function historyEvent(action, actor, status, at, opinion = "", version = null) {
  return {
    action,
    actor: actor?.name || "系统",
    role: actor?.role || "",
    status,
    opinion: String(opinion || "").trim(),
    at,
    ...(version == null ? {} : { version }),
  };
}

export function createInfoCollection(profile, actor, now = new Date().toISOString()) {
  const org = organizations.find(
    (item) => item.id === (profile.orgId || profile.org_unit_id),
  );
  const stage = stageCode(profile.stage);
  return {
    id: crypto.randomUUID(),
    profile_id: profile.id,
    user_id: profile.user_id || actor?.id || null,
    member_name: profile.name,
    member_stage: stage,
    member_stage_label: stageLabel(stage),
    org_unit_id: profile.orgId || profile.org_unit_id || org?.id || "",
    org_name: profile.organization || profile.org_name || org?.name || "未登记",
    department: profile.department || org?.department || "",
    tenant_id: profile.tenant_id || actor?.tenant_id || "school-1",
    id_card_masked: profile.id_card_masked || "",
    birth_date: profile.birth_date || "",
    stage_joined_on: profile.joined || profile.stage_joined_on || "",
    status: "draft",
    version: 0,
    payload: emptyInfoPayload(),
    history: [],
    collector_name: "",
    member_confirmed_at: null,
    submitted_at: null,
    branch_reviewed_at: null,
    branch_reviewed_by_name: "",
    branch_opinion: "",
    department_reviewed_at: null,
    department_reviewed_by_name: "",
    department_opinion: "",
    archived_at: null,
    archived_by_name: "",
    returned_at: null,
    returned_by_name: "",
    return_reason: "",
    return_stage: "",
    created_at: now,
    updated_at: now,
  };
}

export function selfInfoCollection(data, session) {
  const profileId = session?.user?.profile_id;
  if (!profileId) return null;
  return (
    (data.memberInfoCollections || []).find(
      (item) =>
        item.profile_id === profileId &&
        item.tenant_id === (session.user.tenant_id || "school-1"),
    ) || null
  );
}

export function scopedInfoCollections(data, session) {
  return (data.memberInfoCollections || [])
    .filter((item) => recordInScope(session?.user, item))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

export function infoCollectionById(data, id) {
  return (data.memberInfoCollections || []).find((item) => item.id === id) || null;
}

export function infoCounts(collections) {
  const counts = Object.fromEntries(INFO_STATUS_ORDER.map((status) => [status, 0]));
  for (const item of collections) {
    if (counts[item.status] == null) counts[item.status] = 0;
    counts[item.status] += 1;
  }
  return counts;
}

function findProfile(data, profileId) {
  return (data.members || []).find((member) => member.id === profileId);
}

function ensureSelfCollection(data, session, now) {
  const profile = findProfile(data, session.user.profile_id);
  if (!profile) throw new Error("当前账号尚未关联本人档案，请联系组织管理员。");
  if (!isEligibleProfile(profile))
    throw new Error("成为预备党员后，才需要填写党员基本信息采集表。");
  let collection = selfInfoCollection(data, session);
  if (!collection) {
    collection = createInfoCollection(profile, session.user, now);
    collection.payload = mergeSelfPayload(collection.payload, {
      gender: profile.gender === "男" ? "male" : profile.gender === "女" ? "female" : "",
    });
  }
  return { profile, collection };
}

export function saveSelfInfo(data, session, payload, now = new Date().toISOString()) {
  if (session?.user?.role !== "member")
    throw new Error("仅党员本人可以填写基本信息采集表。");
  const { profile, collection } = ensureSelfCollection(data, session, now);
  if (!["draft", "returned"].includes(collection.status))
    throw new Error("当前采集表已提交，不能直接修改。");
  const next = {
    ...collection,
    payload: mergeSelfPayload(collection.payload, payload),
    updated_at: now,
  };
  const collections = (data.memberInfoCollections || []).some(
    (item) => item.id === next.id,
  )
    ? data.memberInfoCollections.map((item) =>
        item.id === next.id ? next : item,
      )
    : [next, ...(data.memberInfoCollections || [])];
  return { collections, profile, collection: next };
}

export function submitSelfInfo(
  data,
  session,
  payload,
  confirmed,
  now = new Date().toISOString(),
) {
  if (session?.user?.role !== "member")
    throw new Error("仅党员本人可以提交基本信息采集表。");
  const { profile, collection } = ensureSelfCollection(data, session, now);
  if (!["draft", "returned"].includes(collection.status))
    throw new Error("当前采集表已提交，不能重复提交。");
  const merged = mergeSelfPayload(collection.payload, payload);
  const errors = validateSelfInfo(merged);
  if (Object.keys(errors).length) throw new Error(validationMessage(errors));
  if (!confirmed) throw new Error("请先勾选本人确认。");
  const version = (collection.version || 0) + 1;
  const next = {
    ...collection,
    payload: merged,
    status: "submitted",
    version,
    submitted_at: now,
    member_confirmed_at: now,
    updated_at: now,
    history: [
      ...(collection.history || []),
      historyEvent("submit", session.user, "submitted", now, "本人确认提交", version),
    ],
  };
  const current = data.memberInfoCollections || [];
  const collections = current.some((item) => item.id === next.id)
    ? current.map((item) => (item.id === next.id ? next : item))
    : [next, ...current];
  return { collections, profile, collection: next };
}

export function canEditBranchInfo(session, collection, checkScope = true) {
  return (
    !!collection &&
    ["organizer", "branch_secretary"].includes(session?.user?.role) &&
    collection.status === "submitted" &&
    (!checkScope || recordInScope(session?.user, collection))
  );
}

export function saveBranchInfo(
  data,
  session,
  id,
  payload,
  now = new Date().toISOString(),
) {
  const collection = infoCollectionById(data, id);
  if (!collection) throw new Error("采集表不存在，请刷新后重试。");
  if (!canEditBranchInfo(session, collection))
    throw new Error("当前账号不能补录这份采集表。");
  const next = {
    ...collection,
    payload: mergeBranchPayload(collection.payload, payload),
    updated_at: now,
    history: [
      ...(collection.history || []),
      historyEvent("branch_save", session.user, collection.status, now, "支部补录核对"),
    ],
  };
  return data.memberInfoCollections.map((item) =>
    item.id === id ? next : item,
  );
}

export function reviewInfoCollection(
  data,
  session,
  id,
  action,
  opinion,
  payload = null,
  now = new Date().toISOString(),
) {
  const collection = infoCollectionById(data, id);
  if (!collection) throw new Error("采集表不存在，请刷新后重试。");
  if (!recordInScope(session?.user, collection))
    throw new Error("这份采集表不在当前账号的办理范围内。");
  const role = session?.user?.role;
  const text = String(opinion || "").trim();
  if (!text) throw new Error("请填写处理意见。");
  if (action === "return") {
    if (!["submitted", "branch_approved", "department_approved"].includes(collection.status))
      throw new Error("当前状态不能退回。");
    const allowed =
      (role === "branch_secretary" && collection.status === "submitted") ||
      (role === "department_admin" && collection.status === "branch_approved") ||
      (role === "school_admin" && collection.status === "department_approved");
    if (!allowed) throw new Error("当前账号不能退回这份采集表。");
    const next = {
      ...collection,
      payload: payload ? mergeBranchPayload(collection.payload, payload) : collection.payload,
      status: "returned",
      returned_at: now,
      returned_by_name: session.user.name,
      return_reason: text,
      return_stage: collection.status,
      updated_at: now,
      history: [
        ...(collection.history || []),
        historyEvent("return", session.user, "returned", now, text, collection.version),
      ],
    };
    return data.memberInfoCollections.map((item) => (item.id === id ? next : item));
  }

  if (action === "archive") {
    if (role !== "school_admin" || collection.status !== "department_approved")
      throw new Error("只有学校管理员可以对院系复核通过的采集表备案。");
    const next = {
      ...collection,
      payload: payload ? mergeBranchPayload(collection.payload, payload) : collection.payload,
      status: "archived",
      archived_at: now,
      archived_by_name: session.user.name,
      updated_at: now,
      history: [
        ...(collection.history || []),
        historyEvent("archive", session.user, "archived", now, text, collection.version),
      ],
    };
    return data.memberInfoCollections.map((item) => (item.id === id ? next : item));
  }

  if (action !== "approve") throw new Error("处理决定无效。");
  const nextPayload = payload
    ? mergeBranchPayload(collection.payload, payload)
    : collection.payload;
  if (role === "branch_secretary" && collection.status === "submitted") {
    const errors = validateCompleteInfo(nextPayload, {
      stage: collection.member_stage,
      birth_date: collection.birth_date,
    });
    if (Object.keys(errors).length)
      throw new Error("请先补全支部信息：" + validationMessage(errors));
    const next = {
      ...collection,
      payload: nextPayload,
      status: "branch_approved",
      branch_reviewed_at: now,
      branch_reviewed_by_name: session.user.name,
      branch_opinion: text,
      collector_name: collection.collector_name || session.user.name,
      updated_at: now,
      history: [
        ...(collection.history || []),
        historyEvent("branch_approve", session.user, "branch_approved", now, text, collection.version),
      ],
    };
    return data.memberInfoCollections.map((item) => (item.id === id ? next : item));
  }
  if (role === "department_admin" && collection.status === "branch_approved") {
    const next = {
      ...collection,
      payload: nextPayload,
      status: "department_approved",
      department_reviewed_at: now,
      department_reviewed_by_name: session.user.name,
      department_opinion: text,
      updated_at: now,
      history: [
        ...(collection.history || []),
        historyEvent("department_approve", session.user, "department_approved", now, text, collection.version),
      ],
    };
    return data.memberInfoCollections.map((item) => (item.id === id ? next : item));
  }
  throw new Error("当前账号不能审核这份采集表。");
}

export function canReviewInfo(session, collection, checkScope = true) {
  if (!collection || (checkScope && !recordInScope(session?.user, collection)))
    return false;
  const role = session?.user?.role;
  return (
    (role === "branch_secretary" && collection.status === "submitted") ||
    (role === "department_admin" && collection.status === "branch_approved") ||
    (role === "school_admin" && collection.status === "department_approved")
  );
}

export function reviewActionLabel(session, collection) {
  if (!collection) return "";
  if (session?.user?.role === "school_admin") return "备案归档";
  if (session?.user?.role === "department_admin") return "复核通过";
  return "初核通过";
}

function seedPayload(profile, overrides = {}) {
  return normalizeInfoPayload({
    gender: profile.gender === "女" ? "female" : "male",
    ethnicity: "汉族",
    education_code: "22",
    mobile: "13800001234",
    phone_area: "",
    phone_number: "",
    address: "示范大学学生公寓 1 栋 101",
    lost_contact: false,
    floating: false,
    join_party_on: "2021-06-01",
    full_member_on: profile.stage === "预备党员" ? "" : "2022-06-01",
    job_code: "321",
    party_status: "normal",
    filing_type: "new",
    relation_transfer: false,
    ...overrides,
  });
}

export function seedDemoInfoCollections() {
  const organizer = DEMO_PERSONAS.find((item) => item.id === "organizer")?.user;
  const branch = organizations.find((item) => item.id === organizer?.org_unit_id);
  if (!organizer || !branch) return [];
  const personas = new Set(DEMO_PERSONAS.map((item) => item.user.profile_id));
  const candidates = seedMembers.filter(
    (member) =>
      member.orgId === branch.id &&
      ["预备党员", "正式党员"].includes(member.stage) &&
      !personas.has(member.id),
  );
  const teacher = seedMembers.find(
    (member) =>
      member.id === DEMO_PERSONAS.find((item) => item.id === "teacher")?.user.profile_id,
  );
  const submittedMember = candidates[0];
  const deptMember = candidates[1];
  const archivedMember = candidates[2];
  const now = "2026-10-28T09:00:00+08:00";
  const items = [];

  if (teacher) {
    const base = createInfoCollection(teacher, organizer, now);
    items.push({
      ...base,
      id: "demo-info-teacher",
      status: "returned",
      version: 1,
      payload: seedPayload(teacher, { address: "示范大学教师公寓" }),
      submitted_at: "2026-10-24T09:10:00+08:00",
      member_confirmed_at: "2026-10-24T09:10:00+08:00",
      returned_at: "2026-10-25T10:20:00+08:00",
      returned_by_name: "周书记",
      return_reason: "请补填家庭住址门牌号，并核对手机号是否本人使用。",
      return_stage: "submitted",
      updated_at: "2026-10-25T10:20:00+08:00",
      history: [
        historyEvent("submit", teacher, "submitted", "2026-10-24T09:10:00+08:00", "本人确认提交", 1),
        historyEvent("return", { name: "周书记", role: "branch_secretary" }, "returned", "2026-10-25T10:20:00+08:00", "请补填家庭住址门牌号，并核对手机号是否本人使用。", 1),
      ],
    });
  }

  if (submittedMember) {
    const base = createInfoCollection(submittedMember, organizer, now);
    items.push({
      ...base,
      id: "demo-info-submitted",
      status: "submitted",
      version: 1,
      payload: seedPayload(submittedMember),
      submitted_at: "2026-10-26T14:20:00+08:00",
      member_confirmed_at: "2026-10-26T14:20:00+08:00",
      updated_at: "2026-10-26T14:20:00+08:00",
      history: [
        historyEvent("submit", submittedMember, "submitted", "2026-10-26T14:20:00+08:00", "本人确认提交", 1),
      ],
    });
  }

  if (deptMember) {
    const base = createInfoCollection(deptMember, organizer, now);
    items.push({
      ...base,
      id: "demo-info-department",
      status: "department_approved",
      version: 1,
      payload: seedPayload(deptMember),
      submitted_at: "2026-10-22T09:00:00+08:00",
      member_confirmed_at: "2026-10-22T09:00:00+08:00",
      branch_reviewed_at: "2026-10-23T10:00:00+08:00",
      branch_reviewed_by_name: "周书记",
      branch_opinion: "信息核对无误，同意报院系复核。",
      department_reviewed_at: "2026-10-24T11:00:00+08:00",
      department_reviewed_by_name: "赵老师",
      department_opinion: "复核通过，报学校备案。",
      collector_name: "王组织员",
      updated_at: "2026-10-24T11:00:00+08:00",
      history: [
        historyEvent("submit", deptMember, "submitted", "2026-10-22T09:00:00+08:00", "本人确认提交", 1),
        historyEvent("branch_approve", { name: "周书记", role: "branch_secretary" }, "branch_approved", "2026-10-23T10:00:00+08:00", "信息核对无误，同意报院系复核。", 1),
        historyEvent("department_approve", { name: "赵老师", role: "department_admin" }, "department_approved", "2026-10-24T11:00:00+08:00", "复核通过，报学校备案。", 1),
      ],
    });
  }

  if (archivedMember) {
    const base = createInfoCollection(archivedMember, organizer, now);
    items.push({
      ...base,
      id: "demo-info-archived",
      status: "archived",
      version: 2,
      payload: seedPayload(archivedMember),
      submitted_at: "2026-09-20T09:00:00+08:00",
      member_confirmed_at: "2026-09-20T09:00:00+08:00",
      branch_reviewed_at: "2026-09-21T10:00:00+08:00",
      branch_reviewed_by_name: "周书记",
      branch_opinion: "信息核对无误。",
      department_reviewed_at: "2026-09-22T11:00:00+08:00",
      department_reviewed_by_name: "赵老师",
      department_opinion: "复核通过。",
      archived_at: "2026-09-23T15:00:00+08:00",
      archived_by_name: "李老师",
      collector_name: "王组织员",
      updated_at: "2026-09-23T15:00:00+08:00",
      history: [
        historyEvent("submit", archivedMember, "submitted", "2026-09-20T09:00:00+08:00", "本人确认提交", 2),
        historyEvent("branch_approve", { name: "周书记", role: "branch_secretary" }, "branch_approved", "2026-09-21T10:00:00+08:00", "信息核对无误。", 2),
        historyEvent("department_approve", { name: "赵老师", role: "department_admin" }, "department_approved", "2026-09-22T11:00:00+08:00", "复核通过。", 2),
        historyEvent("archive", { name: "李老师", role: "school_admin" }, "archived", "2026-09-23T15:00:00+08:00", "同意备案。", 2),
      ],
    });
  }

  return items;
}
