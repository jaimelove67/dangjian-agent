import test from "node:test";
import assert from "node:assert/strict";
import {
  isAutoRosterType,
  mergeParticipantRows,
  participantSummary,
  rosterMembersForImport,
  validateParticipantRows,
} from "../src/meeting-participants.js";

const roster = [
  { participant_id: "m1", name: "张山", stage: "member", org_name: "第一支部" },
  {
    participant_id: "m2",
    name: "李水",
    stage: "probationary",
    org_name: "第一支部",
  },
  { participant_id: "m3", name: "王申", stage: "applicant", org_name: "第一支部" },
];

test("支部大会只自动带入正式党员和预备党员，党课可使用完整名册", () => {
  assert.equal(isAutoRosterType("branch_member_meeting"), true);
  assert.deepEqual(
    rosterMembersForImport(roster, "branch_member_meeting").map(
      (member) => member.participant_id,
    ),
    ["m1", "m2"],
  );
  assert.deepEqual(
    rosterMembersForImport(roster, "party_lecture").map(
      (member) => member.participant_id,
    ),
    ["m1", "m2", "m3"],
  );
  assert.deepEqual(rosterMembersForImport(roster, "branch_committee_meeting"), []);
});

test("带入名册不覆盖已登记人员，重复编号不会重复添加", () => {
  const existing = [
    { participant_id: "m1", name: "张山", attended: true },
  ];
  const merged = mergeParticipantRows(existing, [
    { participant_id: "m1", name: "张山", stage: "member" },
    { participant_id: "m4", name: "赵石", stage: "member" },
  ]);
  assert.deepEqual(
    merged.map((row) => [row.participant_id, row.attended]),
    [
      ["m1", true],
      ["m4", null],
    ],
  );
});

test("参会统计区分出席、缺席和待确认", () => {
  assert.deepEqual(
    participantSummary([
      { attended: true },
      { attended: true },
      { attended: false },
      { attended: null },
    ]),
    { total: 4, attended: 2, absent: 1, pending: 1 },
  );
});

test("保存前必须补齐出勤并拒绝重复人员编号", () => {
  assert.throws(
    () => validateParticipantRows([{ participant_id: "m1", name: "张山" }]),
    /未确认出勤/,
  );
  assert.deepEqual(
    validateParticipantRows([
      { participant_id: "m1", name: "张山", attended: true },
      { participant_id: "m2", name: "李水", attended: false },
    ]),
    [
      { participant_id: "m1", name: "张山", attended: true },
      { participant_id: "m2", name: "李水", attended: false },
    ],
  );
  assert.throws(
    () =>
      validateParticipantRows([
        { participant_id: "m1", name: "张山", attended: true },
        { participant_id: "m1", name: "李水", attended: false },
      ]),
    /不能重复/,
  );
});
