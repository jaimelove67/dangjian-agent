// Contract source: frontend/src/api/types.ts and app/schemas/meeting.py in the reference repository.
export const QA_QUESTION_MAX_LENGTH = 500;

export function branchOrganizations(organizations) {
  return organizations.filter((org) =>
    org.org_type ? org.org_type === "branch" : /支部/.test(org.type || ""),
  );
}

export function questionText(value) {
  if (typeof value !== "string" || !value.trim())
    throw new Error("请输入问题。");
  const question = value.trim();
  if (Array.from(question).length > QA_QUESTION_MAX_LENGTH)
    throw new Error(`问题最多 ${QA_QUESTION_MAX_LENGTH} 字，请缩短后再发送。`);
  return question;
}

export const STAGE_LABELS = {
  applicant: "入党申请人",
  activist: "入党积极分子",
  candidate: "发展对象",
  probationary: "预备党员",
  member: "正式党员",
  rejected: "退回",
};
export const RELATIONS = {
  in_place: "在册",
  out_pending: "转出待接收",
  transferred_out: "已转出",
};
export function normalizeMember(member) {
  return {
    ...member,
    number: member.id_card_masked || member.id,
    organization: member.org_name || "未登记",
    orgId: member.org_unit_id,
    department: member.org_name || "未登记",
    stage: STAGE_LABELS[member.stage] || "未登记",
    status: RELATIONS[member.relation_status] || "在册",
    joined: member.stage_joined_on || "未登记",
    phone: "未提供",
    gender: "未提供",
    relation: RELATIONS[member.relation_status] || "在册",
  };
}
export function memberPayload(values) {
  return {
    name: values.name,
    org_unit_id: values.orgId,
    current_stage:
      Object.keys(STAGE_LABELS).find(
        (code) => STAGE_LABELS[code] === values.stage,
      ) || "applicant",
    materials: [],
    pending: 0,
  };
}
export function meetingParticipants(text) {
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length > 500) throw new Error("参会记录不能超过500人。");
  const seen = new Set();
  return lines.map((line, index) => {
    const fields = line.split(/[|｜]/).map(value => value.trim());
    const [participant_id, name, status] = fields;
    if (fields.length !== 3 || !participant_id || !name || participant_id.length > 100 || name.length > 100)
      throw new Error(`第${index + 1}行请填写人员编号 | 姓名 | 出席或缺席。`);
    if (!["出席", "缺席"].includes(status))
      throw new Error(`第${index + 1}行的出勤情况请填写出席或缺席。`);
    if (seen.has(participant_id)) throw new Error("参会人员编号不能重复。");
    seen.add(participant_id);
    return { participant_id, name, attended: status === "出席" };
  });
}
export function meetingPayload(values, existing = {}) {
  const common = {
    scheduled_on: values.date,
    host: values.host,
    agenda: values.agenda,
    reason: "组织人员人工维护会议资料",
  };
  if (existing.id)
    return {
      ...common,
      topic: values.title,
      transcript: values.minutes,
      expected_revision: existing.revision,
      ...(values.heldOn ? { held_on: values.heldOn } : {}),
      ...(values.participants ? { participants: values.participants } : {}),
    };
  return {
    ...common,
    org_unit_id: values.orgId,
    activity_type: values.activityType,
    title: values.title,
    participants: values.participants || [],
    source_doc_ids: [],
  };
}
