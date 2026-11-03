import { DEMO_PERSONAS, accountOrganizations } from "./roles.js";
import { seedActivities, seedMembers } from "./data.js";
import { buildSchoolData } from "./school-data.js";
import { extendPlatformData } from "./platform-data.js";
import { seedDemoInfoCollections } from "./member-info.js";
import { STAGE_LABELS } from "./contracts.js";
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
  // 已发布的自建活动补一条消息通知，避免旧浏览器数据在修复后仍显示“没有通知”。
  if (!data.activityNoticeVersion) {
    const seedIds = new Set(seedActivities.map((activity) => activity.id));
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    const noticed = new Set(
      tasks
        .filter((task) => task.kind === "activity_notice")
        .map((task) => task.activity_id),
    );
    const notices = (data.activities || [])
      .filter(
        (activity) =>
          !seedIds.has(activity.id) &&
          !noticed.has(activity.id) &&
          activity.organization,
      )
      .map((activity) => ({
        id: `activity-notice-${activity.id}`,
        kind: "activity_notice",
        title: `新主题党日：${activity.title}`,
        date: String(activity.date || "").slice(5),
        status: "待查看",
        route: "activities",
        completed: false,
        tenant_id: activity.tenant_id || "school-1",
        org_unit_id: activity.orgId || "",
        department: activity.department || activity.organization,
        activity_id: activity.id,
        created_by: activity.created_by || "",
        created_at: activity.created_at || new Date().toISOString(),
      }));
    existing.tasks = [...notices, ...tasks];
    existing.activityNoticeVersion = 1;
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
    publicity: { items: [], current: null, satisfied: false, notice: "尚未登记公示起止日期" },
    upper_talk: { items: [], current: null, satisfied: false, notice: "尚未登记上级党委派人谈话" },
    branch_vote: { items: [], current: null, satisfied: false, notice: "尚未登记支部大会票决" },
    probation_outcome: { items: [], current: null, satisfied: false, notice: "尚未登记预备党员转正结果" },
    higher_record: { items: [], current: null, satisfied: false, notice: "尚未登记再上一级党委组织部门备案" },
    party_group: { items: [], current: null, satisfied: false, notice: "尚未登记编入党支部和党小组" },
    secondary_review: { items: [], current: null, by_node: {}, satisfied: false, notice: "尚未登记二级党组织审议与组织员签字" },
    requirement: "接收预备党员前应完成培养联系人、2名不同入党介绍人、支委会审查、上级党委预审和入党志愿书登记；公示应登记起止日期并按5个工作日核对。上级党委派人谈话应在上级审批前完成；二级党组织审议与专职组织员签字按学校节点单独登记。预备党员转正前应登记支部大会票决和转正结果；延长预备期作为独立记录，取消预备党员资格为终态。系统只登记事实，不替代组织程序。",
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
      satisfied: latest.length >= 2,
      notice: latest.length === 0 ? "尚未登记入党介绍人" : latest.length < 2 ? "已登记1名入党介绍人；接收预备党员前须登记2名" : "已登记2名入党介绍人",
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
  if (key === "publicity") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: status === "completed",
      notice: !current
        ? "尚未登记公示起止日期"
        : status === "completed"
          ? `公示已满 ${current?.details?.working_days || 5} 个工作日`
          : "公示状态待核对",
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
  if (key === "branch_vote") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: status === "passed",
      notice: !current ? "尚未登记支部大会票决" : status === "passed" ? "支部大会票决通过" : "支部大会票决未通过",
    };
  }
  if (key === "probation_outcome") {
    const status = current?.status;
    return {
      items,
      current,
      satisfied: Boolean(current),
      notice: !current
        ? "尚未登记预备党员转正结果"
        : status === "qualified"
          ? "预备党员已按期转正"
          : status === "extended"
            ? `延长预备期至 ${current?.details?.effective_until || "未登记日期"}`
            : "已登记取消预备党员资格",
    };
  }
  if (key === "higher_record") {
    return {
      items,
      current,
      satisfied: current?.status === "recorded",
      notice: current ? "再上一级党委组织部门备案已登记" : "尚未登记再上一级党委组织部门备案",
    };
  }
  if (key === "party_group") {
    return {
      items,
      current,
      satisfied: current?.status === "assigned",
      notice: current ? "已编入党支部和党小组" : "尚未登记编入党支部和党小组",
    };
  }
  if (key === "secondary_review") {
    const byNode = {};
    for (const item of items) {
      const node = item?.details?.node;
      if (node && !byNode[node]) byNode[node] = item;
    }
    return {
      items,
      current,
      by_node: byNode,
      satisfied: items.length > 0,
      notice: items.length
        ? `已登记 ${Object.keys(byNode).length} 个二级审议节点`
        : "尚未登记二级党组织审议与组织员签字",
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
const FLOW_STAGE_ORDER = [
  "applicant",
  "activist",
  "candidate",
  "probationary",
  "member",
  "disqualified",
  "rejected",
];
const FLOW_REQUIRED_MATERIALS = {
  applicant: ["入党申请书", "党组织谈话记录"],
  activist: ["思想汇报", "培养考察记录", "群众评议材料", "党课培训证明"],
  candidate: ["政治审查材料", "公示情况报告", "支部大会决议"],
  probationary: ["转正申请书", "预备期考察记录", "支部大会决议"],
};
const FLOW_NEXT_STEP = {
  applicant: "递交申请并接受党组织谈话",
  activist: "培养考察，研究确定发展对象",
  candidate: "履行接收预备党员程序",
  probationary: "预备期考察，办理转正",
  member: "继续教育管理",
  disqualified: "已终止发展",
  rejected: "按组织意见重新考察",
};
function stageCode(label) {
  return Object.keys(STAGE_LABELS).find((key) => STAGE_LABELS[key] === label) || label;
}
function daysSince(value) {
  const time = Date.parse(value || "");
  if (Number.isNaN(time)) return 0;
  return Math.max(0, Math.floor((Date.now() - time) / 86400000));
}
export function buildDemoFlowBoard(
  members = [],
  developmentProfiles = {},
  resolvedReminders = [],
) {
  const resolved = new Set(resolvedReminders);
  const items = members.map((member) => {
    const code = stageCode(member.stage);
    const detail = getDemoDevelopment(member, developmentProfiles[member.id]);
    const procedures = detail.procedures || emptyProcedureState();
    const approved = new Set(
      (detail.materials || [])
        .filter(
          (material) =>
            material.review_status === "approved" &&
            materialSource(material) !== "personal",
        )
        .map((material) => material.material_type),
    );
    const missing = [];
    const addMissing = (value) => {
      if (value && !missing.includes(value)) missing.push(value);
    };
    for (const name of FLOW_REQUIRED_MATERIALS[code] || [])
      if (!approved.has(name)) addMissing(name);
    if (code === "activist" && !procedures.contacts?.satisfied)
      addMissing("培养联系人");
    if (code === "candidate") {
      if (!procedures.contacts?.satisfied) addMissing("培养联系人");
      if (!procedures.introducers?.satisfied) addMissing("入党介绍人2名");
      if (!procedures.branch_committee_review?.satisfied)
        addMissing("支委会审查通过");
      if (!procedures.upper_pre_review?.satisfied)
        addMissing("上级党委预审通过");
      if (!procedures.application_form?.satisfied)
        addMissing("入党志愿书已提交或已审核");
      if (!detail.political_reviews?.satisfied)
        addMissing("政治审查合格结论");
      if (!detail.trainings?.satisfied)
        addMissing("集中培训不少于3天或24学时");
    }
    if (code === "probationary") {
      const vote = procedures.branch_vote?.current;
      const outcome = procedures.probation_outcome?.current;
      if (outcome?.status === "disqualified") {
        if (!vote) addMissing("支部大会讨论票决");
      } else if (
        !vote ||
        vote.status !== "passed" ||
        vote.details?.meeting_for !== "conversion"
      )
        addMissing("支部大会转正票决通过");
      if (!outcome) addMissing("预备党员转正结果");
      else if (outcome.status === "extended")
        addMissing(
          `延长预备期至 ${outcome.details?.effective_until || "未登记日期"}，未满`,
        );
      else if (outcome.status === "disqualified")
        addMissing("取消预备党员资格待办理");
      if (!procedures.party_group?.satisfied)
        addMissing("编入党支部和党小组");
      if (!procedures.higher_record?.satisfied)
        addMissing("再上一级党委组织部门备案");
    }
    const stageJoinedOn =
      detail.stage_joined_on || member.stage_joined_on || "2026-01-01";
    const reminders = [];
    if (code === "probationary") {
      const due = stageJoinedOn;
      if (!procedures.higher_record?.satisfied)
        reminders.push({
          id: `demo-${member.id}-higher_record`,
          kind: "higher_record",
          due_on: due,
          status: "open",
          note: "",
        });
      if (!procedures.party_group?.satisfied)
        reminders.push({
          id: `demo-${member.id}-party_group`,
          kind: "party_group",
          due_on: due,
          status: "open",
          note: "",
        });
      const oathId = `demo-${member.id}-oath`;
      if (!resolved.has(oathId)) {
        reminders.push({
          id: oathId,
          kind: "oath",
          due_on: due,
          status: "open",
          note: "",
        });
        addMissing("入党宣誓");
      }
    }
    return {
      id: member.id,
      name: member.name,
      org_name: member.organization || member.org_name || "",
      org_unit_id: member.orgId || member.org_unit_id || "",
      current_stage: code,
      stage_label: STAGE_LABELS[code] || member.stage,
      stage_joined_on: stageJoinedOn,
      days_in_stage: daysSince(stageJoinedOn),
      next_stage:
        { applicant: "activist", activist: "candidate", candidate: "probationary", probationary: "member" }[
          code
        ] || "",
      next_step: FLOW_NEXT_STEP[code] || "核对档案阶段",
      missing,
      procedures: {},
      political_review: detail.political_reviews?.current
        ? {
            status: detail.political_reviews.current.status,
            reviewed_on: detail.political_reviews.current.reviewed_on,
          }
        : null,
      training_ready: Boolean(detail.trainings?.satisfied),
      reminders,
    };
  });
  const counts = {};
  for (const item of items)
    counts[item.current_stage] = (counts[item.current_stage] || 0) + 1;
  return {
    items,
    stage_summary: FLOW_STAGE_ORDER.map((code) => ({
      stage: code,
      label: STAGE_LABELS[code] || code,
      count: counts[code] || 0,
    })),
    total: items.length,
    shown: items.length,
    truncated: false,
    notice:
      "看板汇总材料、程序事实和提醒，不自动推进阶段，也不替代组织决定。",
  };
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
