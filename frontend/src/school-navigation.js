export const SCHOOL_NAVIGATION = [
  {
    id: "school-home",
    label: "学校工作台",
    icon: "House",
    items: [
      ["dashboard", "全校概况"],
      ["reviews", "集中审核"],
      ["school-supervision", "问题与督办"],
    ],
  },
  {
    id: "school-organization",
    label: "组织与党员",
    icon: "TreeStructure",
    items: [
      ["organization", "组织结构与负责人"],
      ["members", "党员名册与归属"],
      ["archive", "党员档案与材料"],
    ],
  },
  {
    id: "school-development",
    label: "党员发展",
    icon: "GraduationCap",
    items: [
      ["school-development", "全校发展进度"],
      ["development", "材料、培养与流转"],
    ],
  },
  {
    id: "school-life",
    label: "组织生活",
    icon: "CalendarBlank",
    items: [
      ["school-life", "开展检查与归档"],
      ["meetings", "三会一课与会议纪要"],
      ["activities", "主题党日与活动计划"],
    ],
  },
  {
    id: "school-learning",
    label: "学习教育",
    icon: "BookOpen",
    items: [
      ["school-learning", "全校学习计划与任务"],
      ["learning", "课程与活动"],
      ["school-notices", "通知公告"],
      ["knowledge", "政策制度库与文件审核"],
      ["assistant", "制度问答助手"],
    ],
  },
  {
    id: "school-assessment",
    label: "考核与统计",
    icon: "ChartBar",
    items: [
      ["assessment", "年度指标与组织考核"],
      ["analytics", "全校统计与报表"],
    ],
  },
  {
    id: "school-management",
    label: "校级管理",
    icon: "GearSix",
    items: [
      ["school-accounts", "本校账号管理"],
      ["school-permissions", "业务权限申请"],
      ["school-rules", "学校业务参数"],
      ["audit", "校内操作审计"],
    ],
  },
];

export function schoolNavigationGroup(route) {
  return (
    SCHOOL_NAVIGATION.find((group) =>
      group.items.some(([id]) => id === route),
    ) || (route === "inbox" ? SCHOOL_NAVIGATION[2] : null)
  );
}

export function schoolRouteLabel(route) {
  return SCHOOL_NAVIGATION.flatMap((group) => group.items).find(
    ([id]) => id === route,
  )?.[1];
}
