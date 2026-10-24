import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildSchoolData,
  decideSchoolRecord,
  filterSchoolRecords,
  formatSchoolTime,
  isSchoolOverdue,
  schoolMeetingRecords,
} from "../src/school-data.js";
import {
  SCHOOL_NAVIGATION,
  schoolNavigationGroup,
} from "../src/school-navigation.js";
import { demoSession, hasPermission } from "../src/roles.js";
const session = demoSession("school");
const seed = () => buildSchoolData().schoolWorkItems;

test("school workspace reads real meeting transcript without treating structured minutes as text", () => {
  const records = schoolMeetingRecords([
    {
      id: "real-meeting", title: "真实接口记录", org_unit_id: "branch",
      scheduled_on: "2026-10-24", transcript: "学习要点：核对实际材料。",
      minutes: { learning_points: [{ text: "核对实际材料。" }] },
      review_status: "pending", revision: 2,
    },
    { id: "empty", minutes: {}, transcript: "" },
  ], [{ id: "branch", name: "合成支部" }]);
  assert.equal(records[0].materials[0].complete, true);
  assert.equal(records[0].materials[0].content, "学习要点：核对实际材料。");
  assert.equal(records[1].materials[0].complete, false);
});
test("returned meeting and supplement-required business items share the missing-material filter", () => {
  const records = [
    { id: "meeting", status: "已退回" },
    { id: "business", status: "待补充" },
    { id: "done", status: "已归档" },
  ];
  assert.deepEqual(
    filterSchoolRecords(records, { status: "待补充" }).map((r) => r.id),
    ["meeting", "business"],
  );
});
test("live meeting transcripts remain available to the school material checklist", () => {
  const [record] = schoolMeetingRecords(
    [
      {
        id: "live",
        date: "2026-10-23",
        status: "待审核",
        transcript: "已提交的正式纪要",
        revision: 4,
      },
    ],
    [],
  );
  assert.equal(record.materials[0].complete, true);
  assert.equal(record.materials[0].content, "已提交的正式纪要");
});
test("a different school officer can archive without replacing the original reviewer", () => {
  const record = seed()[0];
  const approved = decideSchoolRecord(
    session,
    record,
    record.revision,
    "approve",
    "已完成学校审核",
  );
  const archivist = {
    ...session,
    user: { ...session.user, id: "school-archivist", name: "归档确认员" },
  };
  const archived = decideSchoolRecord(
    archivist,
    approved,
    approved.revision,
    "archive",
    "已核对归档条件",
  );
  assert.equal(archived.reviewedBy, session.user.name);
  assert.equal(archived.archivedBy, "归档确认员");
  assert.equal(archived.history.at(-1).actor, "归档确认员");
});
test("school history uses Beijing time and preserves already local timestamps", () => {
  assert.equal(
    formatSchoolTime("2026-10-23T03:45:00.000Z"),
    "2026-10-23 11:45",
  );
  assert.equal(formatSchoolTime("2026-10-16 10:20"), "2026-10-16 10:20");
});

test("school navigation has seven groups and routes every secondary entry once", () => {
  assert.deepEqual(
    SCHOOL_NAVIGATION.map((n) => n.label),
    [
      "学校工作台",
      "组织与党员",
      "党员发展",
      "组织生活",
      "学习教育",
      "考核与统计",
      "校级管理",
    ],
  );
  const routes = SCHOOL_NAVIGATION.flatMap((n) => n.items.map(([id]) => id));
  assert.equal(new Set(routes).size, routes.length);
  assert.equal(schoolNavigationGroup("archive").label, "组织与党员");
  assert.equal(schoolNavigationGroup("inbox").label, "党员发展");
});
test("organization, year and stage filters apply together without leaking other records", () => {
  const record = seed().find((r) => r.id === "dev-1");
  const result = filterSchoolRecords(seed(), {
    year: record.year,
    department: record.department,
    orgId: record.orgId,
    stage: record.stage,
    business: record.business,
  });
  assert.deepEqual(
    result.map((r) => r.id),
    [record.id],
  );
  assert.equal(filterSchoolRecords(seed(), { year: "2024" }).length, 0);
});
test("overdue means an unfinished item with a deadline strictly before today", () => {
  const record = seed()[0];
  assert.equal(
    isSchoolOverdue({ ...record, dueDate: "2026-10-22" }, "2026-10-23"),
    true,
  );
  assert.equal(
    isSchoolOverdue({ ...record, dueDate: "2026-10-23" }, "2026-10-23"),
    false,
  );
  assert.equal(
    isSchoolOverdue({ ...record, dueDate: "" }, "2026-10-23"),
    false,
  );
  for (const status of ["已通过", "已归档"])
    assert.equal(
      isSchoolOverdue(
        { ...record, status, dueDate: "2026-10-22" },
        "2026-10-23",
      ),
      false,
    );
});
test("a meeting date alone does not invent a review deadline", () => {
  const [record] = schoolMeetingRecords(
    [
      {
        id: "m",
        date: "2026-10-01",
        status: "待审核",
        title: "会议",
        minutes: "纪要",
      },
    ],
    [],
  );
  assert.equal(record.dueDate, "");
  assert.equal(isSchoolOverdue(record, "2026-10-23"), false);
});
test("approval and archival are separate actions with retained opinions and versions", () => {
  const record = seed().find((r) => r.id === "dev-1");
  const approved = decideSchoolRecord(
    session,
    record,
    record.revision,
    "approve",
    "材料与院系核验意见已核对",
  );
  assert.equal(approved.status, "已通过");
  assert.equal(approved.archived, false);
  assert.equal(record.status, "待审核");
  const archived = decideSchoolRecord(
    session,
    approved,
    approved.revision,
    "archive",
    "审核与材料符合学校归档要求",
  );
  assert.equal(archived.status, "已归档");
  assert.equal(archived.history.length, record.history.length + 2);
  assert.equal(archived.history.at(-1).actor, session.user.name);
  assert.equal(archived.revision, record.revision + 2);
});
test("review blocks self approval, stale revision, wrong tenant and missing materials", () => {
  const record = seed()[0];
  assert.throws(
    () =>
      decideSchoolRecord(
        session,
        { ...record, submittedBy: session.user.id },
        2,
        "approve",
        "已核对",
      ),
    /提交人/,
  );
  assert.throws(
    () => decideSchoolRecord(session, record, 1, "approve", "已核对"),
    /版本/,
  );
  assert.throws(
    () =>
      decideSchoolRecord(
        session,
        { ...record, tenant_id: "another-school" },
        2,
        "approve",
        "已核对",
      ),
    /当前学校/,
  );
  const incomplete = {
    ...record,
    materials: [{ name: "证明", complete: false }],
  };
  assert.throws(
    () => decideSchoolRecord(session, incomplete, 2, "approve", "已核对"),
    /尚未齐全/,
  );
  const returned = decideSchoolRecord(
    session,
    incomplete,
    2,
    "return",
    "请补交证明材料",
  );
  assert.equal(returned.status, "待补充");
  assert.equal(returned.history.at(-1).opinion, "请补交证明材料");
});
test("school account authority includes identity management while platform operations stay restricted", () => {
  assert.equal(hasPermission(session, "admin.identity"), true);
  assert.equal(hasPermission(session, "admin.ops"), false);
  assert.equal(hasPermission(session, "assessment.configure"), true);
  assert.equal(hasPermission(demoSession("platform"), "admin.identity"), true);
  assert.throws(
    () =>
      decideSchoolRecord(
        demoSession("department"),
        seed()[0],
        2,
        "approve",
        "已核对",
      ),
    /权限/,
  );
  assert.throws(
    () => decideSchoolRecord(session, seed()[0], 2, "approve", "  "),
    /意见/,
  );
});
