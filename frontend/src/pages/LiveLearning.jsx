import { formatBusinessTime } from "../business-time";
import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { hasPermission } from "../roles";
import { PageHeader, Select, Modal, ErrorBox, downloadBlob } from "../components";
import { request } from "../api";
import { get, send, key, rows } from "../business-api";
import { meetingParticipants } from "../contracts";
import { BusinessForm, BusinessTable, RecordTrace, ResourceState, Status, lines, options, useResource } from "../components/BusinessForms";

export function LiveLearning() {
  const { session } = useApp(), { notify } = useStore();
  const can = p => hasPermission(session, p);
  const [error, setError] = useState(null);
  const [year, setYear] = useState(new Date().getFullYear()), [org, setOrg] = useState(""), [form, setForm] = useState(null), [planId, setPlanId] = useState(null), [activityId, setActivityId] = useState(null), [history, setHistory] = useState(null);
  const orgs = useResource(() => get("/study/org-units"), []);
  const plans = useResource(() => get("/study/plans", { year, org_unit_id: org, page_size: 100 }), [year, org]);
  const plan = useResource(() => planId ? get(`/study/plans/${key(planId)}`) : Promise.resolve(null), [planId]);
  const activity = useResource(() => activityId ? get(`/study/activities/${key(activityId)}`) : Promise.resolve(null), [activityId]);
  const docs = useResource(() => get("/knowledge-docs", { page_size: 100 }), []);
  const sources = rows(docs.value).map(d => [d.doc_id, `${d.title} · v${d.content_revision}`]);
  const sourceField = { name: "source_doc_ids", label: "有效制度依据（可多选）", type: "multi", options: sources, required: false, help: "草稿可暂缺；送审前须补齐有效制度及原文摘录" };
  const reasonField = { name: "reason", label: "办理依据 / 修订说明", type: "textarea", max: 2000 };
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, submit, initial, description }); }
  async function save(path, body, method = "POST") {
    const result = await send(path, body, method); plans.reload(); plan.reload(); activity.reload(); notify("学习业务记录已保存"); return result;
  }
  function planForm(p) {
    open(p ? "修订年度学习计划" : "编制年度学习计划", [
      ...(!p ? [{ name: "org_unit_id", label: "党委组织", options: options(rows(orgs.value)), value: org }, { name: "year", label: "年度", type: "number", min: 2000, max: 2100, value: year }] : []),
      { name: "title", label: "计划标题" }, { name: "responsible", label: "责任人", maxLength: 100 },
      { name: "priorities", label: "年度重点（每行一项，最多12项）", type: "textarea" }, sourceField, reasonField,
    ], values => save(p ? `/study/plans/${key(p.id)}` : "/study/plans", { ...values, priorities: lines(values.priorities), ...(p ? { expected_revision: p.revision } : {}) }, p ? "PATCH" : "POST"), p ? { ...p, priorities: p.priorities.join("\n") } : {});
  }
  function itemForm(p, item) {
    open(item ? "修订学习安排" : "增加学习安排", [
      { name: "topic", label: "学习主题" }, { name: "scheduled_on", label: "计划日期", type: "date" }, { name: "responsible", label: "负责人", maxLength: 100 }, sourceField,
      ...(item ? [{ name: "agenda", label: "议程", type: "textarea", max: 20000 }, { name: "outline", label: "学习提纲", type: "textarea", max: 20000 }] : []), reasonField,
    ], values => save(`/study/plans/${key(p.id)}/items${item ? `/${key(item.id)}` : ""}`, { ...values, expected_revision: p.revision }, item ? "PATCH" : "POST"), item || {});
  }
  function recordAction(type, record, action) {
    const label = { submit: "提交审核", review: "审核当前版本", archive: "单独确认归档", "generate-minutes": "从原文提取纪要" }[action];
    open(label, [...(action === "review" ? [{ name: "decision", label: "审核结果", options: [["approved", "通过"], ["rejected", "退回补充"]] }] : []), reasonField], values => save(`/study/${type}/${key(record.id)}/${action}`, { ...values, expected_revision: record.revision }));
  }
  function editActivity(record) {
    open("登记实际学习与原始记录", [
      { name: "held_on", label: "实际学习日期", type: "date" }, { name: "host", label: "主持人", maxLength: 100 },
      { name: "participants", label: "实名参学（每行：编号 | 姓名 | 出席或缺席）", type: "textarea", max: 60000 },
      { name: "transcript", label: "原始记录", type: "textarea", max: 200000, rows: 12, help: "按实际内容分行标注“学习要点：”“讨论共识：”“工作要求：”，提取后核对原文定位。" }, sourceField, reasonField,
    ], values => save(`/study/activities/${key(record.id)}`, { ...values, participants: meetingParticipants(values.participants), expected_revision: record.revision }, "PATCH"), { ...record, participants: (record.participants || []).map(p => `${p.participant_id} | ${p.name} | ${p.attended ? "出席" : "缺席"}`).join("\n") });
  }
  async function revisions(type, record) { try { setHistory(await get(`/study/${type}/${key(record.id)}/revisions`)); } catch (failure) { setError(failure); } }
  function actions(type, record) {
    return <div className="business-actions">{can("study.manage") && !record.archived_at && <>
      <button className="button secondary" onClick={() => type === "plans" ? planForm(record) : editActivity(record)}>修订记录</button>
      {type === "activities" && <button className="button secondary" onClick={() => recordAction(type, record, "generate-minutes")}>提取纪要</button>}
      {["draft", "rejected"].includes(record.review_status) && <button className="button primary" onClick={() => recordAction(type, record, "submit")}>提交审核</button>}
      {type === "activities" && record.review_status === "approved" && can("meeting.archive") && <button className="button primary" onClick={() => recordAction(type, record, "archive")}>确认归档</button>}
    </>}{can("study.review") && record.review_status === "pending" && record.submitted_by !== session.user.id && <button className="button primary" onClick={() => recordAction(type, record, "review")}>人工审核</button>}<button className="button secondary" onClick={() => revisions(type, record)}>版本记录</button>
      {type === "activities" && record.archived_at && <button className="button secondary" onClick={() => open("导出已归档学习记录", [reasonField], async () => downloadBlob(await request(`/study/activities/${key(record.id)}/export`, { download: true }), "学习归档.json"))}>导出归档</button>}
    </div>;
  }
  function startActivity(p, item) {
    open("登记本期学习活动", [reasonField], async values => { const record = await save(`/study/plans/${key(p.id)}/items/${key(item.id)}/activity`, { ...values, expected_revision: p.revision }); setActivityId(record.id); });
  }
  return <section className="panel workspace-panel"><PageHeader title="全校学习计划与任务" subtitle="年度重点、分期安排、学习记录、独立审核和归档" action={can("study.manage") && <button className="button primary" disabled={!rows(orgs.value).length} onClick={() => planForm()}>编制学习计划</button>} />
    <div className="business-toolbar"><Select label="学习年度" value={year} onChange={e => setYear(Number(e.target.value))}>{Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - i).map(y => <option key={y}>{y}</option>)}</Select><Select label="党委组织" value={org} onChange={e => setOrg(e.target.value)}><option value="">全部授权党委</option>{rows(orgs.value).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</Select><button className="button secondary" onClick={plans.reload}>刷新</button></div>
    <ResourceState resource={orgs} /><ResourceState resource={plans} />{error && <ErrorBox error={error} />}
    {!orgs.loading && !rows(orgs.value).length && <p className="inline-note">中心组年度计划由学校和院系党委办理，支部党员教育请进入“课程与考试”或相关组织生活记录。</p>}
    <BusinessTable items={rows(plans.value)} columns={[["计划", p => p.title], ["组织 / 年度", p => `${rows(orgs.value).find(o => o.id === p.org_unit_id)?.name || "授权党委"} · ${p.year}`], ["负责人", p => p.responsible], ["状态", p => <Status value={p.review_status} />], ["任务", p => `${p.items?.length || 0}期`], ["操作", p => <button className="text-button link" onClick={() => setPlanId(p.id)}>查看与办理</button>]]} />
    {planId && <Modal title="年度学习计划" wide flat onClose={() => setPlanId(null)}><ResourceState resource={plan} />{plan.value && <><h3>{plan.value.title}</h3><Status value={plan.value.review_status} /><RecordTrace record={plan.value} /><ul>{plan.value.priorities.map(text => <li key={text}>{text}</li>)}</ul><p>制度依据：{plan.value.sources.map(s => s.title || s.doc_id).join("；") || "待补"}</p>{actions("plans", plan.value)}<div className="business-section"><header><h3>分期安排与执行</h3>{can("study.manage") && <button className="button secondary" onClick={() => itemForm(plan.value)}>增加安排</button>}</header><BusinessTable items={plan.value.items} columns={[["主题", item => item.topic], ["日期 / 负责人", item => `${item.scheduled_on} · ${item.responsible}`], ["进展", item => <Status value={item.execution_status} />], ["操作", item => <div className="inline-controls">{can("study.manage") && <button className="text-button link" onClick={() => itemForm(plan.value, item)}>修订安排</button>}{item.meeting_record_id ? <button className="text-button link" onClick={() => setActivityId(item.meeting_record_id)}>学习记录</button> : plan.value.review_status === "approved" && can("study.manage") && <button className="text-button link" onClick={() => startActivity(plan.value, item)}>登记活动</button>}</div>]]} /></div></>}</Modal>}
    {activityId && <Modal title="学习活动与纪要" wide flat onClose={() => setActivityId(null)}><ResourceState resource={activity} />{activity.value && <><h3>{activity.value.title}</h3><Status value={activity.value.archived_at ? "archived" : activity.value.review_status} /><RecordTrace record={activity.value} /><p>实际日期：{activity.value.held_on || "待登记"}；主持人：{activity.value.host || "待登记"}</p><p>实名出勤：{activity.value.participants.map(p => `${p.name}（${p.attended ? "出席" : "缺席"}）`).join("、")}</p><p className="business-content">{activity.value.transcript || "原始记录待补"}</p>{Object.entries(activity.value.minutes || {}).map(([category, entries]) => <div key={category}><h4>{{ learning_points: "学习要点", consensus: "共识", requirements: "要求" }[category] || category}</h4>{Array.isArray(entries) && entries.map((entry, index) => <p key={index}>{entry.text}<small className="cell-subtext">原文：{entry.quote}（{entry.start}–{entry.end}）</small></p>)}</div>)}{activity.value.missing?.length > 0 && <p className="inline-note">{activity.value.missing.join("；")}</p>}{actions("activities", activity.value)}</>}</Modal>}
    {history && <Modal title="修订与审核记录" wide flat onClose={() => setHistory(null)}><BusinessTable items={rows(history)} columns={[["版本", r => r.revision], ["操作", r => r.action], ["办理人", r => r.actor_id || r.user_id || r.created_by], ["依据 / 意见", r => r.reason], ["时间", r => formatBusinessTime(r.created_at)]]} /></Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
