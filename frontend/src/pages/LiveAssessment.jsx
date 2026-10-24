import { formatBusinessTime } from "../business-time";
import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { hasPermission } from "../roles";
import { PageHeader, Tabs, Select, Modal, ErrorBox, downloadBlob } from "../components";
import { request } from "../api";
import { get, send, key, rows } from "../business-api";
import { BusinessForm, BusinessTable, ResourceState, RecordTrace, Status, lines, options, useResource } from "../components/BusinessForms";

export function LiveAssessment() {
  const { session } = useApp(), { notify } = useStore();
  const can = permission => hasPermission(session, permission);
  const [org, setOrg] = useState(""), [year, setYear] = useState(new Date().getFullYear()), [tab, setTab] = useState("指标与归集"), [form, setForm] = useState(null), [detail, setDetail] = useState(null), [error, setError] = useState(null);
  const organizations = useResource(() => get("/assessment/org-units"), []);
  const orgId = org || rows(organizations.value).find(o => o.id === session.user.org_unit_id)?.id || rows(organizations.value)[0]?.id;
  const workspace = useResource(() => orgId ? get("/assessment/workspace", { org_unit_id: orgId, year }) : Promise.resolve(null), [orgId, year]);
  const w = workspace.value;
  const scope = { org_unit_id: orgId, year: Number(year) };
  const docs = useResource(() => get("/knowledge-docs", { page_size: 100 }), []);
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, initial, submit, description }); }
  async function action(path, body, method = "POST") {
    const result = await send(path, body, method);
    workspace.reload(); notify("业务记录已保存"); return result;
  }
  function confirmAction(title, path, body = {}, method = "POST") {
    open(title, [{ name: "confirmation", label: "请确认已核对该版本及学校办理要求", type: "checkbox", value: false }], async values => {
      if (!values.confirmation) throw new Error("请先勾选确认");
      await action(path, body, method);
    });
  }
  function review(kind, record) {
    open("人工审核当前版本", [{ name: "status", label: "审核结果", options: [["approved", "通过"], ["returned", "退回补充"]] }, { name: "opinion", label: "处理意见 / 退回原因", type: "textarea" }], values => action(`/assessment/${kind}/${key(record.id)}/review`, { ...values, expected_revision: record.revision }));
  }
  const reviewButton = (kind, record) => can("assessment.review") && !record.stale && record.created_by !== session.user.id && record.review_status !== "approved" && <button className="text-button link" onClick={() => review(kind, record)}>审核版本 {record.revision}</button>;
  function indicator(record) {
    open(record ? "修订年度指标" : "编制年度指标", [
      { name: "code", label: "指标编码", maxLength: 64 }, { name: "name", label: "指标名称", maxLength: 200 },
      { name: "requirement", label: "工作要求", type: "textarea", max: 4000 },
      { name: "source", label: "业务数据来源", options: [["organizations", "组织"], ["members", "党员"], ["member_materials", "党员材料完整率"], ["meetings", "会议"], ["studies", "学习"], ["documents", "制度文件"], ["manual", "有依据的人工特色项"]] },
      { name: "measure", label: "统计口径", options: [["count", "计数"], ["attendance_rate", "实名出勤率"], ["material_rate", "材料完整率"], ["sum", "人工有据求和"]] },
      { name: "target", label: "目标值", type: "number", min: 0, max: 1e12, step: "any" }, { name: "unit", label: "单位", value: "项", maxLength: 20 },
      { name: "comparison", label: "比较方式", options: [["gte", "不少于"], ["lte", "不多于"], ["eq", "等于"]], value: "gte" },
      { name: "period_start", label: "统计开始", type: "date", value: `${year}-01-01` }, { name: "period_end", label: "统计结束", type: "date", value: `${year}-12-31` },
      { name: "required_evidence", label: "必备佐证名称（每行一项）", type: "textarea", required: false },
      { name: "confirmed", label: "确认作为本校指标", type: "checkbox", value: true }, { name: "confirmation_note", label: "学校确认依据", type: "textarea" },
    ], values => {
      const { measure, required_evidence, ...rest } = values;
      return action("/assessment/indicators", { ...scope, ...rest, formula: measure === "count" ? "count" : measure === "sum" ? "sum" : "percentage", source_options: { measure }, required_evidence: lines(required_evidence), expected_version: record?.version || 0 });
    }, record ? { ...record, measure: record.source_options?.measure || "count", required_evidence: (record.required_evidence || []).join("\n") } : {});
  }
  function task(record) {
    open(record ? "修订年度任务" : "创建年度任务", [
      { name: "indicator_code", label: "关联指标", options: (w?.indicators || []).map(r => [r.code, `${r.code} ${r.name}`]) },
      { name: "title", label: "任务名称", maxLength: 200 }, { name: "owner_id", label: "责任账号", options: options(w?.owners || []) },
      { name: "due_date", label: "截止日期", type: "date" }, { name: "declared_progress", label: "申报进度（%）", type: "number", min: 0, max: 100, value: 0 },
      { name: "completed_on", label: "实际完成日期", type: "date", required: false }, { name: "manual_value", label: "人工特色项数值", type: "number", min: 0, step: "any", required: false },
      { name: "basis", label: "完成及人工数值依据", type: "textarea", required: false, max: 4000 },
    ], values => action(record ? `/assessment/tasks/${key(record.id)}` : "/assessment/tasks", { ...scope, ...values, completed_on: values.completed_on || null, ...(record ? { expected_revision: record.revision } : {}) }, record ? "PUT" : "POST"), record || {});
  }
  function evidence() {
    open("绑定文件版本", [{ name: "indicator_code", label: "关联指标", options: (w?.indicators || []).map(r => [r.code, r.name]) }, { name: "requirement_key", label: "对应佐证要求", maxLength: 100 }, { name: "doc_id", label: "授权文件", options: rows(docs.value).map(r => [r.doc_id, `${r.title} · 版本${r.content_revision}`]) }], values => action("/assessment/evidence", { ...scope, ...values }), {}, "只绑定已入库且当前有权读取的文件版本；内容变更后需要重新审核。");
  }
  async function exportRun(record) {
    try { downloadBlob(await request(`/assessment/runs/${key(record.id)}/export`, { method: "POST", download: true }), `考核目录-${year}.zip`); } catch (failure) { setError(failure); }
  }
  function policy() {
    open("确认归档与提醒参数", [{ name: "archive_enabled", label: "学校确认电子归档效力", type: "checkbox" }, { name: "reminder_advance_days", label: "提前提醒天数", type: "number", min: 0, max: 90, value: 14 }, { name: "confirmation_note", label: "学校确认依据", type: "textarea" }], values => action("/assessment/policy", { org_unit_id: orgId, ...values, expected_version: w?.policy?.version || 0, expected_archive_version: w?.policy?.archive_version || 0 }, "PUT"), w?.policy || {});
  }
  return <section className="panel workspace-panel"><PageHeader title="年度指标与组织考核" subtitle="指标版本、业务材料归集、独立人工审核与单独归档" action={<div className="inline-controls">{can("assessment.configure") && <button className="button secondary" onClick={policy} disabled={!w}>归档与提醒配置</button>}{can("assessment.manage") && <button className="button primary" disabled={!w} onClick={() => confirmAction("归集当前年度材料", "/assessment/recalculate", scope)}>归集材料</button>}</div>} />
    <div className="business-toolbar"><Select label="考核组织" value={orgId || ""} onChange={e => setOrg(e.target.value)}>{rows(organizations.value).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</Select><Select label="考核年度" value={year} onChange={e => setYear(Number(e.target.value))}>{Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - i).map(y => <option key={y}>{y}</option>)}</Select><button className="button secondary" onClick={workspace.reload}>刷新</button></div>
    <ResourceState resource={organizations} /><ResourceState resource={workspace} />{error && <ErrorBox error={error} />}
    <Tabs items={["指标与归集", "任务与佐证", "审核与归档", "年度计划与督办"]} active={tab} onChange={setTab} />
    {w && tab === "指标与归集" && <><div className="business-actions">{can("assessment.configure") && <button className="button primary" onClick={() => indicator()}>编制指标</button>}{w.needs_recalculation && <span className="muted">业务数据已变化，请重新归集</span>}</div><BusinessTable items={w.results} columns={[["指标", r => `${r.code} ${r.name}`], ["要求", r => r.requirement], ["实际 / 目标", r => `${r.actual ?? "待核验"} / ${r.target} ${r.unit}`], ["缺项", r => r.missing.join("；") || "—"], ["操作", r => <div className="inline-controls"><button className="text-button link" onClick={() => setDetail(r)}>查看来源与佐证</button>{can("assessment.configure") && <button className="text-button link" onClick={() => indicator(w.indicators.find(i => i.code === r.code))}>修订指标</button>}</div>]]} /></>}
    {w && tab === "任务与佐证" && <><div className="business-actions">{can("assessment.manage") && <><button className="button primary" onClick={() => task()}>创建任务</button><button className="button secondary" onClick={evidence}>绑定佐证</button></>}</div><BusinessTable items={w.tasks} columns={[["任务", r => r.title], ["责任人 / 期限", r => `${(w.owners.find(o => o.id === r.owner_id)?.name || r.owner_id)} · ${r.due_date}`], ["进度 / 版本", r => `${r.declared_progress}% · v${r.revision}`], ["审核", r => <Status value={r.review_status} />], ["操作", r => <div className="inline-controls">{can("assessment.manage") && <button className="text-button link" onClick={() => task(r)}>修订</button>}{reviewButton("tasks", r)}</div>]]} /><h3>佐证材料</h3><BusinessTable items={w.evidence} columns={[["佐证要求", r => r.requirement_key], ["关联文件 / 版本", r => `${r.doc_id} · ${r.content_revision ?? r.doc_version ?? "已锁定"}`], ["审核", r => <Status value={r.review_status} />], ["操作", r => reviewButton("evidence", r)]]} /></>}
    {w && tab === "审核与归档" && <BusinessTable items={w.runs} columns={[["归集时间 / 版本", r => `${formatBusinessTime(r.created_at)} · v${r.revision}`], ["审核状态", r => <><Status value={r.review_status} />{r.stale && <small className="cell-subtext">来源已变化，请重新归集后办理</small>}</>], ["处理意见", r => r.review_opinion || "—"], ["归档", r => r.archived_at ? formatBusinessTime(r.archived_at) : "未归档"], ["操作", r => <div className="inline-controls">{reviewButton("runs", r)}{r.review_status === "approved" && !r.stale && <>{can("assessment.manage") && !r.archived_at && <button className="text-button link" onClick={() => confirmAction("单独确认归档", `/assessment/runs/${key(r.id)}/archive`)}>归档</button>}{can("assessment.export") && <button className="text-button link" onClick={() => exportRun(r)}>导出目录</button>}</>}</div>]]} />}
    {w && tab === "年度计划与督办" && <><div className="business-actions">{can("assessment.manage") && <button className="button primary" onClick={() => open("年度计划草案", [{ name: "run_id", label: "归集依据版本", options: w.runs.map(r => [r.id, `${formatBusinessTime(r.created_at)} · v${r.revision}`]) }, { name: "content", label: "计划内容", type: "textarea", max: 30000, rows: 10 }], values => action("/assessment/plans", { ...values, expected_version: w.plan?.version || 0 }), { content: w.plan?.content || "" })}>编制 / 修订计划</button>}<button className="button secondary" onClick={() => confirmAction("扫描年度任务提醒", "/assessment/reminders/sync", scope)}>扫描提醒</button></div>{w.plan && <article><RecordTrace record={w.plan} /><p className="business-content">{w.plan.content}</p>{reviewButton("plans", w.plan)}</article>}<BusinessTable items={w.reminders} columns={[["提醒", r => r.message || r.title || r.kind], ["处理状态", r => r.handled_at ? "已处理" : "待处理"], ["处理意见", r => r.handle_note || "—"], ["操作", r => !r.handled_at && <button className="text-button link" onClick={() => open("登记督办处理结果", [{ name: "note", label: "处理记录", type: "textarea" }], values => action(`/assessment/reminders/${key(r.id)}/handle`, values))}>办理</button>]]} /></>}
    {detail && <Modal title="指标来源与佐证" wide flat onClose={() => setDetail(null)}><h3>{detail.name}</h3><p>{detail.requirement}</p><p>规则版本：{detail.rule_version}；统计期间：{detail.period_start} 至 {detail.period_end}</p><BusinessTable items={detail.sources || []} columns={[["来源", r => r.title || r.name || r.record_id || r.id], ["业务类型", r => r.source || r.kind || detail.source], ["事实依据", r => r.reason || r.note || r.status || "当前授权业务记录"]]} /><p>{detail.missing.join("；")}</p></Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
