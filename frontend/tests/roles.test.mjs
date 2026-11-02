import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEMO_PERSONAS,
  ROLE_INFO,
  demoSession,
  canAccess,
  hasPermission,
  scopedMembers,
  scopedOrganizations,
  memberInScope,
  memberMatchesOrganization,
  scopedMeetings,
  sessionForAccount,
  activityInScope,
} from "../src/roles.js";
import {
  seedActivities,
  seedMembers,
  STAGES,
  organizations,
} from "../src/data.js";
import { SCHOOL_NAVIGATION } from "../src/school-navigation.js";
import {
  roleSeed,
  extendRoleData,
  materialSource,
  materialSourceNote,
  materialTypeLabel,
  buildDemoFlowBoard,
  emptyProcedureState,
  addDemoProcedure,
} from "../src/role-data.js";
import {
  submitDemoMeeting,
  reviewDemoMeeting,
  transitionDemoMember,
  linkDemoAccount,
} from "../src/role-actions.js";
import { validateMaterialFile } from "../src/material-validation.js";

test("eight demo personas cover seven real roles and explicitly bind personal accounts", () => {
  assert.equal(DEMO_PERSONAS.length, 8);
  assert.equal(new Set(DEMO_PERSONAS.map((p) => p.user.role)).size, 7);
  for (const id of ["teacher", "student", "applicant"]) {
    const { user } = demoSession(id);
    assert.ok(seedMembers.some((m) => m.id === user.profile_id));
  }
  assert.deepEqual(
    demoSession("teacher").permissions,
    demoSession("student").permissions,
  );
});
test("a wildcard or forged explicit permission never grants a role extra authority", () => {
  const s = demoSession("student");
  s.permissions.push("*", "member.query", "admin.identity");
  assert.equal(hasPermission(s, "member.query"), false);
  assert.equal(
    canAccess(s, { id: "members", permission: "member.query" }),
    false,
  );
  assert.equal(
    canAccess(
      { ...s, user: { ...s.user, role: "unknown" } },
      { id: "dashboard" },
    ),
    false,
  );
});
test("self-service menus exclude organization management while party members can view activities", () => {
  for (const id of ["teacher", "student"]) {
    const s = demoSession(id);
    for (const route of [
      "members",
      "reviews",
      "accounts",
      "knowledge",
      "analytics",
    ])
      assert.equal(canAccess(s, { id: route }), false);
    for (const route of [
      "dashboard",
      "self-archive",
      "self-materials",
      "learning",
      "assistant",
      "activities",
    ])
      assert.equal(canAccess(s, { id: route }), true);
  }
  const applicant = demoSession("applicant");
  for (const route of [
    "members",
    "reviews",
    "accounts",
    "knowledge",
    "analytics",
    "activities",
  ])
    assert.equal(canAccess(applicant, { id: route }), false);
  for (const route of [
    "dashboard",
    "self-archive",
    "self-materials",
    "learning",
    "assistant",
  ])
    assert.equal(canAccess(applicant, { id: route }), true);
});
test("learning courses are visible to members and applicants without center-group authority", () => {
  for (const id of ["teacher", "student", "applicant"]) {
    const s = demoSession(id);
    assert.equal(hasPermission(s, "education.query"), true);
    assert.equal(hasPermission(s, "study.query"), false);
    assert.equal(
      canAccess(s, { id: "learning", permission: "education.query" }),
      true,
    );
  }
});
test("school learning navigation exposes a direct course and activity entry", () => {
  const group = SCHOOL_NAVIGATION.find(
    (item) => item.id === "school-learning",
  );
  assert.ok(group);
  assert.ok(
    group.items.some(
      ([id, label]) => id === "learning" && label === "课程与活动",
    ),
  );
  assert.equal(
    canAccess(demoSession("school"), {
      id: "learning",
      permission: "education.query",
    }),
    true,
  );
});
test("school identity permissions do not open platform-only account management", () => {
  const route = {
    id: "accounts",
    permission: "admin.identity",
    roles: ["system_admin"],
  };
  assert.equal(canAccess(demoSession("school"), route), false);
  assert.equal(canAccess(demoSession("platform"), route), true);
  assert.equal(
    canAccess(demoSession("school"), { id: "analytics", demo: true }, true),
    false,
  );
});
test("department and branch scopes select only their own roster and organizations", () => {
  for (const id of ["department", "secretary", "organizer"]) {
    const s = demoSession(id),
      members = scopedMembers({ members: seedMembers }, s),
      orgs = scopedOrganizations(s);
    assert.ok(members.length > 0 && members.length < seedMembers.length);
    assert.ok(members.every((m) => memberInScope(s.user, m)));
    assert.ok(members.every((m) => orgs.some((o) => o.id === m.orgId)));
  }
  assert.equal(scopedOrganizations(demoSession("secretary")).length, 1);
  assert.equal(
    scopedMembers({ members: seedMembers }, demoSession("student")).length,
    1,
  );
});
test("organization drill-down filters by id, including descendant ids, without a false name mismatch", () => {
  const member = { orgId: "branch", organization: "第一支部", department: "学院" };
  assert.equal(memberMatchesOrganization(member, "", new Set(["dept", "branch"])), true);
  assert.equal(memberMatchesOrganization(member, "", new Set(["other"])), false);
  assert.equal(memberMatchesOrganization(member, "第一支部", null), true);
  assert.equal(memberMatchesOrganization(member, "学院", null), true);
  assert.equal(memberMatchesOrganization(member, "其他支部", null), false);
});
test("new department accounts use supplied organization scope without upgrading permissions", () => {
  const s = sessionForAccount({
    id: "new",
    role: "department_admin",
    department: DEMO_PERSONAS[2].user.department,
  });
  assert.ok(scopedMembers({ members: seedMembers }, s).length > 0);
  assert.equal(hasPermission(s, "admin.identity"), false);
});
test("role data migration is idempotent and personal fixtures stay explicitly owned", () => {
  const once = extendRoleData({ meetings: [], members: seedMembers });
  const twice = extendRoleData(once);
  assert.equal(twice.meetings.length, 1);
  assert.equal(twice.accounts.length, 10);
  assert.ok(
    twice.personalMaterials.every(
      (m) => m.owner_id && m.profile_id && !m.has_file,
    ),
  );
});
test("existing user-created activities receive one notification on migration", () => {
  const activity = {
    id: "user-activity-notice-1",
    title: "已发布的主题党日",
    date: "2026-11-01",
    organization: "机械工程学院",
    orgId: "",
  };
  const once = extendRoleData({
    meetings: [],
    members: seedMembers,
    activities: [...seedActivities, activity],
    tasks: [],
  });
  const notices = once.tasks.filter((task) => task.kind === "activity_notice");
  assert.equal(notices.length, 1);
  assert.equal(notices[0].activity_id, activity.id);
  assert.equal(notices[0].route, "activities");
  const twice = extendRoleData(once);
  assert.equal(
    twice.tasks.filter((task) => task.kind === "activity_notice").length,
    1,
  );
});
test("meeting submit requires in-scope editable revision and nonempty saved minutes", () => {
  const s = demoSession("organizer"),
    draft = {
      ...roleSeed().roleMeeting,
      status: "待召开",
      revision: 1,
      submitted_by: null,
    };
  const pending = submitDemoMeeting(s, draft, 1, "参会与纪要已核对");
  assert.equal(pending.status, "待审核");
  assert.equal(pending.submitted_by, s.user.id);
  assert.equal(pending.revision, 2);
  assert.throws(
    () => submitDemoMeeting(s, { ...draft, minutes: "" }, 1, "提交"),
    /纪要/,
  );
  assert.throws(() => submitDemoMeeting(s, draft, 0, "提交"), /版本/);
  assert.throws(
    () => submitDemoMeeting(demoSession("student"), draft, 1, "提交"),
    /范围/,
  );
});
test("independent reviewer approves or returns a current pending version, never own submission", () => {
  const m = roleSeed().roleMeeting,
    s = demoSession("secretary");
  assert.throws(
    () =>
      reviewDemoMeeting(
        demoSession("organizer"),
        m,
        m.revision,
        "approved",
        "已核对",
      ),
    /提交人不能/,
  );
  assert.throws(() => reviewDemoMeeting(s, m, 1, "approved", "已核对"), /变化/);
  assert.throws(
    () => reviewDemoMeeting(s, null, 1, "approved", "已核对"),
    /不存在/,
  );
  const approved = reviewDemoMeeting(
    s,
    m,
    m.revision,
    "approved",
    "纪要与参会情况相符",
  );
  assert.equal(approved.status, "已完成");
  assert.equal(approved.reviewed_by, s.user.id);
  assert.throws(
    () => reviewDemoMeeting(s, approved, approved.revision, "rejected", "退回"),
    /变化/,
  );
  assert.equal(
    reviewDemoMeeting(s, m, m.revision, "rejected", "请补充佐证").status,
    "已退回",
  );
});
test("review permission cannot cross a different branch", () => {
  const m = {
    ...roleSeed().roleMeeting,
    orgId: seedMembers.find(
      (m) => m.orgId !== demoSession("secretary").user.org_unit_id,
    ).orgId,
  };
  assert.equal(
    scopedMeetings({ meetings: [m] }, demoSession("secretary")).length,
    0,
  );
  assert.throws(
    () =>
      reviewDemoMeeting(
        demoSession("secretary"),
        m,
        m.revision,
        "approved",
        "核对",
      ),
    /范围/,
  );
});
test("manual development requires an adjacent stage, real opinion, and in-scope officer", () => {
  const s = demoSession("organizer"),
    member = seedMembers.find(
      (m) => m.id === demoSession("applicant").user.profile_id,
    );
  assert.equal(
    transitionDemoMember(s, member, STAGES[1], "支部讨论登记", "同意办理")
      .stage,
    STAGES[1],
  );
  assert.throws(
    () => transitionDemoMember(s, member, STAGES[3], "依据", "意见"),
    /相邻/,
  );
  assert.throws(
    () => transitionDemoMember(s, member, STAGES[1], "", "意见"),
    /依据/,
  );
  assert.throws(
    () =>
      transitionDemoMember(
        demoSession("applicant"),
        member,
        STAGES[1],
        "依据",
        "意见",
      ),
    /范围/,
  );
});
test("material validation rejects empty, oversized, unsupported and path-like filenames", () => {
  for (const file of [
    { name: "a.txt", size: 0 },
    { name: "old.doc", size: 1 },
    { name: "../a.txt", size: 1 },
    { name: "a.pdf", size: 11 },
  ])
    assert.throws(() => validateMaterialFile(file, 10));
  assert.doesNotThrow(() =>
    validateMaterialFile({ name: "学习心得.TXT", size: 10 }, 10),
  );
});
test("personal material shows its category and source without becoming a development material", () => {
  const personal = {
    id: "material-personal",
    material_type: "",
    category: "thought_report",
    title: "111",
    source: "personal",
  };
  assert.equal(materialSource(personal), "personal");
  assert.equal(materialTypeLabel(personal), "思想汇报（个人提交）");
  assert.equal(
    materialSourceNote(personal),
    "个人材料，不纳入发展材料核验",
  );

  const development = {
    id: "material-development",
    material_type: "入党申请书",
    source: "development",
  };
  assert.equal(materialSource(development), "development");
  assert.equal(materialTypeLabel(development), "入党申请书");
  assert.equal(materialSourceNote(development), "组织登记");

  const legacy = {
    legacy_material: true,
    material_type: "思想汇报",
    source: "legacy",
  };
  assert.equal(materialSource(legacy), "legacy");
  assert.equal(materialTypeLabel(legacy), "思想汇报");
  assert.equal(materialSourceNote(legacy), "历史登记，待核验原件");
});
test("explicit account linking rejects different organizations, duplicate ownership and overwrites", () => {
  const s = demoSession("organizer"),
    member = seedMembers.find(
      (m) => m.id === demoSession("applicant").user.profile_id,
    );
  const account = {
    id: "new",
    username: "new_applicant",
    role: "applicant",
    is_active: true,
    org_unit_id: member.orgId,
    tenant_id: s.user.tenant_id,
    profile_id: null,
  };
  assert.equal(
    linkDemoAccount(s, member, [account], "new_applicant")[0].profile_id,
    member.id,
  );
  assert.throws(
    () =>
      linkDemoAccount(
        s,
        member,
        [{ ...account, org_unit_id: "different" }],
        "new_applicant",
      ),
    /同一组织/,
  );
  assert.throws(
    () =>
      linkDemoAccount(
        s,
        member,
        [{ ...account, profile_id: "different-profile" }],
        "new_applicant",
      ),
    /其他档案/,
  );
  assert.throws(
    () =>
      linkDemoAccount(
        s,
        member,
        [account, { ...account, id: "other", profile_id: member.id }],
        "new_applicant",
      ),
    /其他账号/,
  );
});
test("department activities reach branch users in the same department without leaking other branches", () => {
  const department = demoSession("department").user;
  const secretary = demoSession("secretary").user;
  const teacher = demoSession("teacher").user;
  assert.equal(
    activityInScope(department, { organization: department.department }),
    true,
  );
  assert.equal(
    activityInScope(secretary, { organization: secretary.department }),
    true,
  );
  assert.equal(
    activityInScope(secretary, { orgId: secretary.org_unit_id }),
    true,
  );
  const otherBranch = organizations.find(
    (org) =>
      org.id !== secretary.org_unit_id &&
      org.department === secretary.department,
  );
  assert.equal(
    activityInScope(secretary, { orgId: otherBranch.id }),
    false,
  );
  assert.equal(
    activityInScope(department, { orgId: secretary.org_unit_id }),
    true,
  );
  assert.equal(
    activityInScope(department, { organization: "其他学院" }),
    false,
  );
  assert.equal(
    activityInScope(teacher, { organization: teacher.department }),
    true,
  );
  assert.equal(
    activityInScope(demoSession("applicant").user, {
      organization: demoSession("applicant").user.department,
    }),
    false,
  );
});
test("demo flow board exposes probation reminders and closes them after party-group registration", () => {
  const member = seedMembers.find((m) => m.stage === "预备党员");
  const first = buildDemoFlowBoard([member], {}, []);
  const firstItem = first.items[0];
  assert.equal(firstItem.current_stage, "probationary");
  assert.deepEqual(
    new Set(firstItem.reminders.map((r) => r.kind)),
    new Set(["higher_record", "party_group", "oath"]),
  );
  const procedures = addDemoProcedure(emptyProcedureState(), {
    kind: "party_group",
    occurred_on: "2026-10-20",
    status: "assigned",
    summary: "编入第一党小组",
    details: { party_branch: "第一党支部", party_group: "第一党小组" },
    created_at: "2026-10-20T10:00:00+08:00",
  });
  const second = buildDemoFlowBoard(
    [member],
    { [member.id]: { procedures } },
    [],
  );
  const secondItem = second.items[0];
  assert.ok(!secondItem.reminders.some((r) => r.kind === "party_group"));
  assert.ok(!secondItem.missing.includes("编入党支部和党小组"));
  assert.ok(
    !buildDemoFlowBoard([member], {}, [`demo-${member.id}-oath`]).items[0]
      .reminders.some((r) => r.kind === "oath"),
  );
});
test("demo probationary membership can enter the terminal disqualified stage", () => {
  const s = demoSession("school");
  const member = seedMembers.find((m) => m.stage === "预备党员");
  const next = transitionDemoMember(
    s,
    member,
    "取消预备党员资格",
    "支部大会决定",
    "取消预备党员资格",
    "2026-10-20",
  );
  assert.equal(next.stage, "取消预备党员资格");
  assert.throws(
    () =>
      transitionDemoMember(
        s,
        seedMembers.find((m) => m.stage === "发展对象"),
        "取消预备党员资格",
        "依据",
        "意见",
        "2026-10-20",
      ),
    /只有预备党员/,
  );
});
test("manual stage registration synchronizes the own archive date with the decision date", () => {
  const s = demoSession("organizer"),
    member = seedMembers.find(
      (m) => m.id === demoSession("applicant").user.profile_id,
    );
  const next = transitionDemoMember(
    s,
    member,
    STAGES[1],
    "支部决定",
    "人工登记",
    "2026-10-20",
  );
  assert.equal(next.joined, "2026-10-20");
  assert.equal(next.stage_joined_on, "2026-10-20");
  assert.equal(
    transitionDemoMember(
      s,
      { ...member, stage: "退回" },
      STAGES[1],
      "退回后重新考察",
      "同意重新列为入党积极分子",
      "2026-10-20",
    ).stage,
    STAGES[1],
  );
  assert.throws(
    () =>
      transitionDemoMember(s, member, STAGES[1], "依据", "意见", "2099-01-01"),
    /决定日期/,
  );
});
