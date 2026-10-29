import { formatBusinessTime } from "../business-time";
import { useEffect, useRef, useState } from "react";
import { Badge, Empty, ErrorBox, Field, Loading, Modal } from "../components";
import "../business.css";

export function useResource(load, dependencies = []) {
  const [state, setState] = useState({ value: null, loading: true, error: null });
  const [revision, setRevision] = useState(0);
  const previousKey = useRef(null);
  useEffect(() => {
    let active = true;
    const key = JSON.stringify(dependencies), sameScope = previousKey.current === key;
    previousKey.current = key;
    setState(previous => ({ value: sameScope ? previous.value : null, loading: true, error: null }));
    Promise.resolve().then(load).then(value => { if (active) setState({ value, loading: false, error: null }); })
      .catch(error => { if (active) setState({ value: null, loading: false, error }); });
    return () => { active = false; };
  }, [...dependencies, revision]);
  return { ...state, reload: () => setRevision(n => n + 1) };
}
export const options = (items, label = "name") => items.map(item => [item.id, item[label] || item.title || item.id]);
export const lines = (value) => String(value || "").split(/\r?\n/).map(s => s.trim()).filter(Boolean);
export const statusText = { recorded: "已登记", held: "已开展", draft: "草稿", pending: "待审核", approved: "已通过", rejected: "已退回", returned: "已退回", archived: "已归档", published: "已发布", settled: "已办结", revoked: "已作废", completed: "已完成", planned: "待开展", assigned: "已下发", enrolled: "已报名 / 学习中", cancelled: "已取消", succeeded: "已完成", failed: "失败", running: "处理中", queued: "等待执行", submitted: "待批复", not_started: "未发起" };
export function Status({ value }) { return <Badge tone={["approved", "archived", "completed", "published", "settled"].includes(value) ? "green" : ["rejected", "returned", "revoked"].includes(value) ? "red" : "orange"}>{statusText[value] || value || "待办理"}</Badge>; }
export function ResourceState({ resource }) { return resource.loading ? <Loading /> : resource.error ? <ErrorBox error={resource.error} retry={resource.reload} /> : null; }

export function BusinessToolbar({ children, actions }) {
  if (!children && !actions) return null;
  return <div className="business-toolbar business-toolbar-grouped">
    {children && <div className="business-toolbar-context">{children}</div>}
    {actions && <div className="business-toolbar-actions">{actions}</div>}
  </div>;
}

// 「可多选」统一渲染成带筛选的勾选面板：原生 select[multiple] 要按住 Ctrl 点选，
// 在人员名单、制度依据这种长列表上既看不清也没法核对，勾选 + 关键字筛选才可操作。
export function MultiSelect({ name, options, value, onChange, filterFrom = 8 }) {
  const [query, setQuery] = useState("");
  const selected = Array.isArray(value) ? value : [];
  const keyword = query.trim().toLowerCase();
  // 筛选掉的项只是隐藏、不卸载：DOM 一旦移除，已勾选的值就不会随表单提交。
  const hidden = new Set(
    keyword
      ? options.filter(([id, text]) => !`${text} ${id}`.toLowerCase().includes(keyword)).map(([id]) => id)
      : [],
  );
  const toggle = id => onChange(selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id]);
  return <div className="multi-select">
    {options.length > filterFrom && <input type="text" className="multi-search" value={query} onChange={e => setQuery(e.target.value)} placeholder={`输入关键字筛选 ${options.length} 项`} aria-label={`筛选${name}`} />}
    <div className="multi-options">
      {options.map(([id, text]) => <span className={`multi-option${selected.includes(id) ? " selected" : ""}${hidden.has(id) ? " hidden" : ""}`} key={id}>
        <input type="checkbox" name={name} value={id} checked={selected.includes(id)} aria-label={text} onChange={() => toggle(id)} />
        <span onClick={() => toggle(id)}>{text}</span>
      </span>)}
      {hidden.size === options.length && <span className="multi-empty">没有匹配的选项</span>}
    </div>
    <div className="multi-footer"><span>共 {options.length} 项，已选 {selected.length} 项</span><span className="multi-actions">
      <button type="button" className="text-button" disabled={selected.length === options.length} onClick={() => onChange(options.map(([id]) => id))}>全选</button>
      <button type="button" className="text-button" disabled={!selected.length} onClick={() => onChange([])}>清空</button>
    </span></div>
  </div>;
}

// Field definitions contain labels and domain choices; the server always validates authorization and versions.
// suggest（可选）：{ fileField, run(file), apply(result) } —— 选择文件后调用识别接口，
// 只把建议值填进空白项或仍是默认值的项，人工填写过的内容一律保留。
// generate（可选）：{ label, run(values), note } —— 点按钮时按系统里已有的记录汇总成草稿
// 填回该文本框；生成的内容始终可改，也不替人做出结论。
export function BusinessForm({ title, fields, initial = {}, onSubmit, onClose, description, submitLabel = "确认保存", suggest }) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  const [assembling, setAssembling] = useState(null);
  const [values, setValues] = useState(() => Object.fromEntries(fields.map(f => [f.name, f.type === "checkbox" ? !!(initial[f.name] ?? f.value) : f.type === "multi" ? (initial[f.name] ?? f.value ?? []) : initial[f.name] ?? f.value ?? ""])));
  const [suggesting, setSuggesting] = useState(false), [note, setNote] = useState(null);
  const labels = Object.fromEntries(fields.map(f => [f.name, f.label]));
  const defaults = Object.fromEntries(fields.map(f => [f.name, f.type === "checkbox" ? !!(f.value) : f.type === "multi" ? (f.value ?? []) : f.value ?? ""]));
  function setValue(name, value) { setValues(v => ({ ...v, [name]: value })); }
  async function pickFile(field, file) {
    if (!suggest || field.name !== suggest.fileField) return;
    if (!file) { setNote(null); return; }
    setSuggesting(true); setNote(null);
    try {
      const result = await suggest.run(file);
      const patches = suggest.apply(result) || {};
      const next = { ...values }, filled = [];
      for (const [name, value] of Object.entries(patches)) {
        const label = labels[name] || name;
        if (value == null || value === "" || (Array.isArray(value) && !value.length)) continue;
        const current = values[name];
        if (current === "" || current == null || current === defaults[name]) { next[name] = value; filled.push(label); }
      }
      setValues(next);
      const missing = (result.missing_fields || []).map(k => labels[k] || k).filter(k => !filled.includes(k));
      const parts = [];
      parts.push(filled.length ? `已按文件内容预填：${filled.join("、")}。` : "未能从文件内容中识别出可预填的字段。");
      if (missing.length) parts.push(`以下字段未识别到，请人工填写：${missing.join("、")}。`);
      if (result.truncated) parts.push("文件较长，识别仅基于正文开头部分。");
      setNote({ tone: filled.length ? "info" : "warn", text: parts.join("") });
    } catch (failure) {
      setNote({ tone: "warn", text: `${failure?.message || "文件信息识别失败"}。你仍可手动填写表单完成提交。` });
    } finally { setSuggesting(false); }
  }
  async function assemble(field) {
    if (assembling) return;
    setAssembling(field.name); setError(null); setNote(null);
    try {
      const text = String((await field.generate.run(values)) || "").trim();
      if (!text) throw new Error("没有可汇总的记录");
      setValue(field.name, text);
      setNote({ tone: "info", text: field.generate.note || "已按系统现有记录生成依据草稿，请核对并补充后提交。" });
    } catch (failure) {
      setNote({ tone: "warn", text: `${failure?.message || "未能汇总现有记录"}。你仍可手动填写这项内容。` });
    } finally { setAssembling(null); }
  }
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget), values = {};
    for (const field of fields) {
      const raw = field.type === "multi" ? form.getAll(field.name) : form.get(field.name);
      values[field.name] = field.type === "checkbox" ? form.has(field.name) : field.type === "number" ? raw === "" ? null : Number(raw) : raw;
    }
    setBusy(true); setError(null);
    try { await onSubmit(values); onClose(); } catch (failure) { setError(failure); } finally { setBusy(false); }
  }
  return <Modal title={title} wide flat onClose={() => { if (!busy) onClose(); }}>
    {description && <p className="body-copy">{description}</p>}
    {error && <ErrorBox error={error} />}
    {suggesting && <p className="inline-note">正在读取文件内容并识别字段信息，请稍候…</p>}
    {note && <p className="inline-note" role={note.tone === "warn" ? "alert" : undefined}>{note.text}</p>}
    <form onSubmit={submit} className="business-form"><fieldset disabled={busy}><div className="form-grid">
      {fields.map(field => field.type === "multi" ? <div className="field full" key={field.name}>
        <span>{field.required !== false && <b>*</b>}{field.label}</span>
        <MultiSelect name={field.name} options={field.options} value={values[field.name] ?? []} onChange={next => setValue(field.name, next)} />
        {field.help && <small className="muted">{field.help}</small>}
      </div> : <Field key={field.name} label={field.label} required={field.required !== false} full={field.full || ["textarea", "file"].includes(field.type)}>
        {field.type === "textarea" ? <>
          <textarea name={field.name} rows={field.rows || 3} required={field.required !== false} maxLength={field.max || 2000} value={values[field.name] ?? ""} onChange={e => setValue(field.name, e.target.value)} placeholder={field.placeholder} />
          {field.generate && <span className="generate-row"><button type="button" className="text-button" disabled={!!assembling} onClick={event => { event.preventDefault(); assemble(field); }}>{assembling === field.name ? "正在汇总现有记录…" : (values[field.name] ? field.generate.relabel : null) || field.generate.label || "按现有记录生成"}</button></span>}
        </>
          : field.options ? <select name={field.name} required={field.required !== false} value={values[field.name] ?? ""} onChange={e => setValue(field.name, e.target.value)}>
            <option value="">请选择</option>{field.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select> : <input name={field.name} type={field.type || "text"} required={field.required !== false && field.type !== "checkbox"} checked={field.type === "checkbox" ? !!values[field.name] : undefined} value={field.type === "file" || field.type === "checkbox" ? undefined : values[field.name] ?? ""} onChange={field.type === "file" ? e => pickFile(field, e.target.files?.[0]) : e => setValue(field.name, e.target.value)} min={field.min} max={field.max} maxLength={field.maxLength || 300} step={field.step} accept={field.accept} />}
        {field.help && <small className="muted">{field.help}</small>}
      </Field>)}
    </div></fieldset><div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? "正在提交…" : submitLabel}</button></div></form>
  </Modal>;
}
export function RecordTrace({ record }) {
  return <dl className="detail-list">
    <dt>记录编号 / 版本</dt><dd>{record.id} / {record.revision ?? record.version ?? record.content_revision ?? 1}</dd>
    <dt>提交人</dt><dd>{record.submitted_by || record.created_by || record.submitter_id || record.uploaded_by || record.history?.[0]?.actor_id || "未记录提交人"}</dd>
    {("review_status" in record || "reviewed_by" in record) && <><dt>审核人</dt><dd>{record.reviewed_by || record.reviewer_id || "尚未审核"}</dd><dt>处理意见</dt><dd>{record.review_comment || record.review_opinion || record.review_note || record.opinion || "—"}</dd></>}
    {"archived_at" in record && <><dt>归档状态</dt><dd>{record.archived_at ? `已归档 · ${formatBusinessTime(record.archived_at)}` : "尚未归档"}</dd></>}
  </dl>;
}
export function BusinessTable({ columns, items, empty = "暂无业务记录" }) {
  return <div className="table-scroll"><table><thead><tr>{columns.map(([title]) => <th key={title}>{title}</th>)}</tr></thead><tbody>{items.map((item, index) => <tr key={item.id || item.code || item.profile_id || index}>{columns.map(([title, render]) => <td key={title}>{render(item)}</td>)}</tr>)}</tbody></table>{!items.length && <Empty title={empty} />}</div>;
}
