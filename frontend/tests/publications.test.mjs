import { test } from "node:test";
import assert from "node:assert/strict";
import { demoSession } from "../src/roles.js";
import { buildInitialData } from "../src/data.js";
import { canDownloadDemoPublicationFile, canReadDemoPublication, demoPublications, documentIsPublished, filterPublications, normalizeNotice, noticeIsPublished, publicationFileOwner, publicationToday, seedPublications, validatePublicationDraft } from "../src/publications.js";

const day = "2026-10-28";
const publication = (extra = {}) => ({ id: "p", kind: "notice", status: "published", tenant_id: "school-1", org_unit_id: "school-1", title: "校内公示", body: { category: "publicity", starts_on: "2026-10-26", expires_on: "2026-10-30" }, ...extra });

test("publications use Shanghai dates at the UTC boundary", () => {
  assert.equal(publicationToday(new Date("2026-10-27T17:00:00Z")), "2026-10-28");
});
test("home excludes drafts, expired and future notices, keeping both boundary days", () => {
  assert.equal(noticeIsPublished(publication(), day), true);
  assert.equal(noticeIsPublished(publication(), "2026-10-26"), true);
  assert.equal(noticeIsPublished(publication(), "2026-10-30"), true);
  for (const bad of [publication({ status: "draft" }), publication({ kind: "task" }), publication({ body: { category: "publicity" } }), publication({ body: { starts_on: "2026-10-30" } }), publication({ body: { expires_on: "2026-10-27" } })]) assert.equal(noticeIsPublished(bad, day), false);
  assert.equal(noticeIsPublished(publication({ body: { content: "已有普通通知" } }), day), true);
});
test("organization publication scope includes ancestors, rejects sibling and other tenant", () => {
  const student = demoSession("student").user;
  assert.equal(canReadDemoPublication(student, publication()), true);
  assert.equal(canReadDemoPublication(student, publication({ org_unit_id: "dept-10" })), true);
  assert.equal(canReadDemoPublication(student, publication({ org_unit_id: student.org_unit_id })), true);
  assert.equal(canReadDemoPublication(student, publication({ org_unit_id: "org-10-2" })), false);
  assert.equal(canReadDemoPublication(student, publication({ org_unit_id: "dept-0" })), false);
  assert.equal(canReadDemoPublication(student, publication({ tenant_id: "school-2" })), false);
  assert.equal(canReadDemoPublication(student, publication({ tenant_id: undefined })), false);
  assert.equal(canReadDemoPublication(demoSession("platform").user, publication()), false);
  assert.equal(canReadDemoPublication({ ...student, role: "unknown" }, publication()), false);
});
test("department managers see publications in their own descendants only", () => {
  const user = demoSession("department").user;
  assert.equal(canReadDemoPublication(user, publication({ org_unit_id: "org-10-3" })), true);
  assert.equal(canReadDemoPublication(user, publication({ org_unit_id: "org-0-1" })), false);
});
test("new school tenants never inherit built-in notices or documents", () => {
  const session = demoSession("student"); session.user.tenant_id = "school-2";
  assert.deepEqual(demoPublications(buildInitialData(), session, day), []);
  const scoped = { ...buildInitialData(), publications: [publication({ tenant_id: "school-2", org_unit_id: session.user.org_unit_id })] };
  assert.equal(demoPublications(scoped, session, day).length, 1);
});
test("pending local uploads and personal material do not enter public document feed", () => {
  const data = buildInitialData();
  data.knowledge = [...data.knowledge, { id: "new-doc", title: "未审核原件", status: "现行有效", tenant_id: "school-1", org_unit_id: "school-1" }];
  data.personalMaterials = [{ id: "private", title: "私人思想汇报" }];
  const items = demoPublications(data, demoSession("student"), day);
  assert.ok(items.some((item) => item.category === "publicity"));
  assert.ok(items.some((item) => item.category === "document"));
  assert.ok(!items.some((item) => item.title === "未审核原件" || item.title === "私人思想汇报"));
});
test("documents must be published and currently effective", () => {
  const document = { review_status: "published", status: "effective", effective_date: "2026-10-20" };
  assert.equal(documentIsPublished(document, day), true);
  for (const changed of [{ review_status: "pending" }, { status: "expired" }, { validity: "superseded" }, { effective_date: "2026-10-29" }, { expiration_date: "2026-10-27" }]) assert.equal(documentIsPublished({ ...document, ...changed }, day), false);
});
test("search and category filtering preserve public-notice priority", () => {
  const items = seedPublications().map(normalizeNotice);
  const only = filterPublications(items, { category: "publicity", query: "土木工程" });
  assert.equal(only.length, 1);
  assert.ok(only[0].title.includes("土木工程"));
  const pinned = filterPublications(items)[0];
  assert.equal(pinned.pinned, true);
});

test("draft validation requires complete public-notice dates and authorized audience", () => {
  const values = { title: " 公示标题 ", content: " 正文 ", category: "publicity", org_unit_id: "school-1", starts_on: "2026-10-26", expires_on: "2026-10-30" };
  assert.equal(validatePublicationDraft(values, ["school-1"]).title, "公示标题");
  for (const changed of [{ starts_on: "" }, { expires_on: "" }, { starts_on: "2026-11-01" }, { starts_on: "2026-02-31" }, { org_unit_id: "school-2" }, { content: " " }]) assert.throws(() => validatePublicationDraft({ ...values, ...changed }, ["school-1"]));
  assert.equal(validatePublicationDraft({ ...values, category: "notice", starts_on: "", expires_on: "" }, ["school-1"]).starts_on, null);
});

test("public-notice attachments require publication ownership, membership and audience", () => {
  const record = publication();
  const evidence = { local_file_id: "blob-1", local_owner_id: publicationFileOwner(record), has_file: true };
  record.body.evidence = [evidence];
  const student = demoSession("student").user;
  assert.equal(canDownloadDemoPublicationFile(student, record, evidence, day), true);
  assert.equal(canDownloadDemoPublicationFile(student, record, { ...evidence, local_owner_id: student.id }, day), false);
  assert.equal(canDownloadDemoPublicationFile(student, record, { ...evidence, local_file_id: "other-blob" }, day), false);
  assert.equal(canDownloadDemoPublicationFile(student, { ...record, status: "draft" }, evidence, day), false);
  assert.equal(canDownloadDemoPublicationFile(student, { ...record, tenant_id: "school-2" }, evidence, day), false);
  assert.equal(canDownloadDemoPublicationFile(student, record, evidence, "2026-10-31"), false);
});
