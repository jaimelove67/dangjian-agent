import { useRef, useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { PageHeader, Tabs, Modal, ErrorBox, Field } from "../components";
import { get, send, key, rows } from "../business-api";
import { formatBusinessTime } from "../business-time";
import { BusinessForm, BusinessTable, ResourceState, Status, options, useResource } from "../components/BusinessForms";

const timeISO = value => new Date(value).toISOString();
const localTime = formatBusinessTime;
export function LiveEducation({ eventOnly = false }) {
  const { session } = useApp(), { notify } = useStore();
  const manager = ["school_admin", "department_admin", "branch_secretary", "organizer"].includes(session.user.role);
  const [tab, setTab] = useState(eventOnly ? "主题党日" : "课程与考试"), [selected, setSelected] = useState(null), [form, setForm] = useState(null), [error, setError] = useState(null), [examBusy, setExamBusy] = useState(false), [own, setOwn] = useState(null);
  const kind = tab === "主题党日" ? "event" : "course";
  const offerings = useResource(() => get("/education/offerings", { kind }), [kind]);
  const credits = useResource(() => get("/education/credits"), []);
  const orgs = useResource(() => manager ? get("/member/org-units") : Promise.resolve([]), [manager]);
  const detail = useResource(() => selected ? get(`/education/offerings/${key(selected)}`) : Promise.resolve(null), [selected]);
  const enrollments = useResource(() => selected && detail.value?.can_manage ? get(`/education/offerings/${key(selected)}/enrollments`) : Promise.resolve(null), [selected, detail.value?.can_manage]);
  const video = useRef(null), tick = useRef({ at: 0, busy: false }), ended = useRef(false);
  const d = detail.value, progress = own || d?.own;
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, submit, initial, description }); }
  async function save(path, body) { const result = await send(path, body); offerings.reload(); detail.reload(); credits.reload(); enrollments.reload(); notify("学习业务记录已保存"); return result; }
  function create() {
    const scope = [{ name: "org_unit_id", label: "课程 / 活动组织及下属范围", options: options(rows(orgs.value)) }, { name: "title", label: "标题", maxLength: 200 }, { name: "description", label: "学习或活动要求", type: "textarea", max: 5000 }, { name: "points", label: "完成积分", type: "number", min: 0, max: 1000, value: 1 }];
    if (kind === "event") open("编制主题党日活动", [...scope, { name: "starts_at", label: "开始时间", type: "datetime-local" }, { name: "registration_deadline", label: "报名截止时间", type: "datetime-local" }, { name: "location", label: "活动地点" }, { name: "capacity", label: "报名人数上限", type: "number", min: 1, max: 10000 }], values => save("/education/events", { ...values, starts_at: timeISO(values.starts_at), registration_deadline: timeISO(values.registration_deadline) }));
    else open("编制视频课程与考试", [...scope,
      { name: "video_url", label: "视频地址（HTTP / HTTPS）", type: "url", required: false, maxLength: 2000 }, { name: "duration_seconds", label: "视频时长（秒）", type: "number", min: 0, max: 86400, value: 0 },
      { name: "questions", label: "单选题（每行：题目 | 选项A | 选项B | 正确选项序号）", type: "textarea", max: 60000, required: false, help: "可有2–8个选项，正确序号从1开始；仅考试课程可留空视频" },
      { name: "passing_score", label: "合格分数", type: "number", min: 1, max: 100, value: 60 }, { name: "max_attempts", label: "最多考试次数", type: "number", min: 1, max: 10, value: 3 },
    ], values => {
      const questions = String(values.questions || "").split(/\r?\n/).filter(s => s.trim()).map((line, index) => {
        const pieces = line.split("|").map(s => s.trim()), correct = Number(pieces.pop());
        if (pieces.length < 3 || pieces.length > 9 || !Number.isInteger(correct) || correct < 1 || correct >= pieces.length) throw new Error(`第${index + 1}行题目、选项或正确序号格式有误`);
        return { id: `Q${index + 1}`, text: pieces[0], options: pieces.slice(1), correct_index: correct - 1 };
      });
      return save("/education/courses", { ...values, video_url: values.video_url || null, questions });
    }, {}, "发布后本版本内容固定。标准答案只向有维护权限的组织人员返回，学员成绩、次数及积分由系统核算。");
  }
  function publish() { open("确认发布当前版本", [{ name: "reason", label: "发布依据", type: "textarea" }], values => save(`/education/offerings/${key(d.id)}/publish`, { ...values, expected_revision: d.revision })); }
  async function enroll() { try { const result = await save(`/education/offerings/${key(d.id)}/enroll`, {}); setOwn(result.own); } catch (failure) { setError(failure); } }
  async function heartbeat(force = false) {
    if (!video.current || video.current.paused && !force || tick.current.busy || !progress || progress.status === "completed") return;
    if (!force && Date.now() - tick.current.at < 10000) return;
    tick.current = { at: Date.now(), busy: true };
    try { const result = await send(`/education/offerings/${key(d.id)}/heartbeat`, { position_seconds: video.current.currentTime }); setOwn(result); if (result.status === "completed") { credits.reload(); offerings.reload(); } }
    catch (failure) { setError(failure); }
    finally { tick.current.busy = false; }
  }
  async function exam(event) {
    event.preventDefault(); if (examBusy) return;
    const fields = new FormData(event.currentTarget), answers = {};
    for (const q of d.content.questions) { if (!fields.has(q.id)) { setError(new Error("请完成每一道题目")); return; } answers[q.id] = Number(fields.get(q.id)); }
    setExamBusy(true); setError(null);
    try { const result = await send(`/education/offerings/${key(d.id)}/exam`, { answers }); setOwn(result); credits.reload(); offerings.reload(); notify(result.passed ? `考试通过，成绩${result.score}分` : `本次${result.score}分，可按剩余次数继续学习后重试`); }
    catch (failure) { setError(failure); } finally { setExamBusy(false); }
  }
  function attendance(user) { open("确认本人核验的实际出席", [{ name: "reason", label: "出席核验依据", type: "textarea" }], values => save(`/education/offerings/${key(d.id)}/attendance`, { ...values, user_id: user.user_id, attended: true })); }
  return <section className="panel workspace-panel"><PageHeader title={eventOnly ? "主题党日与报名" : "学习课程、活动与积分"} subtitle="报名记录、视频学习进度、考试成绩与本人积分" action={manager && tab !== "我的积分" && <button className="button primary" onClick={create}>{kind === "event" ? "编制活动" : "编制课程"}</button>} />
    <Tabs items={eventOnly ? ["主题党日", "我的积分"] : ["课程与考试", "主题党日", "我的积分"]} active={tab} onChange={setTab} />
    <div className="business-toolbar"><button className="button secondary" onClick={() => { offerings.reload(); credits.reload(); }}>刷新</button></div>
    {tab === "我的积分" ? <><ResourceState resource={credits} /><h3>本人累计积分：{credits.value?.total_points ?? "—"}</h3><BusinessTable items={rows(credits.value)} columns={[["课程 / 活动", r => r.title], ["积分", r => r.points], ["完成时间", r => localTime(r.completed_at)]]} /></> : <><ResourceState resource={offerings} /><BusinessTable items={rows(offerings.value)} columns={[["课程 / 活动", r => r.title], ["要求", r => r.content.description], ["状态", r => <Status value={r.status} />], ["本人进度", r => r.own ? <Status value={r.own.status} /> : "尚未报名 / 开始"], ["积分", r => r.content.points], ["操作", r => <button className="text-button link" onClick={() => { setSelected(r.id); setOwn(null); setError(null); tick.current = { at: 0, busy: false }; }}>查看与办理</button>]]} /></>}
    {selected && <Modal title="学习与活动办理" wide flat onClose={() => { setSelected(null); setOwn(null); }}><ResourceState resource={detail} />{d && <><h3>{d.title}</h3><Status value={d.status} /><p className="business-content">{d.content.description}</p>{error && <ErrorBox error={error} />}
      {d.status === "draft" && d.can_manage && <button className="button primary" onClick={publish}>确认发布</button>}
      {d.kind === "event" && <><p>活动时间：{localTime(d.content.starts_at)}；地点：{d.content.location}</p><p>报名截止：{localTime(d.content.registration_deadline)}；已报名{d.enrolled_count} / {d.content.capacity}人</p></>}
      {d.status === "published" && (!progress || progress.status === "cancelled") && <button className="button primary" onClick={enroll}>{d.kind === "event" ? "本人报名" : "开始学习"}</button>}
      {progress && progress.status !== "cancelled" && <><p>本人状态：<Status value={progress.status} />；已获得{progress.points}积分</p>{d.kind === "event" && progress.status !== "completed" && <button className="button secondary" onClick={() => open("取消本人报名", [{ name: "confirm", label: "确认取消本次报名", type: "checkbox" }], async values => { if (!values.confirm) throw new Error("请先确认"); const result = await save(`/education/offerings/${key(d.id)}/cancel`, {}); setOwn(result.own); })}>取消报名</button>}
        {d.kind === "course" && <>{d.content.video_url && <><video ref={video} className="business-video" controls preload="metadata" src={d.content.video_url} onLoadedMetadata={() => { if (video.current && progress.position_seconds) video.current.currentTime = progress.position_seconds; }} onTimeUpdate={() => heartbeat()} onPause={() => heartbeat(true)} onEnded={() => heartbeat(true)} /><p>已记录有效学习{Math.floor(progress.watched_seconds || 0)} / {d.content.duration_seconds}秒。正常播放每10秒保存；暂停、拖动或直接报送完成时间不会自动获得积分。</p></>}
          {d.content.questions?.length > 0 && progress.status !== "completed" && <form onSubmit={exam}><p>合格分数{d.content.passing_score}；已使用{progress.attempts || 0} / {d.content.max_attempts}次。{progress.score != null && `最近成绩：${progress.score}分`}</p><fieldset disabled={examBusy}>{d.content.questions.map(q => <Field full key={q.id} label={q.text} required><div>{q.options.map((label, index) => <label key={index} style={{ display: "block", margin: "10px 0" }}><input type="radio" name={q.id} value={index} required /> {label}</label>)}</div></Field>)}</fieldset><button className="button primary" disabled={examBusy || (progress.attempts || 0) >= d.content.max_attempts}>{examBusy ? "正在提交…" : "提交考试"}</button></form>}
        </>}
      </>}
      {d.can_manage && <section className="business-section"><header><h3>{d.kind === "event" ? "报名与实际出席" : "组织学习进度"}</h3><button className="button secondary" onClick={enrollments.reload}>刷新进度</button></header><ResourceState resource={enrollments} /><BusinessTable items={rows(enrollments.value)} columns={[["学员", r => r.name], ["状态", r => <Status value={r.status} />], ["考试 / 学习", r => d.kind === "course" ? `${r.score ?? "未考试"} · ${Math.floor(r.watched_seconds)}秒` : "已登记报名"], ["积分", r => r.points], ["操作", r => d.kind === "event" && !["completed", "cancelled"].includes(r.status) && r.user_id !== session.user.id && <button className="text-button link" onClick={() => attendance(r)}>核验实际出席</button>]]} /></section>}
    </>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
