import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const origin = process.env.EDUCATION_TEST_ORIGIN || "http://127.0.0.1:4173";
const debugOrigin = process.env.EDUCATION_TEST_CDP || "http://127.0.0.1:9222";
const version = await (await fetch(`${debugOrigin}/json/version`)).json();
const socket = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let nextId = 0;
const pending = new Map(), exceptions = [];
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const task = pending.get(message.id);
    pending.delete(message.id);
    message.error ? task.reject(new Error(JSON.stringify(message.error))) : task.resolve(message.result);
  } else if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
});
function cdp(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
    pending.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}
const { browserContextId } = await cdp("Target.createBrowserContext");
const { targetId } = await cdp("Target.createTarget", { url: origin, browserContextId });
const { sessionId } = await cdp("Target.attachToTarget", { targetId, flatten: true });
async function evaluate(expression) {
  const result = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
async function until(expression, label) {
  const result = await evaluate(`(async () => { const until = Date.now() + 6500; do { if (${expression}) return true; await new Promise(resolve => setTimeout(resolve, 40)); } while (Date.now() < until); return false; })()`);
  assert.ok(result, label);
  return result;
}
const click = text => evaluate(`(() => { const button = [...document.querySelectorAll('button')].find(button => { const label = button.cloneNode(true); label.querySelectorAll('.education-note-tag').forEach(tag => tag.remove()); return button.checkVisibility() && label.textContent.trim() === ${JSON.stringify(text)}; }); if (!button) throw new Error('Missing button: ' + ${JSON.stringify(text)}); button.click(); })()`);
const typeNote = value => evaluate(`(() => { const input = document.querySelector('.education-notes-pane textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(value)}); input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
const openFirstCourse = async () => {
  await evaluate("document.querySelector('.education-course-row h3 button').click()");
  await until("document.querySelector('.education-course-heading h2')", "course opened");
};
async function snapshot(name, width, height) {
  await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 }, sessionId);
  await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const overflow = await evaluate("document.querySelector('dialog').scrollWidth - document.querySelector('dialog').clientWidth");
  assert.ok(overflow <= 1, `${name} has no horizontal overflow`);
  if (process.env.EDUCATION_TEST_ARTIFACT_DIR) {
    await mkdir(process.env.EDUCATION_TEST_ARTIFACT_DIR, { recursive: true });
    const { data } = await cdp("Page.captureScreenshot", { format: "png" }, sessionId);
    await writeFile(join(process.env.EDUCATION_TEST_ARTIFACT_DIR, `${name}.png`), Buffer.from(data, "base64"));
  }
}
try {
  await cdp("Runtime.enable", {}, sessionId);
  await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false }, sessionId);
  await until("document.querySelector('main') || document.querySelector('.login-page')", "application is ready");
  await evaluate(`(async () => {
    const { demoSession } = await import('/src/roles.js');
    const { educationState } = await import('/src/education-local.js');
    const stored = JSON.parse(localStorage.getItem('dangjian.demo.v1'));
    stored.education = structuredClone(educationState(stored));
    Object.assign(stored.education.offerings[1].content, { video_url: 'data:video/mp4;base64,', duration_seconds: 20 });
    localStorage.setItem('dangjian.demo.v1', JSON.stringify(stored));
    sessionStorage.setItem('dangjian.auth.v1', JSON.stringify(demoSession('student')));
    location.hash = '/learning';
    location.reload();
  })()`);
  await until("document.querySelector('.education-course-row')", "personal courses loaded");
  await openFirstCourse();
  console.log("Course:", await evaluate("document.querySelector('.education-course-heading h2').textContent"));
  await click("开始本次学习");
  await until("[...document.querySelectorAll('.education-course-primary button')].some(button => button.textContent === '进入测评')", "course enrollment saved");
  await click("记录笔记");
  await until("document.querySelector('.education-notes-pane:not([hidden]) textarea:not([disabled])')", "notes tab opens an editable notebook");
  assert.equal(await evaluate("document.activeElement === document.querySelector('.education-notes-pane textarea')"), true, "note action focuses the editor");
  await typeNote("学习笔记回归检查");
  await until("document.querySelector('.education-notes-tab .unsaved')", "unsaved draft is clearly marked");
  await click("学习内容");
  await click("本人笔记");
  assert.equal(await evaluate("document.querySelector('.education-notes-pane textarea').value"), "学习笔记回归检查", "switching tabs preserves the note draft");
  await click("保存本人笔记");
  await until("document.querySelector('.education-note-feedback').textContent.includes('当前章节笔记已保存')", "saving notes gives inline confirmation");
  assert.equal(await evaluate("document.querySelector('.education-note-chapter .education-note-tag')?.textContent"), "有笔记", "saved chapter carries a note tag");
  await snapshot("notes-desktop", 1440, 1000);
  await snapshot("notes-mobile", 390, 844);
  await click("返回课程");
  await until("document.querySelector('.education-course-row .education-note-tag')", "course list immediately reflects saved notes");
  await openFirstCourse();
  await click("本人笔记");
  assert.equal(await evaluate("document.querySelector('.education-notes-pane textarea').value"), "学习笔记回归检查", "saved notes survive reopening");
  console.log("PASS: note action, draft preservation, saving, chapter/course tags and reopening");
  await click("课程测评");
  await until("document.querySelector('.education-assessment-pane:not([hidden]) form')", "assessment opened");
  await evaluate(`document.querySelector('input[name="Q1"][value="1"]').click();`);
  await click("提交考试");
  assert.equal(await evaluate("document.querySelector('.education-exam-review')"), null, "incomplete answers do not submit an attempt");
  await evaluate(`document.querySelector('input[name="Q2"][value="1"]').click();`);
  await click("提交考试");
  await until("document.querySelector('.education-exam-review .education-answer-state.incorrect')", "failed attempt shows which answer was wrong");
  assert.match(await evaluate("document.querySelector('.education-exam-review').innerText"), /50 分.*未通过/, "failed attempt retains its score and explanation");
  await evaluate(`document.querySelector('input[name="Q1"][value="0"]').click();`);
  assert.equal(await evaluate(`document.querySelector('input[name="Q2"][value="1"]').checked`), true, "previously selected answers survive result updates");
  await click("提交考试");
  await until("document.querySelector('.education-completed')", "assessment completes");
  const assessment = await evaluate("document.querySelector('.education-assessment-pane').innerText");
  assert.match(assessment, /正确答案/, "submitted assessment shows the correct answers");
  assert.match(assessment, /未经核对的转述不能替代原文/, "submitted assessment shows authored explanations");
  await snapshot("assessment-mobile", 390, 844);
  await snapshot("assessment-desktop", 1440, 1000);
  await click("返回课程");
  await openFirstCourse();
  await click("课程测评");
  assert.match(await evaluate("document.querySelector('.education-assessment-pane').innerText"), /本人答案：A\./, "answers survive reopening a completed course");
  await click("本人笔记");
  await typeNote("");
  await click("保存本人笔记");
  await until("!document.querySelector('.education-notes-tab .education-note-tag')", "clearing the last note removes the notebook tag");
  await click("返回课程");
  await until("!document.querySelector('.education-course-row .education-note-tag')", "clearing the last note removes the course tag");
  await openFirstCourse();
  await click("本人笔记");
  assert.equal(await evaluate("document.querySelector('.education-notes-pane textarea').value"), "", "cleared notes stay empty when reopened");
  await click("返回课程");
  await evaluate("document.querySelectorAll('.education-all-courses .education-course-row h3 button')[1].click()");
  await until("document.querySelector('.education-course-heading h2')", "multi-material course opened");
  await click("开始本次学习");
  await until("[...document.querySelectorAll('.education-course-primary button')].some(button => button.textContent === '记录笔记')", "multi-material course started");
  await click("记录笔记");
  await typeNote("导读章节的独立草稿");
  await evaluate("document.querySelectorAll('.education-note-chapter')[1].click()");
  assert.equal(await evaluate("document.querySelector('.education-notes-pane textarea').value"), "", "another chapter starts with its own empty note");
  await typeNote("视频章节的独立笔记");
  await click("保存本人笔记");
  await until("document.querySelector('.education-note-chapter:nth-child(2) .education-note-tag')", "video chapter is tagged after saving");
  await evaluate("document.querySelectorAll('.education-note-chapter')[0].click()");
  assert.equal(await evaluate("document.querySelector('.education-notes-pane textarea').value"), "导读章节的独立草稿", "switching chapters preserves the first draft");
  assert.equal(await evaluate("document.querySelector('.education-note-chapter:first-child .education-note-tag')"), null, "an unsaved chapter is not marked as saved");
  await click("保存本人笔记");
  await until("document.querySelectorAll('.education-note-chapter .education-note-tag').length === 2", "both chapters retain distinct saved notes and tags");
  await snapshot("chapter-notes-desktop", 1440, 1000);
  await snapshot("chapter-notes-mobile", 390, 844);
  await typeNote("");
  await click("保存本人笔记");
  await until("document.querySelectorAll('.education-note-chapter .education-note-tag').length === 1", "clearing one chapter preserves the other chapter tag");
  assert.equal(await evaluate("document.querySelector('.education-notes-tab .education-note-tag')?.textContent"), "有笔记", "remaining chapter notes keep the course notebook marked");
  assert.equal(exceptions.length, 0, "no browser exceptions");
  console.log("PASS: incomplete/failed/passed assessments, answers/explanations, reopening and clearing notes");
  console.log("PASS: independent chapter drafts, saved notes and per-chapter tags");
} finally {
  await cdp("Target.disposeBrowserContext", { browserContextId });
  socket.close();
}
