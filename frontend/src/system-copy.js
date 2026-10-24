// Upgrade only known system text in the local workspace. Keep identifiers,
// attachments, permissions and user-edited business content unchanged.
const replacements = new Map([
  ["本地演示档案", "党员档案登记信息"],
  ["10月学习心得（示例）", "10月学习心得"],
  ["围绕本月专题学习记录个人体会。此条为示例记录，无原件。", "围绕本月专题学习记录个人体会，原件尚未提交。"],
  ["学习心得-示例.txt", "学习心得.txt"],
  ["入党申请阶段材料（示例）", "入党申请阶段材料"],
  ["按所在支部要求登记的演示材料，无原件。", "按所在支部要求登记材料，原件尚未提交。"],
  ["个人材料-示例.pdf", "个人材料.pdf"],
  ["与会人员围绕学习材料开展交流，明确后续学习与服务安排。此记录用于演示人工审核流程。", "与会人员围绕学习材料开展交流，明确后续学习与服务安排。记录经审核后按学校制度归档。"],
  ["本地演示材料清单，具体要求以组织审核为准。", "材料清单已登记，具体要求及核验结果以组织审核为准。"],
  ["已登记业务材料摘要。请结合所属组织及适用年度核对；此为演示材料，无正式原件。", "当前仅登记材料摘要，尚未附原件；请核对所属组织、适用年度和材料版本。"],
  ["发展党员工作相关制度。演示模式不生成政策结论，正式使用以现行有效原文与组织审核为准。", "发展党员工作相关制度，办理时请核对现行有效原文及组织审核要求。"],
  ["2026年度学校党建工作要点（示例）", "2026年度学校党建工作要点"],
  ["演示学校文件，请使用正式学校文件替换。", "文件内容待组织人员复核，请以学校正式发布的有效原件为准。"],
  ["创建演示账号", "创建账号"],
  ["登记演示租户", "登记租户"],
  ["重置演示账号密码", "重置账号密码"],
  ["恢复演示初始密码，保留累计自主改密次数并撤销未完成申请", "恢复初始密码，保留累计自主改密次数并撤销未完成申请"],
  ["配置与业务索引快照（演示）", "配置与业务索引记录"],
  ["以上为内置示例模板，用于演示交互，未调用大模型；请结合实际情况人工修改。", "以上为工作模板，请补充实际情况，经组织人员审核后使用。"],
  ["演示回答 · 未进行真实知识检索，请以正式制度和组织审核意见为准。", "办理参考 · 请以现行制度和组织审核意见为准。"],
]);

function fields(record, names) {
  return Object.fromEntries(Object.entries(record).map(([key, value]) => [
    key, names.includes(key) ? replacements.get(value) ?? value : value,
  ]));
}

const schoolSeedIds = new Set([
  "dev-1", "dev-2", "dev-3", "dev-4", "life-1", "life-2",
  "learn-1", "learn-2", "learn-3", "assess-1", "assess-2", "assess-3",
]);
const referenceTail = "当前未提供可核验的制度依据。以上为办理参考，请查阅学校现行制度，并由有权限的组织人员确认后办理。";
const oldReferenceTail = "当前是本地演示环境，尚未连接正式知识库和模型服务，因此不会生成未经核验的政策结论或引用。您可以继续体验提问、会话记录及材料模板，也可以在接入原项目后使用带来源的制度问答。";

export function normalizeSystemAuditCopy(row) {
  return {
    ...fields(row, ["action", "detail"]),
    request_id: /^demo-(?:trace-001|platform-trace-\d+|[a-f0-9]{8}|password-[a-f0-9-]{36})$/.test(row.request_id)
      ? row.request_id.replace(/^demo-/, "local-") : row.request_id,
  };
}

export function normalizeStoredSystemCopy(data) {
  const next = { ...data };
  if (Array.isArray(data.members)) next.members = data.members.map((row) =>
    /^member-\d+$/.test(row.id) ? fields(row, ["note"]) : row);
  if (Array.isArray(data.knowledge)) next.knowledge = data.knowledge.map((row) =>
    ["doc-2", "doc-4"].includes(row.id) ? fields(row, ["title", "summary"]) : row);
  if (Array.isArray(data.personalMaterials)) next.personalMaterials = data.personalMaterials.map((row) =>
    ["demo-material-student", "demo-material-applicant"].includes(row.id)
      ? fields(row, ["title", "description", "file_name"]) : row);
  if (Array.isArray(data.meetings)) next.meetings = data.meetings.map((row) =>
    row.id === "role-meeting-1" ? fields(row, ["minutes"]) : row);
  if (Array.isArray(data.schoolWorkItems)) next.schoolWorkItems = data.schoolWorkItems.map((row) =>
    schoolSeedIds.has(row.id) && Array.isArray(row.materials)
      ? { ...row, materials: row.materials.map((item) => fields(item, ["content"])) } : row);
  if (data.developmentProfiles) next.developmentProfiles = Object.fromEntries(
    Object.entries(data.developmentProfiles).map(([id, profile]) => [id,
      Array.isArray(profile?.materials) ? {
        ...profile,
        materials: profile.materials.map((item) => item.id?.startsWith(`demo-dev-${id}-`)
          ? fields(item, ["note"]) : item),
      } : profile,
    ]),
  );
  if (Array.isArray(data.auditEntries)) next.auditEntries = data.auditEntries.map(normalizeSystemAuditCopy);
  if (Array.isArray(data.messages)) next.messages = data.messages.map((row) => {
    if (row.role !== "assistant") return row;
    const result = fields(row, ["disclaimer"]);
    if (row.content?.startsWith("我可以帮助您梳理这个问题的办理思路。") && row.content.endsWith(oldReferenceTail)) {
      result.content = row.content.slice(0, -oldReferenceTail.length) + referenceTail;
    }
    return result;
  });
  if (Array.isArray(data.platform?.backups)) next.platform = {
    ...data.platform,
    backups: data.platform.backups.map((row) => ({
      ...fields(row, ["scope"]),
      checksum: ["demo-sha256-8f61b36a", "demo-sha256-42b87f31"].includes(row.checksum)
        ? "" : row.checksum,
    })),
  };
  return next;
}
