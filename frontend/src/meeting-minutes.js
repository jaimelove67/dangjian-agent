const THREE_MEETING_LABELS = [
  { key: "learning_points", label: "学习要点", aliases: ["学习重点"] },
  { key: "consensus", label: "讨论共识", aliases: ["会议共识"] },
  { key: "requirements", label: "工作要求", aliases: ["落实要求"] },
];

const ORGANIZATIONAL_LIFE_LABELS = [
  { key: "problems", label: "查摆问题", aliases: ["存在问题"] },
  {
    key: "criticisms",
    label: "批评意见",
    aliases: ["批评与自我批评", "批评和自我批评"],
  },
  { key: "rectifications", label: "整改方向", aliases: ["整改措施"] },
];

export function minutesSectionsFor(activityType) {
  return activityType === "organizational_life_meeting"
    ? ORGANIZATIONAL_LIFE_LABELS
    : THREE_MEETING_LABELS;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function transcriptSectionStatus(transcript, activityType) {
  const text = String(transcript || "");
  return minutesSectionsFor(activityType).map((section) => {
    const names = [section.label, ...(section.aliases || [])]
      .map(escapeRegExp)
      .join("|");
    return {
      ...section,
      found: new RegExp(`^\\s*(?:${names})[：:]`, "m").test(text),
    };
  });
}

export function missingMinuteLabels(transcript, activityType) {
  return transcriptSectionStatus(transcript, activityType)
    .filter((section) => !section.found)
    .map((section) => section.label);
}

export function meetingIsFuture(scheduledOn, today = new Date()) {
  if (!scheduledOn) return false;
  const localToday = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
  return String(scheduledOn) > localToday;
}
