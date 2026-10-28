import { useState } from "react";
import { User, DeviceMobile, Clock, ShieldCheck, Bell, EnvelopeSimple, FileText, CheckCircle, ArrowUUpLeft, CaretRight, SignOut } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { hasPermission, isSelfService, roleLabel, scopeLabel } from "../roles";
import { accountWorkspace } from "../account-workspace";
import { canChangeOwnPassword } from "../password-security";
import { PageHeader, Badge, Modal } from "../components";
import "../account-settings.css";

const PERMISSION_NAMES = [
  ["member.self_query", "查看本人档案"], ["member.material_submit", "提交本人材料"],
  ["member.query", "查阅授权范围内的党员名册"], ["member.stage_transition", "办理党员发展与阶段登记"],
  ["member.scoring", "登记党员培养情况"], ["meeting.query", "查看组织生活记录"],
  ["meeting.manage", "登记与维护组织生活"], ["meeting.review", "独立审核组织生活记录"],
  ["meeting.archive", "办理组织生活归档"], ["admin.review", "处理授权范围内的业务审核"],
  ["admin.archive_confirm", "确认校级业务归档"], ["study.query", "查看学习教育记录"],
  ["education.query", "查看学习课程与活动"],
  ["study.manage", "维护学习教育安排"], ["study.review", "核验学习教育记录"],
  ["assessment.query", "查阅考核评价记录"], ["assessment.manage", "登记考核与佐证材料"],
  ["assessment.review", "核验考核材料"], ["assessment.export", "导出授权范围内的考核记录"],
  ["assessment.configure", "维护学校考核规则"], ["knowledge.query", "查阅党建工作资料"],
  ["knowledge.manage", "维护党建工作资料"], ["knowledge.review", "核验党建工作资料"],
  ["qa.ask", "使用党建智能体"], ["admin.identity", "维护授权范围内的账号"],
  ["admin.audit", "查阅授权范围内的审计记录"], ["admin.ops", "处理平台系统运维"],
  ["admin.config", "维护授权范围内的系统配置"],
];
function formatTime(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "暂无记录";
  const date = new Date(value);
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" });
  const clock = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
  if (day.format(date) === day.format(new Date())) return `今天 ${clock}`;
  if (day.format(date) === day.format(new Date(Date.now() - 86400000))) return `昨天 ${clock}`;
  return `${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric" }).format(date)} ${clock}`;
}
function readPreferences(key) {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    return { reminders: typeof saved?.reminders === "boolean" ? saved.reminders : true, digest: typeof saved?.digest === "boolean" ? saved.digest : false };
  } catch { return { reminders: true, digest: false }; }
}
export function AccountSettings({ onLogout }) {
  const { session } = useApp();
  return <PersonalCenter key={`${session.user.tenant_id}:${session.user.id}`} onLogout={onLogout} />;
}
function PersonalCenter({ onLogout }) {
  const { session, navigate } = useApp();
  const { data, notify } = useStore();
  const { user } = session;
  const workspace = accountWorkspace(data, session);
  const preferencesKey = `dangjian.personal-notifications.v1:${encodeURIComponent(user.tenant_id || "")}:${encodeURIComponent(user.id)}`;
  const [preferences, setPreferences] = useState(() => readPreferences(preferencesKey));
  const [saved, setSaved] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [busy, setBusy] = useState(false);
  const personal = isSelfService(user);
  const platform = user.role === "system_admin";
  const administrator = platform ? "平台管理员" : "学校管理员";
  const workItems = IS_LIVE ? [] : workspace.items;
  const recent = IS_LIVE ? [] : workspace.recent;
  const recentAll = IS_LIVE ? [] : workspace.recentAll;
  const active = IS_LIVE ? user.is_active : data.accounts.find((account) => account.id === user.id && (account.tenant_id || "school-1") === (user.tenant_id || "school-1"))?.is_active;
  const status = active === false ? "已停用" : active === true ? "正常" : "已登录";
  const permissionNames = PERMISSION_NAMES.filter(([permission]) => hasPermission(session, permission) && (!platform || ["admin.identity", "admin.ops", "admin.config", "admin.audit"].includes(permission)));
  const organization = IS_LIVE ? user.org_name || user.department || "以账号登记的组织归属为准" : workspace.organization;
  const loginTime = IS_LIVE ? user.last_login_at : workspace.lastLogin;

  function togglePreference(key) {
    const next = { ...preferences, [key]: !preferences[key] };
    try { localStorage.setItem(preferencesKey, JSON.stringify(next)); setPreferences(next); setSaved(true); }
    catch { notify("设置未能保存，请检查浏览器的本地存储权限。", "error"); }
  }
  async function logout() {
    setBusy(true);
    try { await onLogout(); }
    catch (error) { notify(error.message || "退出失败，请重试。", "error"); }
    finally { setBusy(false); }
  }
  const statistics = [
    { key: "pending", label: "待我审核", value: workspace.pending, enabled: workspace.canReview },
    { key: "submitted", label: "我提交的事项", value: workspace.submitted, enabled: !platform },
    { key: "returned", label: "退回待补", value: workspace.returned, enabled: !platform },
  ];
  const recentIcon = (tone) => tone === "green" ? CheckCircle : tone === "orange" ? ArrowUUpLeft : FileText;

  return (
    <section className="panel workspace-panel account-settings personal-center">
      <PageHeader title="个人中心" subtitle="管理个人信息，跟进我的工作" />
      <div className="personal-center-content">
        <section className="personal-identity" aria-label="个人资料">
          <div className="personal-avatar" aria-hidden="true">{(user.name || user.username || "我")[0]}</div>
          <div className="personal-identity-info">
            <div className="personal-name-line"><h2>{user.name || user.username}</h2><Badge tone="red">{roleLabel(user)}</Badge></div>
            <p className="personal-organization">{organization}</p>
            <div className="personal-identity-meta"><span>登录账号：<b>{user.username}</b></span><span>{personal ? "访问范围" : "管理范围"}：{IS_LIVE ? scopeLabel(user) : workspace.scope}</span></div>
          </div>
          <div className="personal-identity-actions"><button className="button secondary" onClick={() => setDialog("correction")}>申请更正资料</button><button className="text-button" onClick={() => setDialog("permissions")}>查看权限</button></div>
        </section>
        <div className="personal-center-grid">
          <div className="personal-center-column">
            <section className="personal-card personal-work" aria-labelledby="personal-work-heading">
              <header className="personal-card-heading"><h2 id="personal-work-heading">我的工作</h2><button className="button primary" onClick={() => navigate(workspace.workRoute)}>{platform ? "前往工作台" : "处理待办"}</button></header>
              <div className="personal-work-stats">{statistics.map((item) => <button key={item.label} disabled={!item.enabled} onClick={() => setDialog(item.key)}><span>{item.label}</span><strong>{IS_LIVE || platform ? "—" : item.value}</strong></button>)}</div>
              <div className="personal-work-list">
                {workItems.map((item) => <button className="personal-work-row" key={item.id} onClick={() => navigate(item.route, item.params || {})}><span className="personal-file-icon"><FileText size={25} /></span><span className="personal-row-copy"><strong>{item.title}</strong><small>{item.organization}</small></span><Badge tone={item.status === "待审核" ? "red" : ["已退回", "待补充"].includes(item.status) ? "orange" : "blue"}>{item.status}</Badge><CaretRight size={18} /></button>)}
                {!workItems.length && <div className="personal-empty"><FileText size={30} /><p>{IS_LIVE ? "前往业务模块查看本人待办与提交记录" : platform ? "平台运维与账号待办请在平台工作台查看" : "当前暂无需要处理的个人事项"}</p></div>}
              </div>
            </section>
            <section className="personal-card personal-recent" aria-labelledby="personal-recent-heading">
              <header className="personal-card-heading"><h2 id="personal-recent-heading">最近操作</h2><button className="text-button" onClick={() => setDialog("recent")}>查看全部<CaretRight size={14} /></button></header>
              {recent.map((event) => { const Icon = recentIcon(event.tone); return <div className="personal-recent-row" key={event.id}><span className={`personal-event-icon ${event.tone}`}><Icon size={18} weight={event.tone === "green" ? "fill" : "regular"} /></span><span className="personal-event-title">{event.title}</span><span className="personal-event-org">{event.organization}</span><time dateTime={event.createdAt}>{formatTime(event.createdAt)}</time></div>; })}
              {!recent.length && <div className="personal-empty"><Clock size={28} /><p>{IS_LIVE ? "各业务模块保留相应操作记录" : "暂无本人的操作记录"}</p></div>}
            </section>
          </div>
          <div className="personal-center-column">
            <section className="personal-card personal-security" aria-labelledby="personal-security-heading">
              <header className="personal-card-heading"><h2 id="personal-security-heading">账号与安全</h2></header>
              <div className="personal-security-row"><User size={24} /><span>登录方式</span><strong>账号密码登录</strong><button className="personal-inline-action" onClick={() => setDialog("authentication")}>登录说明<CaretRight size={14} /></button></div>
              <div className="personal-security-row"><DeviceMobile size={24} /><span>联系方式</span><strong>{user.phone || (IS_LIVE ? "暂未提供" : "未登记")}</strong><button className="personal-inline-action" onClick={() => setDialog("contact")}>登记方式<CaretRight size={14} /></button></div>
              <div className="personal-security-row"><Clock size={24} /><span>最近登录</span><strong>{formatTime(loginTime)}</strong></div>
              <div className="personal-security-row"><ShieldCheck size={24} /><span>账号状态</span><strong className="personal-account-status"><i className="personal-status-dot" />{status}</strong></div>
              <p className="personal-card-note">组织信息如有变更，请联系{administrator}。</p>
            </section>
            <section className="personal-card personal-notifications" aria-labelledby="personal-notifications-heading">
              <header className="personal-card-heading"><h2 id="personal-notifications-heading">通知设置</h2></header>
              {[
                { key: "reminders", title: "待办与审核提醒", text: "及时了解需要我处理的事项", Icon: Bell },
                { key: "digest", title: "每日工作汇总", text: "关注未完成的个人待办", Icon: EnvelopeSimple },
              ].map(({ key, title, text, Icon }) => <div className="personal-notification-row" key={key}><Icon size={25} /><span className="personal-row-copy"><strong>{title}</strong><small>{text}</small></span><button className="personal-switch" type="button" role="switch" aria-label={title} aria-checked={preferences[key]} onClick={() => togglePreference(key)} /></div>)}
              <p className="personal-card-note" role="status">{saved ? "设置已保存至当前浏览器" : "通知偏好仅保存于当前浏览器"}</p>
            </section>
          </div>
        </div>
        <div className="personal-center-footer"><p className="personal-demo-note">{IS_LIVE ? "工作记录以授权业务模块为准" : "仅展示当前账号授权范围内的记录"}</p><button className="text-button personal-logout" disabled={busy} onClick={logout}><SignOut size={16} />{busy ? "正在退出…" : "退出登录"}</button></div>
      </div>
      {dialog && <Modal className="personal-center-dialog" title={{ correction: "申请更正资料", permissions: "我的访问权限", authentication: "登录与安全说明", contact: "联系方式登记", recent: "我的操作记录", pending: "待我审核", submitted: "我提交的事项", returned: "退回待补" }[dialog]} onClose={() => setDialog(null)} wide={["recent", "pending", "submitted", "returned"].includes(dialog)}>
        {dialog === "correction" && <><p className="personal-dialog-copy">姓名、所属组织和管理范围由管理员核验维护。如需更正，请联系{administrator}，提供当前登录账号和需要更正的资料。</p><dl className="detail-list"><dt>当前账号</dt><dd>{user.username}</dd><dt>所属单位</dt><dd>{organization}</dd></dl></>}
        {dialog === "permissions" && <><dl className="detail-list"><dt>当前角色</dt><dd>{roleLabel(user)}</dd><dt>访问范围</dt><dd>{IS_LIVE ? scopeLabel(user) : workspace.scope}</dd></dl><ul className="personal-permissions">{permissionNames.map(([permission, label]) => <li key={permission}><CheckCircle size={17} />{label}</li>)}</ul></>}
        {dialog === "authentication" && <><p className="personal-dialog-copy">当前使用账号和密码登录。{canChangeOwnPassword(user) ? "从右上角头像菜单进入修改密码，首次可自主修改，之后每次修改需向平台管理员申请。" : `请妥善保管密码；如需重置，请联系${administrator}核验身份后处理。`}</p><p className="personal-dialog-copy">校园统一认证暂不可用，请使用账号密码登录。</p></>}
        {dialog === "contact" && <p className="personal-dialog-copy">{user.phone ? `当前登记：${user.phone}。` : IS_LIVE ? "当前登录信息暂未提供联系方式。" : "当前账号未登记联系方式。"}如需登记或更正，请联系{administrator}核验维护。</p>}
        {dialog === "recent" && <>{recentAll?.length ? recentAll.map((event) => <div className="personal-history-row" key={event.id}><strong>{event.title}</strong><span>{event.organization}</span><time dateTime={event.createdAt}>{formatTime(event.createdAt)}</time></div>) : <div className="personal-empty"><Clock size={30} /><p>{IS_LIVE ? "请在对应业务模块查看本人操作记录" : "暂无本人的操作记录"}</p></div>}</>}
        {["pending", "submitted", "returned"].includes(dialog) && <>{!IS_LIVE && workspace[`${dialog}Items`]?.length ? workspace[`${dialog}Items`].map((item) => <button className="personal-work-row" key={item.id} onClick={() => navigate(item.route, item.params || {})}><span className="personal-file-icon"><FileText size={24} /></span><span className="personal-row-copy"><strong>{item.title}</strong><small>{item.organization}</small></span><Badge>{item.status}</Badge><CaretRight size={16} /></button>) : <div className="personal-empty"><FileText size={30} /><p>{IS_LIVE ? "前往业务模块查看当前账号的记录" : "暂无符合条件的个人事项"}</p></div>}<div className="modal-actions"><button className="button secondary" onClick={() => navigate(workspace.workRoute)}>前往业务办理<CaretRight size={15} /></button></div></>}
      </Modal>}
    </section>
  );
}
