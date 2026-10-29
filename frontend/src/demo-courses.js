import { DEPARTMENTS, organizations } from "./data.js";

export const COURSE_MANAGER_ROLES = [
  "school_admin",
  "department_admin",
  "branch_secretary",
  "organizer",
];

export function canManageCourses(session) {
  return (
    COURSE_MANAGER_ROLES.includes(session?.user?.role) &&
    (session?.permissions || []).includes("education.query")
  );
}

function courseScope(course) {
  return course?.orgScope || "school";
}

export function courseScopeOptions(session) {
  const user = session?.user;
  if (!user) return [];
  if (user.role === "school_admin") {
    return [
      { value: "school", label: "全校" },
      ...DEPARTMENTS.map((name) => ({
        value: `department:${name}`,
        label: name,
      })),
    ];
  }
  if (user.role === "department_admin") {
    const department = user.department || "";
    return [
      ...(department
        ? [
            {
              value: `department:${department}`,
              label: `${department}（院系）`,
            },
          ]
        : []),
      ...organizations
        .filter((org) => org.department === department)
        .map((org) => ({ value: org.id, label: org.name })),
    ];
  }
  const org = organizations.find((item) => item.id === user.org_unit_id);
  return org ? [{ value: org.id, label: org.name }] : [];
}

export function courseVisibleTo(course, session) {
  const user = session?.user;
  if (!user || user.role === "system_admin") return false;
  const scope = courseScope(course);
  if (scope === "school") return true;
  if (user.role === "school_admin") return true;
  if (scope.startsWith("department:")) {
    return user.department === scope.slice("department:".length);
  }
  const org = organizations.find((item) => item.id === scope);
  if (!org) return false;
  if (user.role === "department_admin") {
    return org.department === user.department;
  }
  return user.org_unit_id === org.id;
}

export function canManageOffering(course, session) {
  const user = session?.user;
  if (!user || !canManageCourses(session)) return false;
  if (user.role === "school_admin") return true;
  const scope = courseScope(course);
  if (user.role === "department_admin") {
    if (scope === "school") return false;
    if (scope === `department:${user.department}`) return true;
    const org = organizations.find((item) => item.id === scope);
    return !!org && org.department === user.department;
  }
  return course.createdBy === user.id && scope === user.org_unit_id;
}

export function visibleDemoCourses(
  offerings,
  session,
  canManage = canManageCourses(session),
) {
  return (offerings || []).filter((course) => {
    if (!courseVisibleTo(course, session)) return false;
    if (course.status === "published") return true;
    return canManage && canManageOffering(course, session);
  });
}

export function createDemoCourse(
  values,
  session,
  publish = false,
  now = new Date().toISOString(),
) {
  const user = session?.user;
  if (!user || !canManageCourses(session)) {
    throw new Error("当前账号不能编制课程。");
  }
  const options = courseScopeOptions(session);
  const orgScope = values.orgScope || options[0]?.value || "";
  const selected = options.find((item) => item.value === orgScope);
  if (!selected) throw new Error("请选择课程组织范围。");
  const title = String(values.title || "").trim();
  const content = String(values.content || "").trim();
  if (!title) throw new Error("请填写课程名称。");
  if (!content) throw new Error("请填写学习内容。");
  const minutes = Number(values.minutes);
  if (!Number.isFinite(minutes) || minutes <= 0) {
    throw new Error("学习时长须大于 0 分钟。");
  }
  const points = Number(values.points);
  if (!Number.isFinite(points) || points < 0) {
    throw new Error("完成积分不能为负数。");
  }
  return {
    id: `course-${globalThis.crypto?.randomUUID?.() || Date.now()}`,
    title,
    subtitle: String(values.subtitle || "").trim(),
    category: values.category || "理论学习",
    minutes,
    points,
    cover: Number(values.cover) || 1,
    content,
    orgScope,
    orgName: selected.label,
    status: publish ? "published" : "draft",
    students: "0",
    createdBy: user.id,
    createdAt: now,
    publishedAt: publish ? now : null,
  };
}

export function publishDemoCourse(
  offerings,
  id,
  session,
  now = new Date().toISOString(),
) {
  const course = (offerings || []).find(
    (item) => String(item.id) === String(id),
  );
  if (!course) throw new Error("课程不存在。");
  if (!canManageOffering(course, session)) {
    throw new Error("当前账号不能发布该课程。");
  }
  return (offerings || []).map((item) =>
    String(item.id) === String(id)
      ? { ...item, status: "published", publishedAt: now }
      : item,
  );
}
