import test from "node:test";
import assert from "node:assert/strict";
import {
  organizationForest,
  organizationMemberCount,
  organizationMatches,
  organizationType,
} from "../src/organization-tree.js";

const school = { id: "school", name: "测试大学党委", org_type: "school", parent_id: null };
const department = { id: "dept", name: "计算机学院党委", org_type: "department", parent_id: "school" };
const branch = { id: "branch", name: "本科生第一党支部", org_type: "branch", parent_id: "dept" };

test("real parent IDs reconstruct the authorized school, department and branch irrespective of response order", () => {
  const forest = organizationForest([branch, school, department]);
  assert.equal(forest.length, 1);
  assert.equal(forest[0].id, "school");
  assert.equal(forest[0].children[0].id, "dept");
  assert.equal(forest[0].children[0].children[0].id, "branch");
  assert.equal(branch.children, undefined);
});

test("restricted scopes never create an unavailable school or department", () => {
  assert.deepEqual(organizationForest([branch]), [{ ...branch, children: [] }]);
  const forest = organizationForest([department, branch]);
  assert.equal(forest[0].id, "dept");
  assert.equal(forest[0].children[0].id, "branch");
  assert.equal(forest.length, 1);
  assert.equal(organizationForest([{ ...school, parent_id: null }, { ...branch, parent_id: null }]).length, 2);
});

test("branch searches retain actual ancestors and parent searches retain their descendants", () => {
  const organizations = [school, department, branch];
  assert.equal(organizationForest(organizations, " 第一党支部 ")[0].children[0].children[0].id, "branch");
  assert.equal(organizationForest(organizations, "学院")[0].children[0].children[0].id, "branch");
  assert.equal(organizationForest(organizations, "branch")[0].children[0].children[0].id, "branch");
  assert.deepEqual(organizationForest(organizations, "不存在"), []);
});

test("organization search and detail counts accept ids and remote aggregates", () => {
  assert.equal(organizationMatches(branch, "branch"), true);
  assert.equal(organizationMatches(branch, "本科生"), true);
  assert.equal(organizationMatches(branch, "不存在"), false);
  assert.equal(organizationMemberCount({ id: "branch", member_count: 7 }, []), 7);
  assert.equal(
    organizationMemberCount(
      { id: "branch" },
      [{ orgId: "branch" }, { orgId: "other" }],
    ),
    1,
  );
  assert.equal(organizationMemberCount({ id: "branch" }, [], false), null);
  assert.equal(organizationMemberCount({}, []), null);
});

test("malformed self and cyclic parent links terminate without dropping visible organizations", () => {
  const records = [
    { id: "a", name: "A", parent_id: "b" },
    { id: "b", name: "B", parent_id: "a" },
    { id: "c", name: "C", parent_id: "a" },
    { id: "d", name: "D", parent_id: "d" },
  ];
  assert.deepEqual(organizationForest(records).map((node) => node.id), ["a", "b", "c", "d"]);
  assert.equal(organizationForest(records, "C").length, 1);
  assert.deepEqual(organizationForest([]), []);
});

test("organization types are displayed in Chinese without inventing an unknown type", () => {
  assert.deepEqual([school, department, branch].map(organizationType), ["学校党委", "二级党组织", "党支部"]);
  assert.equal(organizationType({}), "未登记");
});
