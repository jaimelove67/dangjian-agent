import { useRef, useState } from "react";
import { Plus, FileText } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { accountOrganizations } from "../roles";
import { newAudit } from "../role-data";
import { saveDemoFile } from "../demo-files";
import { formatBusinessTime } from "../business-time";
import { canReadDemoPublication, publicationFileOwner, publicationToday, seedPublications, validatePublicationDraft } from "../publications";
import { Empty, Modal, PageHeader, SearchInput, Select } from "../components";
import { BusinessForm, BusinessTable, Status } from "./BusinessForms";

export function DemoPublicationManager() {
  const { session } = useApp(), { data, update, notify } = useStore();
  const identity = `${session.user.tenant_id}:${session.user.id}:${session.user.role}`;
  const identityRef = useRef(identity); identityRef.current = identity;
  const [query, setQuery] = useState(""), [status, setStatus] = useState(""), [selected, setSelected] = useState(null), [form, setForm] = useState(null);
  const user = session.user;
  if (IS_LIVE || user.role !== "school_admin") return <Empty title="当前账号无公示发布管理权限" description="请联系学校管理员办理公示发布。" />;
  const organizations = user.tenant_id === "school-1" ? accountOrganizations() : [{ id: user.tenant_id, name: data.tenants.find((t) => t.id === user.tenant_id)?.name || "本校", org_type: "school" }];
  const records = [...new Map([...seedPublications(), ...(data.publications || [])].map((record) => [record.id, record])).values()].filter((record) => record.kind === "notice" && canReadDemoPublication(user, record));
  const visible = records.filter((record) => (!status || record.status === status) && (!query.trim() || `${record.title} ${record.body.issuer || ""} ${record.body.organization_name || ""}`.includes(query.trim()))).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const detail = records.find((record) => record.id === selected);
  const checkIdentity = () => { if (identityRef.current !== identity) throw new Error("当前账号已变更，请重新打开发布管理。"); };
  const audit = (action, id) => update("auditEntries", (previous = []) => [newAudit(user, action, "school_notice", id), ...previous]);
  const persist = (record) => update("publications", (previous = []) => [record, ...previous.filter((item) => item.id !== record.id)]);
  function create() {
    setForm({ identity, title: "编制公示或通知草稿", submitLabel: "保存草稿", description: "先核对正文、接收组织及附件，保存草稿后再单独确认发布。公示事项须填写完整的公示起止日期。", fields: [
      { name: "category", label: "信息类型", options: [["notice", "通知公告"], ["publicity", "公示事项"]], value: "notice" },
      { name: "org_unit_id", label: "接收组织及其下属", options: organizations.map((org) => [org.id, org.name]), value: user.tenant_id },
      { name: "title", label: "标题", maxLength: 200 },
      { name: "content", label: "正文", type: "textarea", max: 10000, rows: 7 },
      { name: "starts_on", label: "展示开始日期（公示必填）", type: "date", required: false, value: publicationToday() },
      { name: "expires_on", label: "展示截至日期（公示必填）", type: "date", required: false },
      { name: "file", label: "附件原件（可选，PDF、DOCX或TXT，10MB以内）", type: "file", required: false, accept: ".pdf,.docx,.txt" },
    ], submit: async (values) => {
      checkIdentity();
      const fields = validatePublicationDraft(values, organizations.map((org) => org.id));
      const id = crypto.randomUUID(), time = new Date().toISOString(), organization = organizations.find((org) => org.id === fields.org_unit_id);
      const record = { id, kind: "notice", tenant_id: user.tenant_id, org_unit_id: fields.org_unit_id, title: fields.title, status: "draft", revision: 1, created_by: user.id, created_at: time, updated_at: time, body: { category: fields.category, content: fields.content, starts_on: fields.starts_on, expires_on: fields.expires_on, organization_name: organization.name, issuer: organizations.find((org) => org.id === user.org_unit_id)?.name || organizations[0].name, evidence: [] }, history: [{ action: "保存草稿", revision: 1, actor: user.name, created_at: time, reason: "编制公示或通知草稿" }] };
      const file = values.file;
      if (file?.name) {
        if (!file.size) throw new Error("附件为空，请选择包含内容的原件。");
        if (file.size > 10 * 1024 * 1024 || !/\.(pdf|docx|txt)$/i.test(file.name)) throw new Error("附件仅支持10MB以内的PDF、DOCX或TXT文件。");
        const fileId = crypto.randomUUID(), owner = publicationFileOwner(record);
        await saveDemoFile(fileId, owner, file);
        checkIdentity();
        record.body.evidence = [{ local_file_id: fileId, local_owner_id: owner, has_file: true, doc_id: `publication-${id}`, revision: 1, title: file.name, file_name: file.name }];
      }
      checkIdentity(); persist(record); audit("保存公示通知草稿", id); setSelected(id); notify("草稿已保存，请核对后确认发布。");
    } });
  }
  function publish(record) {
    setForm({ identity, title: "确认发布公示或通知", submitLabel: "确认发布", description: `发布后，${record.body.organization_name || "接收组织"}及其下属的授权用户可在首页查阅。`, fields: [
      { name: "reason", label: "发布依据与说明", type: "textarea", max: 2000 },
      { name: "confirmed", label: "已核对正文、接收范围、公示期限及附件", type: "checkbox" },
    ], submit: (values) => {
      checkIdentity();
      if (!values.confirmed) throw new Error("请先确认已核对发布内容与接收范围。");
      const current = records.find((r) => r.id === record.id);
      if (!current || current.status !== "draft" || current.revision !== record.revision || current.tenant_id !== user.tenant_id) throw new Error("记录状态已变更，请刷新后核对。");
      validatePublicationDraft({ ...current.body, title: current.title, org_unit_id: current.org_unit_id }, organizations.map((org) => org.id));
      const time = new Date().toISOString();
      persist({ ...current, status: "published", revision: current.revision + 1, published_at: time, updated_at: time, history: [...current.history, { action: "确认发布", revision: current.revision + 1, actor: user.name, created_at: time, reason: String(values.reason || "").trim() }] });
      audit("发布公示通知", current.id); notify("信息已发布，将按接收范围与展示期限呈现。");
    } });
  }
  return <section className="panel workspace-panel"><PageHeader title="公示公告发布管理" subtitle="编制校内公示与通知，按组织范围发布并保留办理记录" action={<button className="button primary" onClick={create}><Plus size={17} />编制信息</button>} />
    <div className="table-toolbar"><SearchInput placeholder="搜索标题、发布单位或接收组织" value={query} onChange={(e) => setQuery(e.target.value)} /><Select label="发布状态" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">全部状态</option><option value="draft">草稿</option><option value="published">已发布</option></Select></div>
    <BusinessTable items={visible} columns={[["信息标题", (r) => <strong>{r.title}</strong>], ["类型", (r) => r.body.category === "publicity" ? "公示事项" : "通知公告"], ["接收范围", (r) => r.body.organization_name || organizations.find((o) => o.id === r.org_unit_id)?.name || "所属组织"], ["展示期限", (r) => `${r.body.starts_on || "发布后"} 至 ${r.body.expires_on || "长期展示"}`], ["状态", (r) => <Status value={r.status} />], ["操作", (r) => <button className="text-button link" onClick={() => setSelected(r.id)}>查看与办理</button>]]} />
    {detail && !form && <Modal title="公示公告记录" wide flat onClose={() => setSelected(null)}><h2>{detail.title}</h2><Status value={detail.status} /><dl className="detail-list"><dt>发布单位</dt><dd>{detail.body.issuer || "学校党组织"}</dd><dt>接收范围</dt><dd>{detail.body.organization_name || organizations.find((o) => o.id === detail.org_unit_id)?.name || "所属组织"}</dd><dt>开始日期</dt><dd>{detail.body.starts_on || "发布后"}</dd><dt>截至日期</dt><dd>{detail.body.expires_on || "长期展示"}</dd></dl><p className="business-content">{detail.body.content}</p>{detail.body.evidence?.map((file) => <p className="body-copy" key={file.local_file_id || file.doc_id}><FileText size={16} /> {file.file_name || file.title} · 版本{file.revision || 1}</p>)}{detail.status === "draft" && <div className="business-actions"><button className="button primary" onClick={() => publish(detail)}>确认发布</button></div>}<BusinessTable items={detail.history || []} empty="此前记录未登记办理历史" columns={[["版本", (r) => r.revision], ["操作", (r) => r.action], ["办理人", (r) => r.actor], ["说明", (r) => r.reason], ["时间", (r) => formatBusinessTime(r.created_at)]]} /></Modal>}
    {form?.identity === identity && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
