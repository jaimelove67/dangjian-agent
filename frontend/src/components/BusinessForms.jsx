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

// Field definitions contain labels and domain choices; the server always validates authorization and versions.
export function BusinessForm({ title, fields, initial = {}, onSubmit, onClose, description, submitLabel = "确认保存" }) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
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
    <form onSubmit={submit} className="business-form"><fieldset disabled={busy}><div className="form-grid">
      {fields.map(field => <Field key={field.name} label={field.label} required={field.required !== false} full={field.full || ["textarea", "multi", "file"].includes(field.type)}>
        {field.type === "textarea" ? <textarea name={field.name} rows={field.rows || 3} required={field.required !== false} maxLength={field.max || 2000} defaultValue={initial[field.name] ?? field.value ?? ""} placeholder={field.placeholder} />
          : field.options ? <select name={field.name} multiple={field.type === "multi"} required={field.required !== false} defaultValue={initial[field.name] ?? field.value ?? (field.type === "multi" ? [] : "")}>
            {field.type !== "multi" && <option value="">请选择</option>}{field.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select> : <input name={field.name} type={field.type || "text"} required={field.required !== false && field.type !== "checkbox"} defaultValue={field.type === "file" ? undefined : initial[field.name] ?? field.value ?? ""} defaultChecked={field.type === "checkbox" ? !!(initial[field.name] ?? field.value) : undefined} min={field.min} max={field.max} maxLength={field.maxLength || 300} step={field.step} accept={field.accept} />}
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
