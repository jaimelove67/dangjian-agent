import test from "node:test";
import assert from "node:assert/strict";
import {
  meetingIsFuture,
  missingMinuteLabels,
  transcriptSectionStatus,
} from "../src/meeting-minutes.js";

test("三会一课纪要只识别明确标签行", () => {
  const status = transcriptSectionStatus(
    "学习要点：学习原文。\n讨论共识:形成共识。\n工作要求待明确。",
    "party_lecture",
  );
  assert.deepEqual(
    status.map((item) => [item.label, item.found]),
    [
      ["学习要点", true],
      ["讨论共识", true],
      ["工作要求", false],
    ],
  );
  assert.deepEqual(
    missingMinuteLabels(
      "学习重点：学习。\n会议共识：共识。\n落实要求：落实。",
      "branch_member_meeting",
    ),
    [],
  );
});

test("组织生活会使用查摆问题、批评意见和整改方向", () => {
  assert.deepEqual(
    missingMinuteLabels(
      "学习要点：不适用于组织生活会。\n查摆问题：问题。\n整改方向：方向。",
      "organizational_life_meeting",
    ),
    ["批评意见"],
  );
});

test("未来日期按本地日期判断", () => {
  const today = new Date(2026, 10, 5);
  assert.equal(meetingIsFuture("2026-11-06", today), true);
  assert.equal(meetingIsFuture("2026-11-05", today), false);
  assert.equal(meetingIsFuture("2026-11-04", today), false);
  assert.equal(meetingIsFuture("", today), false);
});
