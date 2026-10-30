import { DEMO_PERSONAS, accountOrganizations } from "./roles.js";
import { seedMembers } from "./data.js";
import { buildSchoolData } from "./school-data.js";
import { extendPlatformData } from "./platform-data.js";
import { seedDemoInfoCollections } from "./member-info.js";
export function roleSeed() {
  const organizer = DEMO_PERSONAS.find((p) => p.id === "organizer").user;
  const student = DEMO_PERSONAS.find((p) => p.id === "student").user;
  const applicant = DEMO_PERSONAS.find((p) => p.id === "applicant").user;
  return {
    ...buildSchoolData(),
    personalMaterials: [
      {
        id: "demo-material-student",
        owner_id: student.id,
        profile_id: student.profile_id,
        title: "10月学习心得",
        category: "study_note",
        description: "围绕本月专题学习记录个人体会，原件尚未提交。",
        file_name: "学习心得.txt",
        file_size: 1024,
        created_at: "2026-10-20T10:00:00+08:00",
        status: "submitted",
        has_file: false,
      },
      {
        id: "demo-material-applicant",
        owner_id: applicant.id,
        profile_id: applicant.profile_id,
        title: "入党申请阶段材料",
        category: "other",
        description: "按所在支部要求登记材料，原件尚未提交。",
        file_name: "个人材料.pdf",
        file_size: 12000,
        created_at: "2026-10-21T10:00:00+08:00",
        status: "submitted",
        has_file: false,
      },
    ],
    materialReceipts: [],
    memberInfoCollections: seedDemoInfoCollections(),
    developmentProfiles: {},
    accounts: DEMO_PERSONAS.map((p) => ({
      ...p.user,
      is_active: true,
      org_name:
        accountOrganizations().find((o) => o.id === p.user.org_unit_id)?.name ||
        "平台级账号",
    })),
    tenants: [
      {
        id: "platform-1",
        name: "高校党建管理平台",
        tenant_type: "platform",
        parent_id: null,
        is_active: true,
      },
      {
        id: "school-1",
        name: "示范大学",
        tenant_type: "school",
        parent_id: "platform-1",
        is_active: true,
      },
    ],
    auditEntries: [
      {
        id: "audit-seed",
        user_id: organizer.id,
        user_name: organizer.name,
        action: "登记组织生活",
        resource_type: "meeting",
        resource_id: "role-meeting-1",
        data_level: "internal",
        result: "success",
        request_id: "local-trace-001",
        created_at: "2026-10-22T10:00:00+08:00",
        orgId: organizer.org_unit_id,
      },
    ],
    roleMeeting: {
      id: "role-meeting-1",
      title: "10月支部学习交流会纪要（待审核）",
      date: "2026-10-21",
      time: "14:30",
      type: "党小组会",
      activityType: "party_group_meeting",
      host: organizer.name,
      location: "党员活动室",
      organization: accountOrganizations().find(
        (o) => o.id === organizer.org_unit_id,
      )?.name,
      orgId: organizer.org_unit_id,
      attended: 18,
      total: 19,
      status: "待审核",
      review_status: "pending",
      submitted_by: organizer.id,
      submitted_name: organizer.name,
      agenda: "1. 学习本月专题材料\n2. 交流学习心得\n3. 明确下月工作安排",
      minutes:
        "与会人员围绕学习材料开展交流，明确后续学习与服务安排。记录经审核后按学校制度归档。",
      revision: 2,
    },
  };
}
export function extendRoleData(data) {
  const defaults = roleSeed();
  const { roleMeeting, ...fields } = defaults;
  const existing = { ...fields, ...data };
  if (!data.roleDataVersion) {
    existing.meetings = [...data.meetings, roleMeeting];
    existing.roleDataVersion = 1;
  }
  return extendPlatformData(existing);
}
export const MATERIAL_CATEGORIES = {
  thought_report: "思想汇报",
  study_note: "学习心得",
  certificate: "证明材料",
  other: "其他材料",
};
export function materialSource(material) {
  if (material?.legacy_material) return "legacy";
  if (["personal", "development", "legacy"].includes(material?.source))
    return material.source;
  return material?.material_type ? "development" : "personal";
}
export function materialTypeLabel(material) {
  if (materialSource(material) === "personal")
    return `${MATERIAL_CATEGORIES[material.category] || material.title || "个人材料"}（个人提交）`;
  return material.material_type || material.title || "未分类";
}
export function materialSourceNote(material) {
  return {
    personal: "个人材料，不纳入发展材料核验",
    legacy: "历史登记，待核验原件",
    development: "组织登记",
  }[materialSource(material)];
}
export const REQUIRED_DEMO_MATERIALS = [
  "入党申请书",
  "培养考察记录",
  "党课培训证明",
];
export function getDemoDevelopment(member, stored) {
  if (stored) return stored;
  return {
    id: member.id,
    current_stage: member.stage,
    materials: REQUIRED_DEMO_MATERIALS.map((type, i) => ({
      id: `demo-dev-${member.id}-${i}`,
      material_type: type,
      file_version: "v1",
      submit_date: "2026-10-15",
      review_status: i === 0 ? "approved" : "pending",
      note: "材料清单已登记，具体要求及核验结果以组织审核为准。",
    })),
    cultivation: [],
    stage_history: [],
    procedures: emptyProcedureState(),
  };
}
export function emptyProcedureState() {
  return {
    contacts: { items: [], current: null, satisfied: false, notice: "尚未登记培养联系人" },
    introducers: { items: [], current: [], count: 0, satisfied: false, notice: "尚未登记入党介绍人" },
    branch_committee_review: { items: [], current: null, satisfied: false, notice: "尚未登记支委会审查" },
    upper_pre_review: { items: [], current: null, satisfied: false, notice: "尚未登记上级党委预审" },
    application_form: { items: [], current: null, satisfied: false, notice: "尚未登记入党志愿书" },
    upper_talk: { items: [], current: null, satisfied: false, notice: "尚未登记上级党委派人谈话" },
    requirement: "接收预备党员前应完成培养联系人、入党介绍人、支委会审查、上级党委预审和入党志愿书登记；上级党委派人谈话应在上级审批前完成。系统只登记事实，不替代组织程序。",
    data_level: "internal",
    data_level_label: "内部",
    cloud_allowed: false,
    embedding_allowed: false,
  };
}
function procedureKey(kind) {
  return kind === "contact" ? "contacts" : kind === "introducer" ? "introducers" : kind;
}
function summarizeProcedure(key, items) {
  const current = items[0] || null;
  if (key === "contacts") {
    return { items, current, satisfied: Boolean(current), notice: current ? "已登记培养联系人" : "尚未登记培养联系人" };
  }
  if (key === "introducers") {
    const latest = items.slice(0, 2);
    return {
      items,
      current: latest,
      count: latest.length,
      satisfied: latest.length > 0,
      notice: latest.length === 0 ? "尚未登记入党介绍人" : latest.length < 2 ? "已登记1名入党介绍人；细则一般由两名正式党员担任" : "已登记2名入党介绍人",
    };
  }
  if (key === "branch_committee_review") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: status === "passed",
      notice: !current ? "尚未登记支委会审查" : status === "passed" ? "支委会审查已通过" : status === "failed" ? "支委会审查未通过" : "支委会审查进行中",
    };
  }
  if (key === "upper_pre_review") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: status === "passed",
      notice: !current ? "尚未登记上级党委预审" : status === "passed" ? "上级党委预审已通过" : status === "supplement" ? "上级党委预审要求补充材料" : status === "failed" ? "上级党委预审未通过" : "上级党委预审进行中",
    };
  }
  if (key === "application_form") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: ["submitted", "reviewed"].includes(status),
      notice: !current ? "尚未登记入党志愿书" : status === "reviewed" ? "入党志愿书已审核" : status === "submitted" ? "入党志愿书已提交" : "入党志愿书正在填写",
    };
  }
  if (key === "upper_talk") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: status === "completed",
      notice: !current ? "尚未登记上级党委派人谈话" : status === "completed" ? "上级党委派人谈话已完成" : "上级党委派人谈话状态待核对",
    };
  }
  return { items, current, satisfied: false, notice: "程序状态待核对" };
}
export function addDemoProcedure(state, record) {
  const next = { ...emptyProcedureState(), ...(state || {}) };
  const key = procedureKey(record.kind);
  const group = next[key] || { items: [] };
  const items = [record, ...(group.items || [])].sort((a, b) => {
    const byDate = String(b.occurred_on || "").localeCompare(String(a.occurred_on || ""));
    if (byDate) return byDate;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });
  next[key] = summarizeProcedure(key, items);
  return next;
}
export function newAudit(user, action, type, id) {
  return {
    id: crypto.randomUUID(),
    user_id: user.id,
    user_name: user.name,
    action,
    resource_type: type,
    resource_id: id,
    data_level: "internal",
    result: "success",
    request_id: "local-" + crypto.randomUUID().slice(0, 8),
    created_at: new Date().toISOString(),
    orgId: user.org_unit_id,
    tenant_id: user.tenant_id || "school-1",
  };
}
