import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { ROLE_INFO } from "../roles";
import { passwordService } from "../password-security";
import { usePasswordState } from "../password-hooks";
import { Badge, Empty, ErrorBox, Field, Modal, Select } from "../components";
import { PASSWORD_STATUS, passwordTime } from "./PasswordSecurity";
import "../password-security.css";

export function PasswordRequests({ tenantId, query = "" }) {
  const { session } = useApp();
  const { notify, data } = useStore();
  const state = usePasswordState(session.user, { admin: true, tenantId });
  const [filter, setFilter] = useState("pending");
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const tenant = data.tenants.find((item) => item.id === tenantId);
  const rows = (state.requests || []).filter((item) => (!filter || item.status === filter) && (!query || `${item.name} ${item.username}`.includes(query)));
  async function review(event) {
    event.preventDefault();
    if (busy) return;
    const fields = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await passwordService().review(session.user, selected.id, tenantId, fields.get("decision"), fields.get("comment"), selected.version);
      notify(fields.get("decision") === "approved" ? "已批准，申请人可再修改一次密码。" : "已驳回改密申请，处理意见已保留。");
      setSelected(null);
    } catch (failure) { setError(failure); }
    finally { setBusy(false); }
  }
  return <div className="password-requests">
    <div className="password-requests-heading"><div><strong>再次修改密码申请</strong><p>首次自主修改后，每次再次修改均需审批；每次批准仅授权一次。</p></div><Select label="改密申请状态" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="pending">待审核</option><option value="">全部状态</option>{Object.entries(PASSWORD_STATUS).filter(([id]) => id !== "pending").map(([id, label]) => <option key={id} value={id}>{label}</option>)}</Select></div>
    {state.error && <ErrorBox error={state.error} />}
    {!state.error && <div className="table-scroll"><table><thead><tr>{["申请人 / 账号", "角色", "申请原因", "提交时间", "状态", "处理结果", "操作"].map((title) => <th key={title}>{title}</th>)}</tr></thead><tbody>{rows.map((request) => <tr key={request.id}><td><strong>{request.name}</strong><small className="cell-subtext">{request.username}</small></td><td>{ROLE_INFO[request.role]?.label || request.role}</td><td className="password-reason-cell">{request.reason}</td><td>{passwordTime(request.created_at)}</td><td><Badge tone={request.status === "pending" ? "orange" : request.status === "rejected" ? "red" : "green"}>{PASSWORD_STATUS[request.status]}</Badge></td><td className="password-reason-cell">{request.review_comment || "等待处理"}{request.reviewer_name && <small className="cell-subtext">{request.reviewer_name} · {passwordTime(request.reviewed_at)}</small>}</td><td>{request.status === "pending" ? <button className="text-button link" disabled={!IS_LIVE && (!tenant || tenant.is_active === false)} onClick={() => { setError(null); setSelected(request); }}>审核申请</button> : <span className="muted">{request.status === "consumed" ? "授权已使用" : "—"}</span>}</td></tr>)}</tbody></table>{!rows.length && <Empty title={filter === "pending" ? "暂无待审核改密申请" : "暂无符合条件的改密申请"} description="仅展示当前管理租户的申请，切换学校或状态可查看其他记录。" />}</div>}
    {selected && <Modal title="审核改密申请" className="password-dialog" onClose={() => { if (!busy) setSelected(null); }}>
      <dl className="detail-list"><dt>申请人</dt><dd>{selected.name}（{selected.username}）</dd><dt>申请时间</dt><dd>{passwordTime(selected.created_at)}</dd><dt>申请原因</dt><dd>{selected.reason}</dd></dl>
      <p className="password-help">批准后由申请人自行输入新密码，仅可修改一次。审批不恢复首次自主修改机会。</p>
      {error && <ErrorBox error={error} />}
      <form onSubmit={review} className="password-form"><Field label="处理结果" required full><select name="decision" defaultValue="approved" disabled={busy}><option value="approved">批准一次修改</option><option value="rejected">驳回申请</option></select></Field><Field label="处理意见" required full><textarea name="comment" rows={3} minLength={2} maxLength={300} placeholder="请记录身份核验结果或驳回原因，不要填写密码" required disabled={busy} /></Field><div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={() => setSelected(null)}>取消</button><button className="button primary" disabled={busy}>{busy ? "正在处理…" : "确认处理"}</button></div></form>
    </Modal>}
  </div>;
}
