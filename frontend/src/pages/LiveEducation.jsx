import { useEffect, useRef, useState } from "react";
import { BookOpen, ArrowRight, GraduationCap } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { PageHeader, Tabs, Modal, ErrorBox, SearchInput, Select } from "../components";
import { key, rows } from "../business-api";
import { useEducationApi } from "../education-api";
import { EDUCATION_MANAGERS, educationNotes } from "../education-local";
import { isSelfService } from "../roles";
import { formatBusinessTime } from "../business-time";
import { BusinessForm, BusinessTable, BusinessToolbar, ResourceState, Status, options, useResource } from "../components/BusinessForms";
import { EducationLearnerWorkspace } from "../components/EducationLearnerWorkspace";
import { EducationCourseDialog } from "../components/EducationCourseDialog";
import { saveHeartbeatWithPending } from "../education-heartbeat";
import "../education.css";

const timeISO = value => new Date(value).toISOString();
const localTime = formatBusinessTime;
export function LiveEducation({ eventOnly = false }) {
  const { session, routeParams } = useApp(), { notify } = useStore();
  const { get, send, identity } = useEducationApi();
  const manager = EDUCATION_MANAGERS.has(session.user.role), personal = isSelfService(session.user);
  const [tab, setTab] = useState(eventOnly ? "主题党日" : ["主题党日", "我的积分"].includes(routeParams.tab) ? routeParams.tab : "课程与考试");
  const [selected, setSelected] = useState(routeParams.offeringId || null), [form, setForm] = useState(null), [error, setError] = useState(null), [examBusy, setExamBusy] = useState(false), [own, setOwn] = useState(null), [query, setQuery] = useState(""), [filter, setFilter] = useState(""), [notes, setNotes] = useState({}), [savingNote, setSavingNote] = useState(false), [videoError, setVideoError] = useState(false), [enrollBusy, setEnrollBusy] = useState(false);
  const kind = tab === "主题党日" ? "event" : "course";
  const offerings = useResource(() => get("/education/offerings", { kind }), [identity, kind]);
  const credits = useResource(() => get("/education/credits"), [identity]);
  const registeredEvents = useResource(() => personal && !eventOnly ? get("/education/offerings", { kind: "event" }) : Promise.resolve(null), [identity, personal, eventOnly]);
  const orgs = useResource(() => manager ? get("/member/org-units") : Promise.resolve([]), [identity, manager]);
  const detail = useResource(() => selected ? get(`/education/offerings/${key(selected)}`) : Promise.resolve(null), [identity, selected]);
  const d = detail.value?.id === selected ? detail.value : null;
  const enrollments = useResource(() => selected && d?.can_manage ? get(`/education/offerings/${key(selected)}/enrollments`) : Promise.resolve(null), [identity, selected, d?.can_manage]);
  const video = useRef(null), tick = useRef({ at: 0, busy: false }), active = useRef(null);
  active.current = `${identity}:${selected}`;
  const progress = own?.id === selected ? own.value : d?.own;
  const acceptProgress = (id, scope, value) => {
    if (active.current !== `${scope}:${id}`) return;
    setOwn(previous => {
      const before = previous?.id === id ? previous.value : null;
      if (before && ((before.status === "completed" && value.status !== "completed") || (before.attempts || 0) > (value.attempts || 0) || (before.watched_seconds || 0) > (value.watched_seconds || 0))) return previous;
      return { id, value };
    });
  };
  useEffect(() => { setOwn(null); setError(null); setVideoError(false); setNotes({}); tick.current = { at: 0, busy: false }; }, [identity, selected]);
  useEffect(() => { if (d) setNotes(educationNotes(d.own)); }, [d?.id]);
  useEffect(() => () => { active.current = null; }, []);
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, submit, initial, description }); }
  async function save(path, body) { const result = await send(path, body); offerings.reload(); detail.reload(); credits.reload(); enrollments.reload(); if (d?.kind === "event") registeredEvents.reload(); notify("学习业务记录已保存"); return result; }
  function create() {
    const scope = [{ name: "org_unit_id", label: "课程 / 活动组织及下属范围", options: options(rows(orgs.value)) }, { name: "title", label: "标题", maxLength: 200 }, { name: "description", label: "学习或活动要求", type: "textarea", max: 5000 }, { name: "points", label: "完成积分", type: "number", min: 0, max: 1000, value: 1 }];
    if (kind === "event") open("编制主题党日活动", [...scope, { name: "starts_at", label: "开始时间", type: "datetime-local" }, { name: "registration_deadline", label: "报名截止时间", type: "datetime-local" }, { name: "location", label: "活动地点" }, { name: "capacity", label: "报名人数上限", type: "number", min: 1, max: 10000 }], values => save("/education/events", { ...values, starts_at: timeISO(values.starts_at), registration_deadline: timeISO(values.registration_deadline) }));
    else open("编制视频课程与考试", [...scope,
      { name: "video_url", label: "视频地址（HTTP / HTTPS）", type: "url", required: false, maxLength: 2000 }, { name: "duration_seconds", label: "视频时长（秒）", type: "number", min: 0, max: 86400, value: 0 },
      { name: "questions", label: "单选题（每行：题目 | 选项A | 选项B | 正确选项序号 | 解析：说明）", type: "textarea", max: 60000, required: false, help: "可有2–8个选项，正确序号从1开始；末尾可填写“解析：说明”，学员提交后查阅。仅考试课程可留空视频。" },
      { name: "passing_score", label: "合格分数", type: "number", min: 1, max: 100, value: 60 }, { name: "max_attempts", label: "最多考试次数", type: "number", min: 1, max: 10, value: 3 },
    ], values => {
      const questions = String(values.questions || "").split(/\r?\n/).filter(s => s.trim()).map((line, index) => {
        const pieces = line.split("|").map(s => s.trim());
        const explanation = /^解析[:：]/.test(pieces.at(-1)) ? pieces.pop().replace(/^解析[:：]\s*/, "") : "";
        const correct = Number(pieces.pop());
        if (pieces.length < 3 || pieces.length > 9 || !Number.isInteger(correct) || correct < 1 || correct >= pieces.length) throw new Error(`第${index + 1}行题目、选项或正确序号格式有误`);
        return { id: `Q${index + 1}`, text: pieces[0], options: pieces.slice(1), correct_index: correct - 1, explanation };
      });
      return save("/education/courses", { ...values, video_url: values.video_url || null, questions });
    }, {}, "发布后本版本内容固定。学员提交测评后可查看本人作答、正确答案与解析，成绩、次数及积分由系统核算。");
  }
  function publish() { open("确认发布当前版本", [{ name: "reason", label: "发布依据", type: "textarea" }], values => save(`/education/offerings/${key(d.id)}/publish`, { ...values, expected_revision: d.revision })); }
  async function enroll() {
    if (enrollBusy || !d) return;
    const id = d.id, scope = identity; setEnrollBusy(true); setError(null);
    try { const result = await save(`/education/offerings/${key(id)}/enroll`, {}); acceptProgress(id, scope, result.own); }
    catch (failure) { if (active.current === `${scope}:${id}`) setError(failure); }
    finally { setEnrollBusy(false); }
  }
  async function heartbeat(force = false) {
    if (!d || !video.current || (video.current.paused && !force) || !progress || progress.status === "completed" || (!force && (tick.current.busy || Date.now() - tick.current.at < 10000))) return;
    const id = d.id, scope = identity, position = video.current.currentTime;
    try { await saveHeartbeatWithPending(tick.current, position, async positionToSave => {
      const result = await send(`/education/offerings/${key(id)}/heartbeat`, { position_seconds: positionToSave });
      acceptProgress(id, scope, result);
      if (result.status === "completed" && active.current?.startsWith(`${scope}:`)) { credits.reload(); offerings.reload(); }
    }, force); }
    catch (failure) { if (active.current === `${scope}:${id}`) { setError(failure); if (failure.status === 422 && video.current) { video.current.pause(); video.current.currentTime = progress.position_seconds || 0; } } }
  }
  async function exam(event) {
    event.preventDefault(); if (examBusy || savingNote || !d) return;
    const fields = new FormData(event.currentTarget), answers = {}, id = d.id, scope = identity;
    for (const q of d.content.questions) { if (!fields.has(q.id)) { setError(new Error("请完成每一道题目")); return; } answers[q.id] = Number(fields.get(q.id)); }
    setExamBusy(true); setError(null);
    try { const result = await send(`/education/offerings/${key(id)}/exam`, { answers }); acceptProgress(id, scope, result); if (active.current !== `${scope}:${id}`) return; credits.reload(); offerings.reload(); notify(result.passed ? `考试通过，成绩${result.score}分` : `本次${result.score}分；${result.attempts >= d.content.max_attempts ? "已达考试次数上限，请联系组织人员" : "请继续学习后重试"}`); }
    catch (failure) { if (active.current === `${scope}:${id}`) setError(failure); }
    finally { setExamBusy(false); }
  }
  async function saveNote(materialId) {
    if (!d || savingNote || examBusy) return;
    const id = d.id, scope = identity; setSavingNote(true); setError(null);
    try { const result = await send(`/education/offerings/${key(id)}/notes`, { note: notes[materialId] || "", material_id: materialId }); acceptProgress(id, scope, result); if (active.current === `${scope}:${id}`) { offerings.reload(); notify("本人学习笔记已保存"); } }
    catch (failure) { if (active.current === `${scope}:${id}`) setError(failure); }
    finally { setSavingNote(false); }
  }
  function attendance(user) { open("核验实际出席", [{ name: "reason", label: "出席核验依据", type: "textarea" }], values => save(`/education/offerings/${key(d.id)}/attendance`, { ...values, user_id: user.user_id, attended: true })); }
  function closeDetail() { if (video.current && !video.current.paused) { heartbeat(true); video.current.pause(); } setSelected(null); setOwn(null); }
  const all = rows(offerings.value), published = all.filter(row => row.status === "published");
  const visible = all.filter(row => (!query.trim() || row.title.includes(query.trim())) && (!filter || (filter === "not_started" ? !row.own || row.own.status === "cancelled" : row.own?.status === filter)));
  const percent = row => row.own?.status === "completed" ? 100 : row.content.video_url ? Math.min(100, Math.floor((row.own?.watched_seconds || 0) / row.content.duration_seconds * 100)) : null;
  const changeTab = value => { setTab(value); setFilter(""); setQuery(""); };
  const managementPanel = d?.can_manage && <section className="business-section"><header><h3>{d.kind === "event" ? "报名与实际出席" : "组织学习进度"}</h3><button className="button secondary" onClick={enrollments.reload}>刷新进度</button></header><ResourceState resource={enrollments} /><BusinessTable items={rows(enrollments.value)} columns={[["学员", row => row.name], ["状态", row => <Status value={row.status} />], ["考试 / 学习", row => d.kind === "course" ? `${row.score ?? "未考试"} · ${Math.floor(row.watched_seconds)}秒` : "已登记报名"], ["积分", row => row.points], ["操作", row => d.kind === "event" && !["completed", "cancelled"].includes(row.status) && row.user_id !== session.user.id && <button className="text-button link" disabled={Date.parse(d.content.starts_at) > Date.now()} onClick={() => attendance(row)}>核验实际出席</button>]]} /></section>;
  return <section className={`education-workspace ${personal && !eventOnly ? "education-personal" : "panel workspace-panel"}`}>
    <div className={personal && !eventOnly ? "panel education-page-heading" : undefined}>
    <PageHeader title={eventOnly ? "主题党日与报名" : personal ? "我的学习" : "学习课程与活动"} subtitle={personal && !eventOnly ? "查阅组织课程，记录本人学习情况。" : "按所属组织查阅课程，记录本人学习、测评与参学情况"} action={manager && tab !== "我的积分" && <button className="button primary" disabled={orgs.loading || !!orgs.error || !rows(orgs.value).length} onClick={create}>{kind === "event" ? "编制活动" : "编制课程"}</button>} />
    {(!personal || eventOnly) && <div className="education-overview"><span><BookOpen size={19} />已发布{kind === "event" ? "活动" : "课程"}<strong>{offerings.loading || offerings.error ? "—" : published.length}</strong></span><span><GraduationCap size={19} />本人已完成<strong>{offerings.loading || offerings.error ? "—" : published.filter(row => row.own?.status === "completed").length}</strong></span><button onClick={() => setTab("我的积分")}>本人累计积分<strong>{credits.loading || credits.error ? "—" : credits.value?.total_points ?? 0}</strong><ArrowRight size={15} /></button></div>}
    <Tabs items={eventOnly ? ["主题党日", "我的积分"] : [{ id: "课程与考试", label: "课程学习" }, "主题党日", "我的积分"]} active={tab} onChange={changeTab} />
    </div>
    {personal && !eventOnly && tab === "课程与考试" ? <EducationLearnerWorkspace offerings={offerings} credits={credits} events={registeredEvents} query={query} setQuery={setQuery} filter={filter} setFilter={setFilter} onSelect={setSelected} onTab={changeTab} /> : <div className={personal && !eventOnly ? "panel education-secondary" : undefined}>
    <BusinessToolbar actions={<button className="button secondary" onClick={() => { offerings.reload(); credits.reload(); }}>刷新</button>}>
      {tab === "我的积分" ? <p className="education-help">积分按已完成课程和经组织人员核验的活动记录累计，同一课程或活动只计一次。</p> : <><SearchInput placeholder={kind === "event" ? "搜索活动名称" : "搜索课程名称"} value={query} onChange={e => setQuery(e.target.value)} /><Select label="本人学习状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部状态</option><option value="not_started">未开始 / 未报名</option><option value="enrolled">学习中 / 已报名</option><option value="completed">已完成</option></Select></>}
    </BusinessToolbar>
    {manager && orgs.error && <ErrorBox error={orgs.error} retry={orgs.reload} />}
    {manager && !orgs.loading && !orgs.error && !rows(orgs.value).length && <p className="education-help">当前账号没有可维护的组织，请联系学校管理员核对组织授权。</p>}
    {!selected && error && <ErrorBox error={error} />}
    {tab === "我的积分" ? <><ResourceState resource={credits} /><BusinessTable items={rows(credits.value)} columns={[["课程 / 活动", row => row.title], ["积分", row => row.points], ["完成时间", row => localTime(row.completed_at)], ["操作", row => <button className="text-button link" onClick={() => setSelected(row.offering_id)}>查看记录</button>]]} /></> : <><ResourceState resource={offerings} /><BusinessTable items={visible} columns={[["课程 / 活动", row => <><strong>{row.title}</strong><small className="cell-subtext">{row.kind === "course" ? (row.org_unit_name || "所属组织发布") : `${localTime(row.content.starts_at)} · ${row.content.location}`}</small></>], ["发布状态", row => <Status value={row.status} />], ["本人进度", row => <>{row.own ? <Status value={row.own.status} /> : "未开始 / 未报名"}{percent(row) != null && <small className="cell-subtext">{percent(row)}%</small>}</>], ["完成积分", row => row.content.points], ["操作", row => <button className="button secondary" onClick={() => setSelected(row.id)}>{row.status === "draft" ? "查看草稿" : row.own?.status === "completed" ? "查看记录" : row.own && row.own.status !== "cancelled" ? row.kind === "course" ? "继续学习" : "查看报名" : row.kind === "course" ? "开始学习" : "查看活动"}</button>]]} /></>}
    </div>}
    {selected && d?.kind !== "event" && <EducationCourseDialog key={`${identity}:${selected}`} course={d} resource={detail} progress={progress} error={error} onClose={closeDetail} enrollBusy={enrollBusy} onEnroll={enroll} onPublish={publish} notes={notes} setNote={(materialId, value) => setNotes(previous => ({ ...previous, [materialId]: value }))} savingNote={savingNote} onSaveNote={saveNote} examBusy={examBusy} onExam={exam} videoRef={video} onHeartbeat={heartbeat} videoError={videoError} onVideoError={() => setVideoError(true)} management={managementPanel} />}
    {selected && d?.kind === "event" && <Modal title="活动与报名" wide flat className="education-detail" onClose={closeDetail}><ResourceState resource={detail} />{d && <>
      <h2>{d.title}</h2><p className="education-detail-meta"><Status value={d.status} /><span>完成积分 {d.content.points}</span>{progress && <Status value={progress.status} />}</p><p className="business-content">{d.content.description}</p>{error && <ErrorBox error={error} />}
      {d.status === "draft" && d.can_manage && <button className="button primary" onClick={publish}>确认发布</button>}
      {d.kind === "event" && <><p>活动时间：{localTime(d.content.starts_at)}；地点：{d.content.location}</p><p>报名截止：{localTime(d.content.registration_deadline)}；已报名 {d.enrolled_count} / {d.content.capacity} 人</p></>}
      {d.status === "published" && (!progress || progress.status === "cancelled") && <button className="button primary" disabled={enrollBusy || (d.kind === "event" && (Date.parse(d.content.registration_deadline) <= Date.now() || d.enrolled_count >= d.content.capacity))} onClick={enroll}>{enrollBusy ? "正在办理…" : d.kind === "event" ? Date.parse(d.content.registration_deadline) <= Date.now() ? "报名已截止" : d.enrolled_count >= d.content.capacity ? "名额已满" : "本人报名" : "开始本次学习"}</button>}
      {progress && progress.status !== "cancelled" && <>
        <p className="education-help">本人已获得 {progress.points} 积分{progress.score != null && ` · 最近成绩 ${progress.score} 分`}</p>
        {d.kind === "event" && progress.status !== "completed" && <><p className="education-help">报名已记录。实际出席由其他有权限的组织人员核验后登记积分。</p><button className="button secondary" disabled={Date.parse(d.content.registration_deadline) <= Date.now()} onClick={() => open("取消本人报名", [{ name: "confirm", label: "确认取消本次报名", type: "checkbox" }], async values => { if (!values.confirm) throw new Error("请先确认"); const result = await save(`/education/offerings/${key(d.id)}/cancel`, {}); setOwn({ id: d.id, value: result.own }); })}>取消报名</button></>}
      </>}
      {managementPanel}
    </>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
