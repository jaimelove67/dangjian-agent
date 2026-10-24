import { organizations, seedMembers } from "./data.js";

export const SCHOOL_YEAR = "2026";
export const BUSINESS_TYPES = ["党员发展", "组织生活", "学习教育", "年度考核"];
export const SCHOOL_INDICATORS = [
  {
    id: "A01",
    name: "组织建设与运行",
    requirement: "组织设置、负责人及换届材料完整",
    weight: 25,
  },
  {
    id: "A02",
    name: "党员教育管理",
    requirement: "年度学习计划、任务及完成记录齐全",
    weight: 25,
  },
  {
    id: "A03",
    name: "组织生活规范",
    requirement: "三会一课、主题党日记录和纪要完整",
    weight: 30,
  },
  {
    id: "A04",
    name: "服务与作用发挥",
    requirement: "服务实践记录及佐证材料可追溯",
    weight: 20,
  },
];

export function buildSchoolData() {
  const definitions = [
    [
      "dev-1",
      "党员发展",
      "下半年发展对象材料审核",
      2,
      "待审核",
      "2026-10-25",
      "发展对象",
      1,
    ],
    [
      "dev-2",
      "党员发展",
      "预备党员转正材料待补充",
      9,
      "待补充",
      "2026-10-20",
      "预备党员",
      0,
    ],
    [
      "life-1",
      "组织生活",
      "10月主题党日纪要未提交",
      14,
      "待提交",
      "2026-10-21",
      "",
      0,
    ],
    [
      "assess-1",
      "年度考核",
      "年度考核组织生活佐证待提交",
      20,
      "待提交",
      "2026-10-18",
      "",
      0,
    ],
    [
      "learn-1",
      "学习教育",
      "院系专题学习计划校级审核",
      27,
      "待审核",
      "2026-10-26",
      "",
      1,
    ],
    [
      "assess-2",
      "年度考核",
      "基层党支部年度考核结果确认",
      33,
      "待审核",
      "2026-10-28",
      "",
      1,
    ],
    [
      "life-2",
      "组织生活",
      "9月主题党日归档确认",
      39,
      "已通过",
      "2026-10-27",
      "",
      1,
    ],
    [
      "dev-3",
      "党员发展",
      "积极分子培养考察记录核对",
      45,
      "已通过",
      "2026-10-22",
      "入党积极分子",
      1,
    ],
    [
      "learn-2",
      "学习教育",
      "党员专题学习完成情况汇总",
      51,
      "已归档",
      "2026-10-20",
      "",
      1,
    ],
    [
      "assess-3",
      "年度考核",
      "上年度基层党组织考核归档",
      58,
      "已归档",
      "2025-12-20",
      "",
      1,
    ],
    [
      "dev-4",
      "党员发展",
      "入党申请人材料完整性核对",
      63,
      "待补充",
      "2026-10-29",
      "入党申请人",
      0,
    ],
    [
      "learn-3",
      "学习教育",
      "10月党员集中学习记录核验",
      7,
      "待审核",
      "2026-10-25",
      "",
      1,
    ],
  ];
  return {
    schoolWorkItems: definitions.map(
      ([id, business, title, index, status, dueDate, stage, complete]) => {
        const org = organizations[index];
        const person = stage
          ? seedMembers.find((m) => m.orgId === org.id && m.stage === stage) ||
            seedMembers.find((m) => m.stage === stage)
          : null;
        const ownerOrg = person
          ? organizations.find((o) => o.id === person.orgId)
          : org;
        return {
          id,
          business,
          title,
          tenant_id: "school-1",
          orgId: ownerOrg.id,
          organization: ownerOrg.name,
          department: ownerOrg.department,
          status,
          dueDate,
          year: dueDate.slice(0, 4),
          stage,
          profileId: person?.id,
          person: person?.name,
          revision: 2,
          ...(business === "学习教育" ? { planId: "plan-1" } : {}),
          submittedBy: `school-submitter-${index}`,
          submittedName: ownerOrg.secretary,
          submittedAt: `${dueDate.slice(0, 4)}-10-16 10:20`,
          reviewLevel: "学校审核",
          archived: status === "已归档",
          materials: [
            {
              name:
                business === "组织生活"
                  ? "活动纪要与开展记录"
                  : business === "年度考核"
                    ? "考核自评表与指标佐证"
                    : business === "学习教育"
                      ? "学习计划与完成清单"
                      : "申请及阶段材料",
              complete: true,
              version: "v2",
              content:
                "当前仅登记材料摘要，尚未附原件；请核对所属组织、适用年度和材料版本。",
            },
            {
              name:
                business === "党员发展"
                  ? "培养考察及组织核验意见"
                  : "院系核验意见与补充佐证",
              complete: !!complete,
              version: complete ? "v1" : "—",
              content: complete
                ? "院系已完成材料完整性核验，提交学校按制度审核。"
                : "院系待补齐材料后重新提交。",
            },
          ],
          history: [
            {
              id: `${id}-history`,
              action:
                status === "待补充"
                  ? "退回补充"
                  : status === "待提交"
                    ? "建立任务"
                    : "院系提交",
              actor: ownerOrg.secretary,
              at: `${dueDate.slice(0, 4)}-10-16 10:20`,
              version: 2,
              opinion:
                status === "待补充"
                  ? "请补齐培养考察记录及院系核验意见。"
                  : "已核对组织归属，按学校制度提交办理。",
            },
          ],
        };
      },
    ),
    schoolRules: {
      year: "2026",
      reviewDays: 5,
      reminderDays: 3,
      developmentMaterials:
        "入党申请书、培养考察记录、党课培训证明、院系核验意见",
      archiveRequirements: "材料审核通过后，由学校授权人员逐项确认归档",
      revision: 1,
    },
    schoolIndicators: SCHOOL_INDICATORS,
    schoolPermissionRequests: [],
    schoolReminders: [],
    schoolLearningPlans: [
      {
        id: "plan-1",
        title: "2026年下半年党员理论学习计划",
        year: "2026",
        deadline: "2026-12-15",
        scope: "全校各院系及所属支部",
        requirement: "完成专题学习，提交学习记录及院系核验意见。",
        status: "执行中",
      },
    ],
  };
}

export function schoolToday() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  return ["year", "month", "day"]
    .map((key) => parts.find((p) => p.type === key).value)
    .join("-");
}
export function formatSchoolTime(value) {
  if (!value) return "—";
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value))
    return value.replace("T", " ").slice(0, 16);
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date
        .toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", hour12: false })
        .slice(0, 16);
}
export function isSchoolComplete(record) {
  return ["已通过", "已归档"].includes(record.status);
}
export function isSchoolOverdue(record, today = schoolToday()) {
  return (
    !!record.dueDate && record.dueDate < today && !isSchoolComplete(record)
  );
}
export function filterSchoolRecords(records, filters = {}) {
  return records.filter(
    (r) =>
      (!filters.year || String(r.year) === String(filters.year)) &&
      (!filters.department || r.department === filters.department) &&
      (!filters.orgId || r.orgId === filters.orgId) &&
      (!filters.business || r.business === filters.business) &&
      (!filters.stage || r.stage === filters.stage) &&
      (!filters.status ||
        (filters.status === "逾期"
          ? isSchoolOverdue(r)
          : filters.status === "待归档"
            ? r.status === "已通过"
            : filters.status === "待补充"
              ? ["待补充", "已退回"].includes(r.status)
              : r.status === filters.status)) &&
      (!filters.query ||
        `${r.title} ${r.organization} ${r.person || ""} ${r.submittedName}`.includes(
          filters.query.trim(),
        )),
  );
}

export function schoolMeetingRecords(meetings, orgs) {
  return meetings.map((m) => {
    const org = orgs.find((o) => o.id === m.orgId);
    const minutes = typeof m.transcript === "string"
      ? m.transcript
      : typeof m.minutes === "string" ? m.minutes : "";
    return {
      ...m,
      source: "meeting",
      business: "组织生活",
      year: m.date?.slice(0, 4),
      department: org?.department || "",
      organization: org?.name || m.organization || m.orgId,
      status:
        m.status === "已完成"
          ? "已通过"
          : m.status === "待召开"
            ? "待开展"
            : m.status,
      submittedBy: m.submitted_by,
      submittedName: m.submitted_name || m.host || "待登记",
      submittedAt: m.date,
      reviewLevel: "学校确认",
      archived: m.status === "已归档",
      archivedBy: m.archived_name || m.archived_by,
      revision: m.revision || 1,
      dueDate:
        m.review_due_date || m.dueDate || (m.status === "待召开" ? m.date : ""),
      materials: [
        {
          name: "会议议程与纪要",
          complete: !!minutes.trim(),
          version: `v${m.revision || 1}`,
          content: minutes || "尚未登记会议纪要。",
        },
      ],
      history: m.schoolHistory || [
        {
          id: `${m.id}-history`,
          action:
            m.status === "已归档"
              ? "已归档"
              : m.status === "待审核"
                ? "提交纪要审核"
                : "登记会议",
          actor: m.submitted_name || m.host || "待登记",
          at: m.date,
          version: m.revision || 1,
          opinion:
            m.review_opinion ||
            m.submission_reason ||
            "查看会议详情可核对议程及纪要。",
        },
      ],
    };
  });
}

export function decideSchoolRecord(
  session,
  current,
  expectedRevision,
  action,
  opinion,
  at = new Date().toISOString(),
) {
  if (
    session?.user?.role !== "school_admin" ||
    !session.permissions?.includes(
      action === "archive" ? "admin.archive_confirm" : "admin.review",
    )
  )
    throw new Error("当前账号没有此项校级办理权限。");
  if (!current || current.source === "meeting")
    throw new Error("请从组织生活记录办理此事项。");
  if ((current.tenant_id || "school-1") !== session.user.tenant_id)
    throw new Error("该事项不属于当前学校。");
  if (current.revision !== expectedRevision)
    throw new Error("材料版本已变化，请关闭后重新核对。");
  if (!opinion.trim()) throw new Error("请填写核对依据与处理意见。");
  if (
    action === "archive"
      ? current.status !== "已通过"
      : current.status !== "待审核"
  )
    throw new Error("事项状态已变化，请重新核对。");
  if (action !== "archive" && current.submittedBy === session.user.id)
    throw new Error("提交人不能审核自己的记录。");
  if (!["approve", "return", "archive"].includes(action))
    throw new Error("无效的处理操作。");
  if (action === "approve" && current.materials.some((m) => !m.complete))
    throw new Error("材料尚未齐全，请退回补充后再审核。");
  const status =
    action === "archive"
      ? "已归档"
      : action === "approve"
        ? "已通过"
        : "待补充";
  return {
    ...current,
    status,
    revision: current.revision + 1,
    archived: action === "archive",
    ...(action === "archive"
      ? { archivedBy: session.user.name }
      : { reviewedBy: session.user.name }),
    history: [
      ...current.history,
      {
        id: crypto.randomUUID(),
        action:
          action === "archive"
            ? "确认归档"
            : action === "approve"
              ? "学校审核通过"
              : "退回补充",
        actor: session.user.name,
        at,
        version: current.revision + 1,
        opinion: opinion.trim(),
      },
    ],
  };
}
