import test from "node:test";
import assert from "node:assert/strict";
import { formatBusinessTime } from "../src/business-time.js";
import { normalizeStoredSystemCopy } from "../src/system-copy.js";
import {
  memberPayload,
  normalizeMember,
  meetingPayload,
  meetingParticipants,
  branchOrganizations,
} from "../src/contracts.js";
import { leagueEligibility } from "../src/league-eligibility.js";

test("stored system text upgrades preserve identity, attachments and user-authored business content", () => {
  const input = {
    members: [{ id: "member-1", orgId: "org-1", note: "本地演示档案" }],
    personalMaterials: [
      { id: "demo-material-student", owner_id: "demo-student", profile_id: "member-413", title: "10月学习心得（示例）", file_name: "学习心得-示例.txt", has_file: false },
      { id: "custom-1", owner_id: "demo-student", title: "演示教学学习心得", file_name: "演示教学.pdf", has_file: true },
      { id: "demo-material-applicant", title: "手工修订标题", description: "我参加了教学演示。" },
    ],
    accounts: [{ id: "demo-student", tenant_id: "school-1", profile_id: "member-413", is_active: true }],
    developmentProfiles: { "member-413": { current_stage: "正式党员", materials: [{ id: "demo-dev-member-413-0", note: "本地演示材料清单，具体要求以组织审核为准。", review_status: "approved" }] } },
  };
  const original = structuredClone(input);
  const output = normalizeStoredSystemCopy(input);
  assert.deepEqual(input, original);
  assert.equal(output.members[0].note, "党员档案登记信息");
  assert.equal(output.personalMaterials[0].title, "10月学习心得");
  assert.equal(output.personalMaterials[0].file_name, "学习心得.txt");
  for (const key of ["id", "owner_id", "profile_id", "has_file"]) {
    assert.equal(output.personalMaterials[0][key], input.personalMaterials[0][key]);
  }
  assert.deepEqual(output.personalMaterials.slice(1), input.personalMaterials.slice(1));
  assert.deepEqual(output.accounts, input.accounts);
  assert.equal(output.developmentProfiles["member-413"].materials[0].review_status, "approved");
  assert.deepEqual(normalizeStoredSystemCopy(output), output);
});

test("stored reply and backup copy retain provenance without changing user questions or real checksums", () => {
  const input = {
    messages: [
      { id: "q", role: "user", content: "请分析演示教学的安排" },
      { id: "a", role: "assistant", conversationId: "session-1", owner_id: "demo-student", content: "已登记", disclaimer: "演示回答 · 未进行真实知识检索，请以正式制度和组织审核意见为准。", citations: [] },
    ],
    platform: { config: { unchanged: true }, backups: [
      { id: "backup-1", checksum: "demo-sha256-8f61b36a", scope: "配置与业务索引快照（演示）" },
      { id: "real-record", checksum: "a".repeat(64), scope: "业务原件" },
    ] },
  };
  const output = normalizeStoredSystemCopy(input);
  assert.deepEqual(output.messages[0], input.messages[0]);
  assert.equal(output.messages[1].disclaimer, "办理参考 · 请以现行制度和组织审核意见为准。");
  assert.equal(output.messages[1].conversationId, "session-1");
  assert.equal(output.platform.backups[0].checksum, "");
  assert.deepEqual(output.platform.backups[1], input.platform.backups[1]);
  assert.deepEqual(output.platform.config, input.platform.config);
  assert.deepEqual(normalizeStoredSystemCopy(output), output);
});
test("business UTC timestamps display in Beijing time across the calendar boundary", () => {
  assert.equal(formatBusinessTime("2026-10-24T23:15:30.123456"), "2026-10-25 07:15:30");
  assert.equal(formatBusinessTime("2026-10-24 05:06:00"), "2026-10-24 13:06:00");
  assert.equal(formatBusinessTime("2026-10-24T13:06:00+08:00"), "2026-10-24 13:06:00");
});
test("business time formatting preserves date-only deadlines and rejects unavailable timestamps", () => {
  assert.equal(formatBusinessTime("2026-10-24"), "2026-10-24");
  assert.equal(formatBusinessTime(null), "—");
  assert.equal(formatBusinessTime("invalid"), "—");
});
test("school branch statistics exclude school and department organizations in the real API response", () => {
  const organizations = [
    { id: "school", org_type: "school", name: "测试学校党委" },
    { id: "department", org_type: "department", name: "测试院系党委" },
    { id: "branch", org_type: "branch", name: "测试党支部" },
    { id: "demo", type: "学生党支部", department: "演示学院" },
    { id: "unknown", name: "未说明类型的组织" },
  ];
  assert.deepEqual(branchOrganizations(organizations).map((row) => row.id), ["branch", "demo"]);
});
test("member creation uses the actual backend stage codes and only supported fields", () => {
  const body = memberPayload({
    name: "测试人员",
    orgId: "org-1",
    stage: "正式党员",
    number: "private-number",
  });
  assert.deepEqual(body, {
    name: "测试人员",
    org_unit_id: "org-1",
    current_stage: "member",
    birth_date: null,
    league_joined_on: null,
    materials: [],
    pending: 0,
  });
  assert.equal(
    memberPayload({ name: "小王", orgId: "org-2", stage: "发展对象" })
      .current_stage,
    "candidate",
  );
  assert.deepEqual(
    memberPayload({
      name: "小李",
      orgId: "org-3",
      stage: "入党积极分子",
      birth_date: "2000-05-04",
      league_joined_on: "2018-05-04",
    }),
    {
      name: "小李",
      org_unit_id: "org-3",
      current_stage: "activist",
      birth_date: "2000-05-04",
      league_joined_on: "2018-05-04",
      materials: [],
      pending: 0,
    },
  );
});
test("backend roster stages and relation state remain readable without inventing personal fields", () => {
  const member = normalizeMember({
    id: "real-id",
    name: "测试人员",
    stage: "probationary",
    org_name: "授权支部",
    org_unit_id: "org-1",
    relation_status: "out_pending",
    stage_joined_on: "2026-03-01",
  });
  assert.equal(member.stage, "预备党员");
  assert.equal(member.relation, "转出待接收");
  assert.equal(member.phone, "未提供");
  assert.equal(member.number, "real-id");
});
test("meeting create excludes context, transcript, attendance totals and revision fields forbidden by ActivityCreate", () => {
  const body = meetingPayload({
    title: "支部大会",
    date: "2026-10-28",
    host: "组织员",
    agenda: "学习与讨论",
    activityType: "branch_member_meeting",
    orgId: "org-1",
    location: "A301",
    time: "14:30",
    minutes: "不能伪造成新建纪要",
  });
  assert.deepEqual(
    Object.keys(body).sort(),
    [
      "scheduled_on",
      "host",
      "agenda",
      "reason",
      "org_unit_id",
      "activity_type",
      "title",
      "participants",
      "source_doc_ids",
    ].sort(),
  );
  assert.deepEqual(body.participants, []);
});
test("meeting update sends topic and expected revision without mutating organization or activity type", () => {
  const body = meetingPayload(
    {
      title: "修订主题",
      date: "2026-10-23",
      host: "组织员",
      agenda: "修订议程",
      minutes: "真实记录",
      orgId: "forbidden",
    },
    { id: "meeting-1", revision: 4 },
  );
  assert.equal(body.topic, "修订主题");
  assert.equal(body.expected_revision, 4);
  assert.equal(body.transcript, "真实记录");
  assert.ok(!("title" in body));
  assert.ok(!("org_unit_id" in body));
  assert.ok(!("activity_type" in body));
});

test("meeting attendance preserves actual names and identifiers and update sends the held date", () => {
  const participants = meetingParticipants("staff-1 | 张三 | 出席\nstudent-2 | 李四 | 缺席");
  assert.deepEqual(participants, [
    { participant_id: "staff-1", name: "张三", attended: true },
    { participant_id: "student-2", name: "李四", attended: false },
  ]);
  const values = { title: "实际会议", date: "2026-10-23", heldOn: "2026-10-24", participants, minutes: "学习要点：原始记录" };
  const body = meetingPayload(values, { id: "record", revision: 2 });
  assert.deepEqual(body.participants, participants);
  assert.equal(body.held_on, "2026-10-24");
  assert.deepEqual(meetingPayload(values).participants, participants);
  assert.throws(() => meetingParticipants("staff-1 | 张三 | 出席\nstaff-1 | 李四 | 出席"), /重复/);
  assert.throws(() => meetingParticipants("staff-1 | 张三"), /编号/);
  assert.throws(() => meetingParticipants("staff-1 | 张三 | 未知"), /出席/);
});

test("league recommendation eligibility checks age and one-year tenure at the recommendation date", () => {
  const on = new Date(2026, 9, 28);
  assert.equal(leagueEligibility("2008-10-28", "2025-10-28", on).eligible, true);
  assert.equal(leagueEligibility("2008-10-29", "2025-10-28", on).eligible, false);
  assert.match(leagueEligibility("2008-10-29", "2025-10-28", on).note, /18周岁/);
  assert.equal(leagueEligibility("2008-01-01", "2025-10-29", on).eligible, false);
  assert.match(leagueEligibility("2008-01-01", "2025-10-29", on).note, /入团满1年/);
  assert.equal(leagueEligibility("", "2025-10-28", on).eligible, null);
  assert.match(leagueEligibility("", "2025-10-28", on).note, /出生年月/);
  assert.equal(leagueEligibility("2008-01-01", "", on).eligible, null);
  assert.equal(leagueEligibility("2008-02-29", "2025-02-28", new Date(2026, 1, 28)).eligible, true);
});
