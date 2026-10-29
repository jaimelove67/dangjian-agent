import { test } from "node:test";
import assert from "node:assert/strict";
import { demoSession, sessionForAccount } from "../src/roles.js";
import { DEPARTMENTS, organizations } from "../src/data.js";
import {
  canManageCourses,
  canManageOffering,
  courseScopeOptions,
  courseVisibleTo,
  createDemoCourse,
  publishDemoCourse,
  visibleDemoCourses,
} from "../src/demo-courses.js";

const school = demoSession("school");
const department = demoSession("department");
const secretary = demoSession("secretary");
const organizer = demoSession("organizer");
const student = demoSession("student");
const applicant = demoSession("applicant");

function values(overrides = {}) {
  return {
    title: "习近平新时代中国特色社会主义思想专题辅导",
    subtitle: "集中学习与交流研讨",
    category: "理论学习",
    minutes: 45,
    points: 12,
    cover: 2,
    content: "围绕课程主题开展个人自学，并结合岗位实际记录学习体会。",
    orgScope: "school",
    ...overrides,
  };
}

test("demo course management follows organization roles and education permission", () => {
  assert.equal(canManageCourses(school), true);
  assert.equal(canManageCourses(department), true);
  assert.equal(canManageCourses(secretary), true);
  assert.equal(canManageCourses(organizer), true);
  assert.equal(canManageCourses(student), false);
  assert.equal(canManageCourses(applicant), false);
});

test("course scope options are limited to the current administrator", () => {
  const schoolOptions = courseScopeOptions(school);
  assert.equal(schoolOptions[0].label, "全校");
  assert.equal(schoolOptions.length, DEPARTMENTS.length + 1);

  const departmentOptions = courseScopeOptions(department);
  assert.equal(departmentOptions[0].value, `department:${department.user.department}`);
  assert.ok(
    departmentOptions
      .slice(1)
      .every(
        (option) =>
          organizations.find((org) => org.id === option.value)?.department ===
          department.user.department,
      ),
  );

  const branchOptions = courseScopeOptions(secretary);
  assert.equal(branchOptions.length, 1);
  assert.equal(branchOptions[0].value, secretary.user.org_unit_id);
});

test("published courses reach learners while drafts stay with course managers", () => {
  const published = createDemoCourse(
    values(),
    school,
    true,
    "2026-10-28T08:00:00.000Z",
  );
  assert.equal(published.status, "published");
  assert.equal(published.orgName, "全校");
  assert.equal(courseVisibleTo(published, student), true);
  assert.equal(visibleDemoCourses([published], student, false).length, 1);

  const draft = createDemoCourse(
    values({ title: "草稿课程" }),
    school,
    false,
    "2026-10-28T09:00:00.000Z",
  );
  assert.equal(draft.status, "draft");
  assert.equal(visibleDemoCourses([draft], school, true).length, 1);
  assert.equal(visibleDemoCourses([draft], student, false).length, 0);
});

test("publishing a draft is permission checked and immediately visible", () => {
  const draft = createDemoCourse(
    values({ title: "待发布课程" }),
    school,
    false,
    "2026-10-28T10:00:00.000Z",
  );
  assert.throws(
    () =>
      publishDemoCourse(
        [draft],
        draft.id,
        student,
        "2026-10-28T11:00:00.000Z",
      ),
    /不能发布/,
  );
  const updated = publishDemoCourse(
    [draft],
    draft.id,
    school,
    "2026-10-28T11:00:00.000Z",
  );
  assert.equal(updated[0].status, "published");
  assert.equal(visibleDemoCourses(updated, student, false).length, 1);
});

test("branch and department scopes prevent cross-organization visibility", () => {
  const branchCourse = createDemoCourse(
    values({ title: "支部专题党课", orgScope: secretary.user.org_unit_id }),
    secretary,
    true,
    "2026-10-28T12:00:00.000Z",
  );
  const otherOrg = organizations.find(
    (org) => org.department !== secretary.user.department,
  );
  const otherMember = sessionForAccount({
    id: "other-member",
    name: "其他院系党员",
    username: "other-member",
    role: "member",
    tenant_id: "school-1",
    org_unit_id: otherOrg.id,
    department: otherOrg.department,
  });
  assert.equal(courseVisibleTo(branchCourse, student), true);
  assert.equal(courseVisibleTo(branchCourse, otherMember), false);
  assert.equal(courseVisibleTo(branchCourse, department), true);
  assert.equal(canManageOffering(branchCourse, secretary), true);
  assert.equal(canManageOffering(branchCourse, organizer), false);

  const departmentCourse = createDemoCourse(
    values({
      title: "院系集中学习",
      orgScope: `department:${department.user.department}`,
    }),
    department,
    true,
    "2026-10-28T13:00:00.000Z",
  );
  assert.equal(courseVisibleTo(departmentCourse, student), true);
  assert.equal(courseVisibleTo(departmentCourse, otherMember), false);
  assert.equal(canManageOffering(departmentCourse, department), true);
});

test("a department administrator cannot publish a school-level draft", () => {
  const draft = createDemoCourse(
    values({ title: "校级课程" }),
    school,
    false,
    "2026-10-28T14:00:00.000Z",
  );
  assert.equal(canManageOffering(draft, department), false);
  assert.equal(visibleDemoCourses([draft], department, true).length, 0);
});
