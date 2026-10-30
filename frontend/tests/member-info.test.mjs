import { test } from "node:test";
import assert from "node:assert/strict";

import { demoSession } from "../src/roles.js";
import { buildInitialData } from "../src/data.js";
import { roleSeed } from "../src/role-data.js";
import {
  canReviewInfo,
  emptyInfoPayload,
  infoCounts,
  infoStatusLabel,
  saveBranchInfo,
  saveSelfInfo,
  scopedInfoCollections,
  seedDemoInfoCollections,
  selfInfoCollection,
  submitSelfInfo,
  validateCompleteInfo,
  validateSelfInfo,
  reviewInfoCollection,
} from "../src/member-info.js";

const student = demoSession("student");
const teacher = demoSession("teacher");
const applicant = demoSession("applicant");
const secretary = demoSession("secretary");
const department = demoSession("department");
const school = demoSession("school");

function completeSelf(overrides = {}) {
  return {
    gender: "male",
    ethnicity: "汉族",
    education_code: "22",
    mobile: "13800001234",
    phone_area: "",
    phone_number: "",
    address: "示范大学学生公寓 1 栋 101",
    lost_contact: false,
    lost_contact_on: "",
    floating: false,
    floating_province: "",
    floating_city: "",
    floating_county: "",
    ...overrides,
  };
}

function branchFields(overrides = {}) {
  return {
    join_party_on: "2021-06-01",
    full_member_on: "2022-06-01",
    job_code: "321",
    party_status: "normal",
    filing_type: "new",
    supplement_reason: "",
    relation_transfer: false,
    transfer_branch: "",
    ...overrides,
  };
}

function freshData() {
  const data = { ...buildInitialData(), ...roleSeed() };
  data.memberInfoCollections = [];
  return data;
}

test("member info validation separates personal and branch fields", () => {
  const errors = validateSelfInfo(
    completeSelf({ mobile: "123", address: "", floating: true }),
  );
  assert.match(errors.mobile, /手机号/);
  assert.match(errors.address, /家庭住址/);
  assert.match(errors.floating_province, /省份/);
  assert.equal(validateSelfInfo(completeSelf()).mobile, undefined);

  const complete = validateCompleteInfo(
    { ...completeSelf(), ...branchFields({ full_member_on: "" }) },
    { stage: "member", birth_date: "2000-01-01" },
  );
  assert.match(complete.full_member_on, /正式党员/);

  const supplement = validateCompleteInfo(
    {
      ...completeSelf(),
      ...branchFields({
        filing_type: "supplement",
        supplement_reason: "",
        relation_transfer: true,
        transfer_branch: "",
      }),
    },
    { stage: "member", birth_date: "2000-01-01" },
  );
  assert.match(supplement.supplement_reason, /补录原因/);
  assert.match(supplement.transfer_branch, /支部全称/);
});

test("member submission creates a version and branch/department/school complete the workflow", () => {
  let data = freshData();
  const saved = saveSelfInfo(data, student, completeSelf());
  data.memberInfoCollections = saved.collections;
  assert.equal(selfInfoCollection(data, student).status, "draft");

  const submitted = submitSelfInfo(data, student, {}, true);
  data.memberInfoCollections = submitted.collections;
  const collection = selfInfoCollection(data, student);
  assert.equal(collection.status, "submitted");
  assert.equal(collection.version, 1);
  assert.equal(collection.history.at(-1).action, "submit");

  const branchSaved = saveBranchInfo(
    data,
    secretary,
    collection.id,
    branchFields(),
  );
  data.memberInfoCollections = branchSaved;
  assert.equal(selfInfoCollection(data, student).status, "submitted");

  const branchReviewed = reviewInfoCollection(
    data,
    secretary,
    collection.id,
    "approve",
    "信息核对无误",
  );
  data.memberInfoCollections = branchReviewed;
  assert.equal(selfInfoCollection(data, student).status, "branch_approved");

  const departmentReviewed = reviewInfoCollection(
    data,
    department,
    collection.id,
    "approve",
    "复核通过",
  );
  data.memberInfoCollections = departmentReviewed;
  assert.equal(
    selfInfoCollection(data, student).status,
    "department_approved",
  );

  const archived = reviewInfoCollection(
    data,
    school,
    collection.id,
    "archive",
    "同意备案",
  );
  data.memberInfoCollections = archived;
  assert.equal(selfInfoCollection(data, student).status, "archived");
  assert.equal(
    infoStatusLabel(selfInfoCollection(data, student).status),
    "已备案",
  );
  assert.equal(
    canReviewInfo(secretary, selfInfoCollection(data, student)),
    false,
  );
});

test("returned collection can be corrected and resubmitted with a new version", () => {
  const data = { ...buildInitialData(), ...roleSeed() };
  const returned = selfInfoCollection(data, teacher);
  assert.equal(returned.status, "returned");
  assert.match(returned.return_reason, /门牌号/);

  const saved = saveSelfInfo(
    data,
    teacher,
    completeSelf({ address: "示范大学教师公寓 2 栋 302" }),
  );
  data.memberInfoCollections = saved.collections;
  assert.equal(selfInfoCollection(data, teacher).status, "returned");

  const submitted = submitSelfInfo(data, teacher, {}, true);
  data.memberInfoCollections = submitted.collections;
  const current = selfInfoCollection(data, teacher);
  assert.equal(current.status, "submitted");
  assert.equal(current.version, 2);
  assert.equal(current.history.at(-1).version, 2);
});

test("applicants cannot start the party-member collection and demo seeds stay scoped", () => {
  const data = freshData();
  assert.throws(
    () => saveSelfInfo(data, applicant, completeSelf()),
    /党员本人/,
  );

  const seeds = seedDemoInfoCollections();
  const counts = infoCounts(seeds);
  assert.equal(counts.submitted, 1);
  assert.equal(counts.returned, 1);
  assert.equal(counts.department_approved, 1);
  assert.equal(counts.archived, 1);
  assert.ok(
    scopedInfoCollections(
      { memberInfoCollections: seeds },
      secretary,
    ).every((item) => item.org_unit_id === secretary.user.org_unit_id),
  );
  // 新填报的党籍状态留空，必须由本人或支部明确选择，不预置结论。
  assert.equal(emptyInfoPayload().party_status, "");
  assert.match(
    validateCompleteInfo(emptyInfoPayload(), { stage: "正式党员" }).party_status,
    /党籍状态/,
  );
  // 演示种子数据本身是完整记录，党籍状态已明确填写。
  assert.ok(seeds.every((item) => item.payload.party_status === "normal"));
});
