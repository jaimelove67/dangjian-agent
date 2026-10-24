import { formatBusinessTime } from "../business-time";
import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { ROLE_INFO, hasPermission } from "../roles";
import { PageHeader, Tabs, Modal, ErrorBox, downloadBlob } from "../components";
import { request } from "../api";
import { get, send, key, rows } from "../business-api";
import { BusinessForm, BusinessTable, RecordTrace, ResourceState, Status, options, useResource } from "../components/BusinessForms";

export function LiveSchoolBusiness({ mode = "tasks", tenantId, category }) {
  const { session } = useApp(), { notify } = useStore();
  const school = session.user.role === "school_admin", platform = session.user.role === "system_admin";
  const [tab, setTab] = useState("任务办理"), [onlyOverdue, setOnlyOverdue] = useState(false), [selected, setSelected] = useState(null), [form, setForm] = useState(null), [error, setError] = useState(null);
  const kind = mode === "notices" ? "notice" : mode === "permissions" ? "permission" : "task";
  const resource = useResource(() => mode === "rules" ? get("/school/business/rules") : get("/school/business/records", { kind, tenant_id: tenantId }), [mode, kind, tenantId]);
  const notices = useResource(() => mode === "personal" ? get("/school/business/records", { kind: "notice" }) : Promise.resolve(null), [mode]);
  const detail = useResource(() => selected ? get(`/school/business/records/${key(selected)}`) : Promise.resolve(null), [selected]);
  const orgs = useResource(() => school ? get("/admin/org-units") : Promise.resolve([]), [school]);
  const users = useResource(() => school ? get("/admin/users") : Promise.resolve([]), [school]);
  const docs = useResource(() => hasPermission(session, "knowledge.query") ? get("/knowledge-docs", { page_size: 100 }) : Promise.resolve(null), []);
  const materials = useResource(() => ["member", "applicant"].includes(session.user.role) ? get("/member/self/materials", { page_size: 100 }) : Promise.resolve(null), []);
  const d = detail.value;
  async function downloadEvidence(evidence, personal = false) {
    try {
      const own = ["member", "applicant"].includes(session.user.role);
      const endpoint = personal ? own ? `/member/self/materials/${key(evidence.id)}/file` : `/member/roster/${key(evidence.profile_id)}/materials/${key(evidence.id)}/file` : `/knowledge-docs/${key(evidence.doc_id)}/file?revision=${evidence.revision}`;
      downloadBlob(await request(endpoint, { download: true }), evidence.file_name || evidence.title || "佐证原件");
    } catch (failure) { setError(failure); }
  }
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, submit, initial, description }); }
  async function save(path, values, method = "POST") { const result = await send(path, values, method); resource.reload(); detail.reload(); notices.reload(); notify("业务记录已保存"); return result; }
  const note = { name: "reason", label: "办理依据与处理说明", type: "textarea" };
  function create() {
    if (kind === "notice") open("编制校内通知草稿", [{ name: "org_unit_id", label: "接收组织及其下属", options: options(rows(orgs.value)) }, { name: "title", label: "通知标题", maxLength: 200 }, { name: "content", label: "通知正文", type: "textarea", max: 10000, rows: 8 }, { name: "expires_on", label: "展示截至日期（可留空）", type: "date", required: false }], values => save("/school/business/notices", { ...values, expires_on: values.expires_on || null }));
    else if (kind === "permission") open("提交本校业务角色申请", [
      { name: "user_id", label: "本校账号", options: rows(users.value).map(u => [u.id, `${u.name} · ${u.username}`]) },
      { name: "role", label: "申请的业务角色", options: Object.entries(ROLE_INFO).filter(([id]) => id !== "system_admin").map(([id, r]) => [id, r.label]) },
      { name: "org_unit_id", label: "申请组织范围", options: options(rows(orgs.value)) }, note,
    ], values => save("/school/business/permission-requests", values), {}, "提交申请后权限保持当前状态。平台批准时校验角色与组织类型、本校边界和本人档案关联，并使旧登录会话失效。");
    else open("布置业务任务与督办要求", [
      { name: "title", label: "任务名称", maxLength: 200 }, { name: "category", label: "所属业务", options: [["learning", "学习教育"], ["development", "党员发展"], ["life", "组织生活"], ["assessment", "考核统计"], ["other", "其他业务"]], value: category || "learning" },
      { name: "org_unit_id", label: "责任组织", options: options(rows(orgs.value)) }, { name: "assignee_id", label: "责任账号（须属于所选组织）", options: rows(users.value).filter(u => u.is_active).map(u => [u.id, `${u.name} · ${rows(orgs.value).find(o => o.id === u.org_unit_id)?.name || "未关联"}`]) },
      { name: "due_date", label: "任务截止日期", type: "date" }, { name: "requirements", label: "任务、材料与完成要求", type: "textarea", max: 4000 }, { name: "evidence_required", label: "完成时必须提供真实文件佐证", type: "checkbox", value: true },
    ], values => save("/school/business/tasks", values), {}, "先保存草稿，再单独确认下发。责任人提交完成记录，由学校或院系的其他账号核验，审核后再确认归档。");
  }
  function recordAction(action) {
    const fields = [note];
    if (action === "review") fields.unshift({ name: "decision", label: "审核结果", options: [["approved", "通过"], ["rejected", "退回补充"]] });
    if (action === "complete") fields.unshift({ name: "report", label: "实际完成情况", type: "textarea", max: 10000 }, { name: "doc_ids", label: "授权制度 / 佐证（多选）", type: "multi", required: false, options: rows(docs.value).map(r => [r.doc_id, r.title]) }, { name: "material_ids", label: "本人已上传原件（多选）", type: "multi", required: false, options: rows(materials.value).map(r => [r.id, `${r.title} · ${r.file_name}`]) });
    open({ publish: d.kind === "notice" ? "确认发布校内通知" : "确认下发业务任务", complete: "提交任务完成记录", review: "审核当前业务版本", archive: "单独确认任务归档" }[action], fields, values => save(`/school/business/records/${key(d.id)}/${action}`, { ...values, expected_revision: d.revision }));
  }
  function rules() { const current = resource.value; open("维护学校业务参数", [
    { name: "year", label: "当前业务年度", type: "number", min: 2000, max: 2100 }, { name: "review_days", label: "建议审核时限（天）", type: "number", min: 1, max: 60 }, { name: "reminder_days", label: "截止前提醒（天）", type: "number", min: 0, max: 60 },
    { name: "development_materials", label: "党员发展材料要求", type: "textarea" }, { name: "archive_requirements", label: "学校归档确认要求", type: "textarea" }, note,
  ], values => save("/school/business/rules", { ...values, expected_revision: current.revision }, "PUT"), current, "参数用于本校任务提醒与办理指引。阶段流转的法定要求和角色权限仍由相应业务规则校验。"); }
  const all = rows(resource.value).filter(r => (!category || r.body.category === category) && (!onlyOverdue || r.overdue));
  const records = mode === "personal" && tab === "通知公告" ? rows(notices.value) : all;
  return <section className="panel workspace-panel"><PageHeader title={{ tasks: category === "learning" ? "支部学习任务" : "问题与督办", personal: "通知与我的任务", notices: "校内通知公告", permissions: "业务角色申请", rules: "学校业务参数" }[mode]} subtitle="所有记录来自本校服务，保留材料版本、办理人及处理意见" action={school && (mode === "rules" ? <button className="button primary" disabled={!resource.value} onClick={rules}>修订学校参数</button> : <button className="button primary" onClick={create}>{kind === "notice" ? "编制通知" : kind === "permission" ? "提交业务申请" : "布置任务"}</button>)} />
    {mode === "personal" && <Tabs items={["任务办理", "通知公告"]} active={tab} onChange={setTab} />}
    <div className="business-toolbar">{kind === "task" && tab !== "通知公告" && <label><input type="checkbox" checked={onlyOverdue} onChange={e => setOnlyOverdue(e.target.checked)} /> 仅看逾期未完成</label>}<button className="button secondary" onClick={() => { resource.reload(); notices.reload(); }}>刷新</button></div>
    <ResourceState resource={resource} />
    {mode === "rules" ? resource.value && <><p>当前版本 v{resource.value.revision} · {resource.value.year} 年度</p><dl className="detail-list"><dt>建议审核时限</dt><dd>{resource.value.review_days}天</dd><dt>截止前提醒</dt><dd>{resource.value.reminder_days}天</dd><dt>发展材料要求</dt><dd>{resource.value.development_materials}</dd><dt>归档要求</dt><dd>{resource.value.archive_requirements}</dd><dt>维护人</dt><dd>{resource.value.updated_by || "采用初始办理指引"}</dd></dl></> : <BusinessTable items={records} columns={[["业务事项", r => r.title], ["要求 / 原因", r => r.body.requirements || r.body.reason || r.body.content?.slice(0, 100)], ["期限", r => r.body.due_date || r.body.expires_on || "—"], ["状态", r => <><Status value={r.status} />{r.overdue && <span className="cell-subtext">已逾期</span>}</>], ["操作", r => <button className="text-button link" onClick={() => setSelected(r.id)}>查看与办理</button>]]} />}
    {selected && <Modal title="业务记录与办理" wide flat onClose={() => setSelected(null)}><ResourceState resource={detail} />{d && <><h3>{d.title}</h3><Status value={d.status} /><RecordTrace record={d} />{error && <ErrorBox error={error} />}<p className="business-content">{d.body.content || d.body.requirements || d.body.reason}</p>{d.body.role && <p>目标角色：{ROLE_INFO[d.body.role]?.label}；组织：{d.body.org_unit_id}；目标账号：{d.body.user_id}</p>}{d.body.report && <p className="business-content">完成情况：{d.body.report}</p>}{d.body.evidence?.map(e => <p key={e.doc_id}>佐证：{e.title}（版本{e.revision}） <button className="text-button link" onClick={() => downloadEvidence(e)}>下载该版本</button></p>)}{d.body.materials?.map(e => <p key={e.id}>本人原件：{e.title}（{e.file_version}） <button className="text-button link" onClick={() => downloadEvidence(e, true)}>下载原件</button></p>)}
      <div className="business-actions">{school && d.status === "draft" && <button className="button primary" onClick={() => recordAction("publish")}>{d.kind === "notice" ? "确认发布" : "确认下发"}</button>}{d.kind === "task" && ["assigned", "rejected"].includes(d.status) && d.body.assignee_id === session.user.id && <button className="button primary" onClick={() => recordAction("complete")}>提交完成记录</button>}{d.status === "pending" && d.submitted_by !== session.user.id && (d.kind === "permission" ? platform : ["school_admin", "department_admin"].includes(session.user.role)) && <button className="button primary" onClick={() => recordAction("review")}>人工核验</button>}{school && d.kind === "task" && d.status === "approved" && <button className="button primary" onClick={() => recordAction("archive")}>确认归档</button>}</div>
      <BusinessTable items={d.history || []} columns={[["版本", r => r.revision], ["操作", r => r.action], ["办理人", r => r.actor_id], ["处理说明", r => r.reason], ["时间", r => formatBusinessTime(r.created_at)]]} /></>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
