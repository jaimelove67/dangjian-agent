import { STAGE_LABELS } from "./contracts.js";

export const AUTO_ROSTER_TYPES = new Set([
  "branch_member_meeting",
  "party_lecture",
  "organizational_life_meeting",
]);

const MEMBER_ONLY_STAGES = new Set(["member", "probationary"]);

export function participantStageLabel(stage) {
  return STAGE_LABELS[stage] || stage || "身份待补";
}

export function isAutoRosterType(activityType) {
  return AUTO_ROSTER_TYPES.has(activityType);
}

export function rosterMembersForImport(members, activityType) {
  if (!isAutoRosterType(activityType)) return [];
  if (activityType === "party_lecture") return [...members];
  return members.filter((member) => MEMBER_ONLY_STAGES.has(member.stage));
}

export function mergeParticipantRows(current, additions) {
  const rows = Array.isArray(current) ? [...current] : [];
  const indexById = new Map(
    rows.map((row, index) => [String(row.participant_id), index]),
  );
  for (const addition of additions || []) {
    const participantId = String(addition.participant_id || "").trim();
    if (!participantId) continue;
    if (indexById.has(participantId)) {
      const index = indexById.get(participantId);
      rows[index] = {
        ...rows[index],
        stage: rows[index].stage || addition.stage || "",
        org_name: rows[index].org_name || addition.org_name || "",
      };
      continue;
    }
    indexById.set(participantId, rows.length);
    rows.push({
      participant_id: participantId,
      name: String(addition.name || "").trim(),
      stage: addition.stage || "",
      org_name: addition.org_name || "",
      attended:
        addition.attended === true || addition.attended === false
          ? addition.attended
          : null,
      manual: Boolean(addition.manual),
    });
  }
  return rows;
}

export function participantSummary(rows) {
  const list = rows || [];
  return {
    total: list.length,
    attended: list.filter((row) => row.attended === true).length,
    absent: list.filter((row) => row.attended === false).length,
    pending: list.filter((row) => row.attended !== true && row.attended !== false)
      .length,
  };
}

export function validateParticipantRows(rows) {
  const list = rows || [];
  if (list.length > 500) throw new Error("参会记录不能超过500人。");
  const seen = new Set();
  for (const row of list) {
    const participantId = String(row.participant_id || "").trim();
    const name = String(row.name || "").trim();
    if (!participantId || !name)
      throw new Error("参会人员姓名和人员编号不能为空。");
    if (seen.has(participantId))
      throw new Error("参会人员编号不能重复。");
    seen.add(participantId);
  }
  const pending = list.filter(
    (row) => row.attended !== true && row.attended !== false,
  ).length;
  if (pending)
    throw new Error(`还有 ${pending} 名参会人员未确认出勤，请选择出席或缺席。`);
  return list.map((row) => ({
    participant_id: String(row.participant_id).trim(),
    name: String(row.name).trim(),
    attended: row.attended === true,
  }));
}
