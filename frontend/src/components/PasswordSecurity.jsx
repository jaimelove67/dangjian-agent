import { useState } from "react";
import { Key, Clock, CheckCircle } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { canChangeOwnPassword, passwordService } from "../password-security";
import { usePasswordState } from "../password-hooks";
import { formatBusinessTime } from "../business-time";
import { Badge, ErrorBox, Field, Modal } from "../components";
import "../password-security.css";

export const PASSWORD_STATUS = { pending: "待审核", approved: "已批准 · 可修改一次", rejected: "已驳回", consumed: "已完成修改", cancelled: "已撤销" };
export const passwordTime = (value) => IS_LIVE ? formatBusinessTime(value) : value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";

export function PasswordDialog({ onClose, onChanged }) {
  const { session } = useApp();
  return canChangeOwnPassword(session.user) ? <PasswordContent key={`${session.user.tenant_id}:${session.user.id}`} onClose={onClose} onChanged={onChanged} /> : null;
}

function PasswordContent({ onClose, onChanged }) {
  const { session } = useApp();
  const { notify } = useStore();
  const state = usePasswordState(session.user);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const canChange = !state.error && state.canChange;
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      if (canChange) {
        await passwordService().change(session.user, { current: fields.get("current"), password: fields.get("password"), confirmation: fields.get("confirmation") });
        form.reset();
        onChanged();
      } else {
        await passwordService().apply(session.user, fields.get("reason"));
        form.reset();
        notify("改密申请已提交，请等待平台管理员审核。");
      }
    } catch (failure) { setError(failure); }
    finally { setBusy(false); }
  }
  return <Modal title="修改密码" className="password-dialog" onClose={() => { if (!busy) onClose(); }}>
    <div className="password-account"><Key size={23} /><span><strong>{session.user.username}</strong><small>仅修改当前登录账号的密码</small></span></div>
    <>
      {state.loading && <p role="status">正在读取改密额度…</p>}
      {(error || state.error) && <ErrorBox error={error || state.error} />}
      {!state.error && !state.loading && <>
        <div className="password-policy" role="status">
          {canChange ? state.used ? <><CheckCircle size={20} /><div><strong>申请已批准，可再修改一次</strong><p>本次修改成功后授权即失效；之后修改需重新申请。</p></div></> : <><Key size={20} /><div><strong>首次自主修改 · 剩余1次</strong><p>每个账号仅可自主修改一次，后续修改需向平台管理员申请。</p></div></> : <><Clock size={20} /><div><strong>{state.pending ? "申请已提交，等待审核" : "首次自主修改机会已使用"}</strong><p>{state.pending ? "管理员处理后可在此查看结果，请勿重复提交。" : "请填写修改原因，经平台管理员批准后可再修改一次。"}</p></div></>}
        </div>
        {canChange ? <form onSubmit={submit} className="password-form">
          <Field label="当前密码" required full><input name="current" type="password" autoComplete="current-password" required disabled={busy} /></Field>
          <Field label="新密码" required full><input name="password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required disabled={busy} aria-describedby="password-requirements" /></Field>
          <Field label="确认新密码" required full><input name="confirmation" type="password" autoComplete="new-password" minLength={8} maxLength={72} required disabled={busy} /></Field>
          <p className="password-help" id="password-requirements">新密码至少8位，UTF-8 编码不超过72字节，且与当前密码不同。修改成功后需重新登录。</p>
          <div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? "正在修改…" : "确认修改并重新登录"}</button></div>
        </form> : !state.pending && <form onSubmit={submit} className="password-form">
          <Field label="申请原因" required full><textarea name="reason" rows={3} minLength={5} maxLength={300} placeholder="请说明再次修改密码的原因，不要填写当前密码或新密码" required disabled={busy} /></Field>
          <p className="password-help">填写5–300个字符。管理员仅审核申请原因，不会收到你的密码。</p>
          <div className="modal-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? "正在提交…" : "提交改密申请"}</button></div>
        </form>}
        {!!state.history?.length && <section className="password-history" aria-label="我的改密申请"><h3>申请记录</h3>{state.history.slice(0, 5).map((request) => <article key={request.id}><header><time>{passwordTime(request.created_at)}</time><Badge tone={request.status === "rejected" ? "red" : request.status === "pending" ? "orange" : "green"}>{PASSWORD_STATUS[request.status]}</Badge></header><p>{request.reason}</p>{request.review_comment && <p className="password-review-comment">处理意见：{request.review_comment}<small>{request.reviewer_name} · {passwordTime(request.reviewed_at)}</small></p>}</article>)}</section>}
      </>}
      {!IS_LIVE && <p className="password-demo-note">密码与申请记录保存在当前浏览器，请在此工作区办理后续操作。</p>}
    </>
  </Modal>;
}
