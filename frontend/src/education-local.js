import { courses, DEPARTMENTS } from "./data.js";
import { accountOrganizations } from "./roles.js";

export const EDUCATION_MANAGERS = new Set(["school_admin", "department_admin", "branch_secretary", "organizer"]);
const learners = new Set([...EDUCATION_MANAGERS, "member", "applicant"]);
const copy = value => structuredClone(value);
const fail = (message, status = 409) => { throw Object.assign(new Error(message), { status }); };

function parents(id, tenant) {
  if (!id) return [];
  if (id === tenant) return [tenant];
  const org = accountOrganizations().find(o => o.id === id);
  if (!org || tenant !== "school-1") return [id, tenant];
  return org.org_type === "branch" ? [id, `dept-${DEPARTMENTS.indexOf(org.department)}`, tenant] : [id, tenant];
}
export function canManageEducation(user, record) {
  if (!user || !EDUCATION_MANAGERS.has(user.role) || record.tenant_id !== user.tenant_id) return false;
  if (record.tenant_id === "school-1" && !accountOrganizations().some(org => org.id === record.org_unit_id)) return false;
  return user.role === "school_admin" || parents(record.org_unit_id, record.tenant_id).includes(user.org_unit_id);
}
export function canReadEducation(user, record) {
  return !!user && learners.has(user.role) && record.tenant_id === user.tenant_id &&
    (canManageEducation(user, record) || (record.status === "published" && parents(user.org_unit_id, user.tenant_id).includes(record.org_unit_id)));
}

export function seedEducation() {
  const questions = [
    { id: "Q1", text: "本次学习准备应先查阅哪项内容？", options: ["组织发布的学习安排与有效原文", "未经核对的转述"], correct_index: 0, explanation: "学习准备应以组织发布的学习安排与现行有效原文为起点，未经核对的转述不能替代原文。" },
    { id: "Q2", text: "学习材料中的要求存在疑问时，应如何处理？", options: ["自行补写未找到的条款", "核对原文并向所属组织确认"], correct_index: 1, explanation: "对不明确的要求，应核对原文并向所属组织确认，不能自行补写没有依据的条款。" },
  ];
  return {
    revision: 1, enrollments: [],
    offerings: courses.map((course, index) => ({
      id: `local-course-${course.id}`, tenant_id: "school-1", org_unit_id: "school-1", kind: "course", title: course.title,
      status: "published", revision: 1, created_by: "demo-school", created_at: `2026-10-${24 - index}T09:00:00+08:00`,
      content: { description: course.content, reading_text: "学习准备：先查阅组织发布的学习安排和现行有效原文，再整理本次学习重点。对不明确的要求，核对原文并向所属组织确认。阅读后记录个人体会，按课程要求完成测评。", cover: course.cover, category: course.category, video_url: null, duration_seconds: 0, questions: copy(questions), passing_score: 60, max_attempts: 3, points: 2 },
    })).concat([{ id: "local-event-1", tenant_id: "school-1", org_unit_id: "school-1", kind: "event", title: "专题学习与交流活动", status: "published", revision: 1, created_by: "demo-school", created_at: "2026-10-25T09:00:00+08:00", content: { description: "围绕组织发布的学习材料交流学习体会，具体安排以发布组织通知为准。", starts_at: "2026-11-05T14:30:00+08:00", registration_deadline: "2026-11-04T17:00:00+08:00", location: "党员活动室", capacity: 100, points: 2 } }]),
  };
}
export const educationState = data => data.education || seedEducation();
const ownEnrollment = (state, user, id) => state.enrollments.find(e => e.tenant_id === user.tenant_id && e.user_id === user.id && e.offering_id === id);
function progressView(enrollment, record) {
  if (!enrollment) return null;
  const { last_tick, watched_segments, ...publicProgress } = enrollment.progress;
  const result = { id: enrollment.id, status: enrollment.status, points: enrollment.points, ...publicProgress };
  if (record && result.attempts && !result.exam_review) result.exam_review = examReview(record.content.questions || []);
  return result;
}
export const educationNotes = progress => ({ reading: progress?.note || "", ...progress?.material_notes });
export const hasEducationNotes = progress => Object.values(educationNotes(progress)).some(note => String(note).trim());
const examReview = (questions, answers = {}) => questions.map(question => ({
  id: question.id, text: question.text, options: copy(question.options),
  selected_index: answers[question.id] ?? null, correct_index: question.correct_index,
  correct: answers[question.id] == null ? null : answers[question.id] === question.correct_index,
  explanation: question.explanation || "",
}));
function view(state, user, record) {
  const result = copy(record), manage = canManageEducation(user, record);
  result.can_manage = manage;
  result.own = progressView(ownEnrollment(state, user, record.id), record);
  if (!manage && result.content.questions) result.content.questions = result.content.questions.map(({ id, text, options }) => ({ id, text, options }));
  if (record.kind === "event") result.enrolled_count = state.enrollments.filter(e => e.tenant_id === record.tenant_id && e.offering_id === record.id && e.status !== "cancelled").length;
  return result;
}
function offering(state, user, id, manage = false) {
  const record = state.offerings.find(r => r.id === id && r.tenant_id === user.tenant_id);
  if (!record || !canReadEducation(user, record)) fail("课程或活动不存在或不在当前组织范围。", 404);
  if (manage && !canManageEducation(user, record)) fail("无权维护该组织的课程或活动。", 403);
  return record;
}
function checkUser(user) { if (!user || !learners.has(user.role)) fail("当前身份不提供学校学习业务。", 403); }

export function readLocalEducation(data, user, path, query = {}) {
  checkUser(user);
  const state = educationState(data);
  if (path === "/member/org-units") return accountOrganizations().filter(org => canManageEducation(user, { tenant_id: "school-1", org_unit_id: org.id })).concat(user.tenant_id !== "school-1" && user.role === "school_admin" ? [{ id: user.tenant_id, name: "本校", org_type: "school" }] : []);
  if (path === "/education/offerings") return { items: state.offerings.filter(r => r.kind === (query.kind || "course") && canReadEducation(user, r)).map(r => view(state, user, r)) };
  if (path === "/education/credits") {
    const items = state.enrollments.filter(e => e.tenant_id === user.tenant_id && e.user_id === user.id && e.status === "completed").map(e => ({ id: e.id, offering_id: e.offering_id, title: state.offerings.find(r => r.id === e.offering_id && r.tenant_id === user.tenant_id)?.title || "学习记录", points: e.points, completed_at: e.progress.completed_at || e.progress.attended_at }));
    return { total_points: items.reduce((sum, e) => sum + e.points, 0), items };
  }
  const match = /^\/education\/offerings\/([^/]+)(?:\/(enrollments))?$/.exec(path);
  if (!match) fail("学习业务地址不存在。", 404);
  const record = offering(state, user, decodeURIComponent(match[1]), !!match[2]);
  if (!match[2]) return view(state, user, record);
  return { items: state.enrollments.filter(e => e.tenant_id === user.tenant_id && e.offering_id === record.id).map(e => ({ id: e.id, user_id: e.user_id, name: (data.accounts || []).find(a => a.id === e.user_id && a.tenant_id === user.tenant_id)?.name || "组织学员", status: e.status, points: e.points, score: e.progress.score, attempts: e.progress.attempts || 0, watched_seconds: e.progress.watched_seconds || 0 })) };
}

function validateContent(kind, body, user) {
  if (!canManageEducation(user, { tenant_id: user.tenant_id, org_unit_id: body.org_unit_id })) fail("请选择有权维护的组织。", 403);
  const title = String(body.title || "").trim(), description = String(body.description || "").trim();
  if (!title || title.length > 200 || !description || description.length > 5000) fail("请填写有效的标题和学习要求。", 422);
  if (!Number.isInteger(body.points) || body.points < 0 || body.points > 1000) fail("完成积分须为0至1000的整数。", 422);
  if (kind === "event") {
    if (!Number.isInteger(body.capacity) || body.capacity < 1 || body.capacity > 10000 || !Number.isFinite(Date.parse(body.starts_at)) || !Number.isFinite(Date.parse(body.registration_deadline)) || Date.parse(body.registration_deadline) > Date.parse(body.starts_at)) fail("请核对活动时间、报名截止和人数上限。", 422);
  } else {
    const questions = body.questions || [];
    if (!body.video_url && !questions.length) fail("课程至少包含视频或考试。", 422);
    if (body.video_url) {
      let url; try { url = new URL(body.video_url); } catch { fail("请填写有效的视频地址。", 422); }
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || !Number.isInteger(body.duration_seconds) || body.duration_seconds < 1 || body.duration_seconds > 86400) fail("请核对视频地址及真实时长。", 422);
    }
    if (!Number.isInteger(body.passing_score) || body.passing_score < 1 || body.passing_score > 100 || !Number.isInteger(body.max_attempts) || body.max_attempts < 1 || body.max_attempts > 10) fail("请核对合格分数与考试次数。", 422);
    if (questions.length > 100 || new Set(questions.map(q => q.id)).size !== questions.length || questions.some(q => !/^[A-Za-z0-9_-]{1,30}$/.test(q.id) || !q.text?.trim() || q.text.length > 2000 || !Array.isArray(q.options) || q.options.length < 2 || q.options.length > 8 || q.options.some(o => !o?.trim() || o.length > 1000) || !Number.isInteger(q.correct_index) || q.correct_index < 0 || q.correct_index >= q.options.length)) fail("请核对题目、选项和标准答案。", 422);
    if (questions.some(q => q.explanation != null && (typeof q.explanation !== "string" || q.explanation.length > 5000))) fail("每道题目的解析须为5000字以内的文字。", 422);
  }
  return { ...copy(body), title, description };
}
export const videoRequirementMet = (record, progress) => !record.content.video_url || (progress?.watched_seconds || 0) >= record.content.duration_seconds * 0.9;
function complete(record, enrollment, at) {
  if (videoRequirementMet(record, enrollment.progress) && (!record.content.questions?.length || enrollment.progress.passed)) {
    enrollment.status = "completed"; enrollment.points = record.content.points;
    enrollment.progress.completed_at ||= at;
  }
}

export function mutateLocalEducation(data, user, path, body = {}, clock = new Date()) {
  checkUser(user);
  const state = copy(educationState(data)), at = clock.toISOString();
  let value, action = path.split("/").at(-1), resourceId;
  if (["/education/courses", "/education/events"].includes(path)) {
    const kind = path.endsWith("courses") ? "course" : "event", content = validateContent(kind, body, user);
    const record = { id: crypto.randomUUID(), tenant_id: user.tenant_id, org_unit_id: content.org_unit_id, kind, title: content.title, content, status: "draft", revision: 1, created_by: user.id, created_at: at };
    delete content.org_unit_id; delete content.title;
    state.offerings.unshift(record); resourceId = record.id; value = view(state, user, record); action = "保存学习内容草稿";
  } else {
    const match = /^\/education\/offerings\/([^/]+)\/(publish|enroll|cancel|heartbeat|exam|attendance|notes)$/.exec(path);
    if (!match) fail("学习业务操作不存在。", 404);
    const record = offering(state, user, decodeURIComponent(match[1]), ["publish", "attendance"].includes(match[2]));
    resourceId = record.id; action = match[2];
    let own = ownEnrollment(state, user, record.id);
    if (action === "publish") {
      if (record.status !== "draft" || body.expected_revision !== record.revision) fail("版本已变化或内容已经发布。");
      if (!String(body.reason || "").trim()) fail("请填写发布依据。", 422);
      if (record.kind === "event" && Date.parse(record.content.registration_deadline) <= clock.getTime()) fail("报名截止时间已过，请编制新的活动。", 422);
      record.status = "published"; record.revision++; value = view(state, user, record);
    } else {
      if (record.status !== "published") fail("课程或活动尚未发布。");
      if (action === "enroll") {
        if (!own || own.status === "cancelled") {
          if (record.kind === "event" && (Date.parse(record.content.registration_deadline) <= clock.getTime() || state.enrollments.filter(e => e.tenant_id === user.tenant_id && e.offering_id === record.id && e.status !== "cancelled").length >= record.content.capacity)) fail("报名已截止或名额已满。");
          if (own) own.status = "enrolled";
          else { own = { id: crypto.randomUUID(), tenant_id: user.tenant_id, user_id: user.id, offering_id: record.id, status: "enrolled", points: 0, progress: { attempts: 0, watched_seconds: 0, position_seconds: 0, last_tick: at } }; state.enrollments.push(own); }
        }
        value = view(state, user, record);
      } else if (action === "attendance") {
        if (record.kind !== "event" || Date.parse(record.content.starts_at) > clock.getTime()) fail("只能核验已开展活动的真实出席。");
        if (body.user_id === user.id) fail("本人出席须由其他组织人员核验。", 403);
        const target = state.enrollments.find(e => e.tenant_id === user.tenant_id && e.offering_id === record.id && e.user_id === body.user_id && e.status !== "cancelled");
        if (!target) fail("该账号没有有效报名记录。", 404);
        if (body.attended !== true || !String(body.reason || "").trim()) fail("请填写真实出席核验依据。", 422);
        target.status = "completed"; target.points = record.content.points; target.progress.attended_at ||= at; target.progress.attended_by = user.id;
        value = progressView(target);
      } else {
        if (!own || own.status === "cancelled") fail("请先开始课程或报名活动。");
        if (action === "cancel") {
          if (record.kind !== "event" || own.status === "completed" || Date.parse(record.content.registration_deadline) <= clock.getTime()) fail("当前活动不能取消报名。");
          own.status = "cancelled"; value = view(state, user, record);
        } else if (action === "notes") {
          if (record.kind !== "course" || typeof body.note !== "string" || body.note.length > 5000) fail("请填写5000字以内的课程笔记。", 422);
          const material = body.material_id ?? "reading";
          if (!(material === "reading" && (record.content.reading_text || record.content.description)) && !(material === "lesson" && record.content.video_url)) fail("所选学习资料不存在，请重新进入课程。", 422);
          own.progress.material_notes = { ...educationNotes(own.progress), [material]: body.note };
          if (material === "reading") own.progress.note = body.note;
          value = progressView(own, record);
        } else if (record.kind !== "course") fail("该操作仅适用于课程。");
        else if (action === "exam") {
          const questions = record.content.questions || [], answers = body.answers || {};
          if (!questions.length || !videoRequirementMet(record, own.progress)) fail("请先完成视频学习，再参加考试。");
          if (own.status !== "completed") {
            if (own.progress.attempts >= record.content.max_attempts) fail("已达到本课程考试次数上限。");
            if (Object.keys(answers).length !== questions.length || questions.some(q => !Number.isInteger(answers[q.id]) || answers[q.id] < 0 || answers[q.id] >= q.options.length)) fail("请按当前试题逐题作答。", 422);
            const score = Math.floor(questions.filter(q => q.correct_index === answers[q.id]).length * 100 / questions.length);
            Object.assign(own.progress, { attempts: own.progress.attempts + 1, score, passed: score >= record.content.passing_score, exam_review: examReview(questions, answers) }); complete(record, own, at);
          }
          value = progressView(own, record);
        } else if (action === "heartbeat") {
          const position = body.position_seconds, elapsed = Math.max(0, (clock.getTime() - Date.parse(own.progress.last_tick)) / 1000), delta = position - own.progress.position_seconds;
          if (!record.content.video_url || !Number.isFinite(position) || position < 0 || position > record.content.duration_seconds + 2 || delta > Math.min(60, elapsed) * 1.25 + 2) fail("播放进度增长超过实际经过时间，请正常观看后重试。", 422);
          const segments = [...(own.progress.watched_segments || [])];
          if (delta > 0) { const end = Math.min(position, record.content.duration_seconds); segments.push([Math.max(0, end - Math.min(delta, elapsed, 60)), end]); }
          const merged = [];
          for (const [start, end] of segments.sort((a, b) => a[0] - b[0])) { const previous = merged.at(-1); if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end); else merged.push([start, end]); }
          Object.assign(own.progress, { watched_segments: merged, watched_seconds: Math.min(record.content.duration_seconds, merged.reduce((sum, [start, end]) => sum + end - start, 0)), position_seconds: position, last_tick: at });
          complete(record, own, at); value = progressView(own, record);
        }
      }
    }
  }
  state.revision++;
  return { state, value, resourceId, action };
}
