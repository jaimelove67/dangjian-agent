import { test } from "node:test";
import assert from "node:assert/strict";
import { demoSession, canAccess, SELF_ROUTES } from "../src/roles.js";
import { courses } from "../src/data.js";
import { educationState, readLocalEducation, mutateLocalEducation, canManageEducation, canReadEducation, hasEducationNotes } from "../src/education-local.js";

const user = id => demoSession(id).user;
const clock = new Date("2026-10-29T02:00:00Z");
const start = (data, actor = user("student"), id = "local-course-1") => mutateLocalEducation(data, actor, `/education/offerings/${id}/enroll`, {}, clock);
const act = (state, actor, id, action, body = {}, at = clock) => mutateLocalEducation({ education: state }, actor, `/education/offerings/${id}/${action}`, body, at);

test("personal learning is reachable without granting platform or school management routes", () => {
  assert.ok(SELF_ROUTES.has("learning"));
  for (const id of ["teacher", "student", "applicant"]) {
    assert.equal(canAccess(demoSession(id), { id: "learning" }), true);
    assert.equal(canAccess(demoSession(id), { id: "school-learning" }), false);
  }
  assert.equal(canAccess(demoSession("platform"), { id: "learning" }), false);
  assert.throws(() => readLocalEducation({}, user("platform"), "/education/offerings"), /不提供/);
});

test("courses follow tenant, parent organization and published status", () => {
  const state = educationState({}), student = user("student");
  assert.equal(readLocalEducation({}, student, "/education/offerings").items.length, courses.length);
  assert.equal(canReadEducation(student, { ...state.offerings[0], tenant_id: "other-school" }), false);
  assert.equal(canReadEducation(student, { ...state.offerings[0], org_unit_id: "dept-0" }), false);
  assert.equal(canReadEducation(student, { ...state.offerings[0], status: "draft" }), false);
  assert.equal(canReadEducation(student, { ...state.offerings[0], org_unit_id: student.org_unit_id }), true);
  assert.deepEqual(readLocalEducation({}, { ...student, tenant_id: "new-school" }, "/education/offerings").items, []);
  assert.equal(canManageEducation(user("department"), { ...state.offerings[0], org_unit_id: "org-0-1" }), false);
});

test("learner views hide answer keys and other accounts' learning records", () => {
  const student = user("student"), teacher = user("teacher"), { state } = start({});
  const course = readLocalEducation({ education: state }, student, "/education/offerings/local-course-1");
  assert.ok(course.content.questions.every(q => q.correct_index === undefined));
  assert.equal(readLocalEducation({ education: state }, teacher, "/education/offerings/local-course-1").own, null);
  assert.throws(() => readLocalEducation({ education: state }, student, "/education/offerings/local-course-1/enrollments"), /无权/);
  assert.equal(readLocalEducation({ education: state }, user("school"), "/education/offerings/local-course-1/enrollments").items.length, 1);
});

test("exam grading checks answers, attempt limits and awards credits only once", () => {
  const actor = user("student"), id = "local-course-1";
  assert.throws(() => act(educationState({}), actor, id, "exam", { answers: { Q1: 0, Q2: 1 } }), /先开始/);
  let { state } = start({});
  assert.throws(() => act(state, actor, id, "exam", { answers: { Q1: 0 } }), /逐题/);
  let result = act(state, actor, id, "exam", { answers: { Q1: 1, Q2: 0 } });
  assert.equal(result.value.attempts, 1); assert.equal(result.value.points, 0);
  result = act(result.state, actor, id, "exam", { answers: { Q1: 0, Q2: 1 }, points: 999 });
  assert.equal(result.value.score, 100); assert.equal(result.value.points, 2); assert.equal(result.value.status, "completed");
  const repeated = act(result.state, actor, id, "exam", { answers: { Q1: 0, Q2: 1 } });
  assert.deepEqual(repeated.value, result.value);
  assert.equal(readLocalEducation({ education: repeated.state }, actor, "/education/credits").total_points, 2);
  assert.equal(readLocalEducation({ education: repeated.state }, user("teacher"), "/education/credits").total_points, 0);
});

test("submitted exams retain own answers and explanations without exposing them before submission", () => {
  const actor = user("student"), id = "local-course-1", base = structuredClone(educationState({}));
  base.offerings[0].content.questions[0].explanation = "应先核对组织发布的学习安排与有效原文。";
  let { state } = start({ education: base });
  const before = readLocalEducation({ education: state }, actor, `/education/offerings/${id}`);
  assert.equal(before.content.questions[0].explanation, undefined);
  assert.equal(before.own.exam_review, undefined);
  const failed = act(state, actor, id, "exam", { answers: { Q1: 1, Q2: 1 } });
  assert.equal(failed.value.exam_review[0].selected_index, 1);
  assert.equal(failed.value.exam_review[0].correct_index, 0);
  assert.equal(failed.value.exam_review[0].correct, false);
  assert.equal(failed.value.exam_review[0].explanation, base.offerings[0].content.questions[0].explanation);
  state = failed.state;
  const reopened = readLocalEducation({ education: state }, actor, `/education/offerings/${id}`);
  assert.deepEqual(reopened.own.exam_review, failed.value.exam_review);
  assert.equal(readLocalEducation({ education: state }, user("teacher"), `/education/offerings/${id}`).own, null);
  const passed = act(state, actor, id, "exam", { answers: { Q1: 0, Q2: 1 } });
  assert.equal(passed.value.exam_review[0].selected_index, 0);
  assert.equal(passed.value.exam_review[0].correct, true);
});

test("unsuccessful attempts stop at the configured maximum", () => {
  const actor = user("student"), id = "local-course-1";
  let { state } = start({});
  for (let i = 0; i < 3; i++) state = act(state, actor, id, "exam", { answers: { Q1: 1, Q2: 0 } }).state;
  assert.throws(() => act(state, actor, id, "exam", { answers: { Q1: 0, Q2: 1 } }), /次数上限/);
  assert.equal(readLocalEducation({ education: state }, actor, "/education/credits").total_points, 0);
});

test("historical scores expose only known answers and retain review when saving notes", () => {
  const actor = user("student"), id = "local-course-1";
  const completed = act(start({}).state, actor, id, "exam", { answers: { Q1: 0, Q2: 1 } });
  delete completed.state.enrollments[0].progress.exam_review;
  const historical = readLocalEducation({ education: completed.state }, actor, `/education/offerings/${id}`).own;
  assert.ok(historical.exam_review.every(question => question.selected_index === null && question.correct === null));
  assert.equal(historical.exam_review[0].correct_index, 0);
  assert.deepEqual(act(completed.state, actor, id, "notes", { note: "追加笔记" }).value.exam_review, historical.exam_review);
});

test("notes are owned by the current account and never mark a course complete", () => {
  const actor = user("student"), id = "local-course-1";
  const { state } = start({}), written = act(state, actor, id, "notes", { note: "我的学习体会" });
  assert.equal(written.value.note, "我的学习体会"); assert.equal(written.value.points, 0); assert.equal(written.value.status, "enrolled");
  assert.equal(readLocalEducation({ education: written.state }, user("teacher"), `/education/offerings/${id}`).own, null);
  assert.throws(() => act(written.state, actor, id, "notes", { note: "长".repeat(5001) }), /5000/);
  assert.equal(act(written.state, actor, id, "notes", { note: "" }).value.note, "");
});

test("chapter notes preserve each material, support clearing and stay private", () => {
  const actor = user("student"), id = "local-course-1", base = structuredClone(educationState({}));
  Object.assign(base.offerings[0].content, { video_url: "http://127.0.0.1/lesson.mp4", duration_seconds: 20 });
  let { state } = start({ education: base });
  let saved = act(state, actor, id, "notes", { material_id: "reading", note: "导读笔记" });
  saved = act(saved.state, actor, id, "notes", { material_id: "lesson", note: "视频笔记" });
  assert.equal(saved.value.material_notes.reading, "导读笔记");
  assert.equal(saved.value.material_notes.lesson, "视频笔记");
  assert.equal(saved.value.note, "导读笔记");
  assert.equal(saved.value.status, "enrolled");
  assert.equal(saved.value.points, 0);
  assert.equal(hasEducationNotes(saved.value), true);
  assert.throws(() => act(saved.state, actor, id, "notes", { material_id: "missing", note: "无效资料" }), /资料/);
  saved = act(saved.state, actor, id, "notes", { material_id: "reading", note: "" });
  assert.equal(saved.value.material_notes.reading, "");
  assert.equal(saved.value.material_notes.lesson, "视频笔记");
  assert.equal(hasEducationNotes(saved.value), true);
  assert.equal(hasEducationNotes(act(saved.state, actor, id, "notes", { material_id: "lesson", note: "" }).value), false);
  assert.equal(readLocalEducation({ education: saved.state }, user("teacher"), `/education/offerings/${id}`).own, null);
});

test("video completion requires elapsed time and distinct watched coverage", () => {
  const actor = user("student"), state = structuredClone(educationState({})), id = "local-course-1";
  Object.assign(state.offerings[0].content, { video_url: "http://127.0.0.1/lesson.mp4", duration_seconds: 20, questions: [] });
  let result = start({ education: state });
  assert.throws(() => act(result.state, actor, id, "heartbeat", { position_seconds: 20 }), /超过/);
  result = act(result.state, actor, id, "heartbeat", { position_seconds: 10 }, new Date(clock.getTime() + 10000));
  assert.equal(result.value.watched_seconds, 10); assert.equal(result.value.points, 0);
  result = act(result.state, actor, id, "heartbeat", { position_seconds: 0 }, new Date(clock.getTime() + 10000));
  result = act(result.state, actor, id, "heartbeat", { position_seconds: 10 }, new Date(clock.getTime() + 20000));
  assert.equal(result.value.watched_seconds, 10);
  result = act(result.state, actor, id, "heartbeat", { position_seconds: 20 }, new Date(clock.getTime() + 30000));
  assert.equal(result.value.status, "completed"); assert.equal(result.value.points, 2);
});

test("activity seats, cancellation and attendance require distinct authorized actions", () => {
  const student = user("student"), teacher = user("teacher"), id = "local-event-1", base = structuredClone(educationState({}));
  base.offerings.find(row => row.id === id).content.capacity = 1;
  let result = act(base, student, id, "enroll");
  assert.equal(act(result.state, student, id, "enroll").value.own.id, result.value.own.id);
  assert.throws(() => act(result.state, teacher, id, "enroll"), /名额/);
  result = act(result.state, student, id, "cancel"); result = act(result.state, teacher, id, "enroll");
  assert.throws(() => act(result.state, user("school"), id, "attendance", { user_id: teacher.id, attended: true, reason: "核验" }), /已开展/);
  assert.throws(() => act(result.state, student, id, "attendance", { user_id: teacher.id, attended: true, reason: "越权" }), /无权/);
  result = act(result.state, user("school"), id, "attendance", { user_id: teacher.id, attended: true, reason: "现场名单核对" }, new Date("2026-11-06T00:00:00Z"));
  assert.equal(result.value.points, 2);
  assert.equal(readLocalEducation({ education: result.state }, teacher, "/education/credits").total_points, 2);
});

test("only authorized managers compile and explicitly publish courses", () => {
  const body = { org_unit_id: user("student").org_unit_id, title: "新课程", description: "已确认的学习要求", points: 1, video_url: null, duration_seconds: 0, passing_score: 60, max_attempts: 2, questions: [{ id: "Q1", text: "阅读题", options: ["一", "二"], correct_index: 0 }] };
  assert.throws(() => mutateLocalEducation({}, user("student"), "/education/courses", body, clock), /有权/);
  let result = mutateLocalEducation({}, user("secretary"), "/education/courses", body, clock);
  const id = result.value.id;
  assert.equal(readLocalEducation({ education: result.state }, user("student"), "/education/offerings").items.some(row => row.id === id), false);
  assert.throws(() => act(result.state, user("secretary"), id, "publish", { expected_revision: 2, reason: "发布" }), /版本/);
  result = act(result.state, user("secretary"), id, "publish", { expected_revision: 1, reason: "核对学习内容后发布" });
  assert.equal(readLocalEducation({ education: result.state }, user("student"), `/education/offerings/${id}`).status, "published");
});
