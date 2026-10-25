import { useEffect, useState } from "react";
import {
  Buildings,
  UsersThree,
  ShieldCheck,
  Plus,
  DownloadSimple,
  Key,
  WarningCircle,
  CheckCircle,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, saveSession } from "../api";
import { ROLE_INFO, accountOrganizations, hasPermission } from "../roles";
import { newAudit } from "../role-data";
import {
  platformIdentityApi as api,
  ADMIN_ROLES,
  validSchoolAdmin,
  accountOrgTypes,
  accountRolesForTenant,
  validateAccountUpdate,
} from "../platform-identity-api";
import {
  PageHeader,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Modal,
  Field,
  Empty,
  Loading,
  ErrorBox,
  Pagination,
  exportCsv,
  downloadBlob,
} from "../components";
import "../platform-identity.css";
import { PasswordRequests } from "../components/PasswordRequests";
import { usePasswordState } from "../password-hooks";
import {
  accountPasswordChange,
  demoPasswordService,
} from "../password-security";
import { AccountPasswordFields } from "../components/AccountPasswordFields";
import { accountSecurityApi } from "../account-security-api";
import { LiveSchoolBusiness } from "./LiveSchoolBusiness";
import { formatBusinessTime } from "../business-time";

const dateTime = (v) => {
  if (IS_LIVE) return formatBusinessTime(v);
  if (!v) return "—";
  const date = new Date(v);
  if (Number.isNaN(date.getTime())) return "—";
  return date
    .toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
    .replaceAll("/", "-");
};
const size = (v) =>
  v == null
    ? "暂无数据"
    : v >= 1073741824
      ? `${(v / 1073741824).toFixed(1)} GB`
      : `${(v / 1048576).toFixed(1)} MB`;
const list = (r) => (Array.isArray(r) ? r : r?.items || []);
function useRemote(load, deps) {
  const [value, setValue] = useState(null),
    [error, setError] = useState(null),
    [loading, setLoading] = useState(IS_LIVE),
    [tick, setTick] = useState(0);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setLoading(true);
    setError(null);
    setValue(null);
    load()
      .then((r) => {
        if (active) setValue(r);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [...deps, tick]);
  return { value, error, loading, reload: () => setTick((n) => n + 1) };
}
function useIdentity() {
  const { session, routeParams = {} } = useApp(),
    { data, update, notify } = useStore();
  function requireAdmin() {
    if (session.user.role !== "system_admin")
      throw new Error("仅平台管理员可以执行此操作。");
  }
  function audit(
    action,
    type,
    id,
    category = "operation",
    detail = "",
    tenantId = session.user.tenant_id,
  ) {
    update("auditEntries", (prev) => [
      {
        ...newAudit(session.user, action, type, id),
        category,
        tenant_id: tenantId,
        detail,
        ip_address: "127.0.0.1",
      },
      ...prev,
    ]);
  }
  function platform(change) {
    update("platform", (prev) => ({ ...prev, ...change(prev || {}) }));
  }
  return {
    session,
    routeParams,
    data,
    update,
    notify,
    requireAdmin,
    audit,
    platform,
  };
}
function Denied() {
  return (
    <Empty title="无权访问平台管理" description="此页面仅向平台管理员开放。" />
  );
}
function StateBadge({ active }) {
  return (
    <Badge tone={active !== false ? "green" : "orange"}>
      {active !== false ? "启用" : "停用"}
    </Badge>
  );
}
function FormActions({ busy, close, label = "保存" }) {
  return (
    <div className="modal-actions">
      <button
        type="button"
        className="button secondary"
        onClick={close}
        disabled={busy}
      >
        取消
      </button>
      <button className="button primary" disabled={busy}>
        {busy ? "正在保存…" : label}
      </button>
    </div>
  );
}
function Metrics({ items }) {
  return (
    <div className="identity-metrics">
      {items.map(([label, value, Icon, note]) => (
        <div key={label}>
          <span className="identity-metric-icon">
            <Icon size={23} weight="duotone" />
          </span>
          <div>
            <span>{label}</span>
            <strong>{value}</strong>
            {note && <small>{note}</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function PlatformTenants() {
  const { session, routeParams, data, update, notify, requireAdmin, audit } =
    useIdentity();
  const remote = useRemote(api.tenants, [session.user.id]);
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(null);
  const tenantRows = IS_LIVE ? list(remote.value) : data.tenants;
  const schools = tenantRows.filter((t) => t.tenant_type === "school");
  const rows = schools.filter(
    (t) =>
      (!query || `${t.name} ${t.contact_name || ""}`.includes(query)) &&
      (!status || String(t.is_active !== false) === status),
  );
  const selected = modal?.tenant;
  const adminRemote = useRemote(
    () => (selected ? api.users(selected.id) : Promise.resolve({ items: [] })),
    [selected?.id, session.user.id],
  );
  const admins = (
    IS_LIVE
      ? list(adminRemote.value).map((a) => ({ ...a, tenant_id: selected?.id }))
      : data.accounts
  ).filter((a) => selected && validSchoolAdmin(a, selected.id));
  const usage = data.platform?.usage?.find((u) => u.tenant_id === selected?.id);
  const platformTenant = tenantRows.find((t) => t.tenant_type === "platform");
  useEffect(() => {
    if (!routeParams.tenantId) return;
    const tenant = tenantRows.find(
      (t) => t.id === routeParams.tenantId && t.tenant_type === "school",
    );
    if (tenant) setModal({ mode: "detail", tenant });
  }, [routeParams.tenantId, remote.value]);
  function open(mode, tenant) {
    setError(null);
    setModal({ mode, tenant });
  }
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      requireAdmin();
      const f = new FormData(e.currentTarget),
        name = f.get("name").trim();
      if (!name) throw new Error("请输入学校名称。");
      if (schools.some((t) => t.name === name && t.id !== selected?.id))
        throw new Error("学校名称已存在。");
      const contact_name = String(f.get("contact_name") || "").trim();
      const contact_phone = String(f.get("contact_phone") || "").trim();
      const contact_email = String(f.get("contact_email") || "").trim();
      const remark = String(f.get("description") || "").trim();
      const body = {
        name,
        contact_name: contact_name || null,
        contact_phone: contact_phone || null,
        contact_email: contact_email || null,
        remark: remark || null,
        ...(!selected
          ? { tenant_type: "school", parent_id: platformTenant?.id }
          : {}),
      };
      if (!selected && !body.parent_id)
        throw new Error("缺少平台根租户，无法开通学校。");
      if (IS_LIVE) {
        selected
          ? await api.updateTenant(selected.id, body)
          : await api.createTenant(body);
        remote.reload();
      } else {
        const record = {
          ...selected,
          ...body,
          id: selected?.id || crypto.randomUUID(),
          is_active: selected?.is_active !== false,
          contact_name: f.get("contact_name").trim(),
          contact_phone: f.get("contact_phone").trim(),
          contact_email: f.get("contact_email").trim(),
          service_plan: f.get("service_plan"),
          description: remark,
          remark,
          updated_at: new Date().toISOString(),
        };
        update("tenants", (prev) =>
          selected
            ? prev.map((t) => (t.id === selected.id ? record : t))
            : [...prev, record],
        );
        audit(
          selected ? "更新学校租户资料" : "开通学校租户",
          "tenant",
          record.id,
          "operation",
          name,
          record.id,
        );
      }
      notify(
        selected
          ? "学校资料已保存"
          : "学校租户已开通；请在账号与权限中创建校级管理员",
      );
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function toggleTenant() {
    setBusy(true);
    setError(null);
    try {
      requireAdmin();
      if (!selected || selected.tenant_type !== "school")
        throw new Error("仅允许在此管理学校租户。");
      if (
        selected.id === session.user.tenant_id &&
        selected.is_active !== false
      )
        throw new Error("不能停用当前登录租户。");
      if (IS_LIVE) {
        await api.updateTenant(selected.id, {
          is_active: selected.is_active === false,
        });
        remote.reload();
      } else {
        update("tenants", (prev) =>
          prev.map((t) =>
            t.id === selected.id
              ? { ...t, is_active: t.is_active === false }
              : t,
          ),
        );
        audit(
          selected.is_active === false ? "启用学校租户" : "停用学校租户",
          "tenant",
          selected.id,
          "operation",
          "",
          selected.id,
        );
      }
      notify(
        selected.is_active === false ? "学校租户已启用" : "学校租户已停用",
      );
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function assignAdmin(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      requireAdmin();
      const userId = new FormData(e.currentTarget).get("admin_id"),
        account = admins.find((a) => a.id === userId);
      if (!validSchoolAdmin(account, selected.id))
        throw new Error("请选择该学校已启用的校级管理员。");
      if (IS_LIVE)
        throw new Error(
          "学校管理员由账号的校级角色和所属学校确定，暂不支持单独指定主要负责人。",
        );
      update("tenants", (prev) =>
        prev.map((t) =>
          t.id === selected.id ? { ...t, school_admin_user_id: userId } : t,
        ),
      );
      audit(
        "指定学校管理员",
        "tenant",
        selected.id,
        "permission",
        `指定校级管理员：${account.name}`,
        selected.id,
      );
      notify("学校主要管理员已指定");
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (session.user.role !== "system_admin") return <Denied />;
  return (
    <div className="platform-identity-page">
      <Metrics
        items={[
          ["接入学校", schools.length, Buildings, "学校租户独立管理"],
          [
            "已启用学校",
            schools.filter((t) => t.is_active !== false).length,
            CheckCircle,
            "可正常访问服务",
          ],
          [
            "已停用学校",
            schools.filter((t) => t.is_active === false).length,
            ShieldCheck,
            "保留数据与审计记录",
          ],
        ]}
      />
      <section className="panel workspace-panel">
        <PageHeader
          title="租户管理"
          subtitle="管理接入平台的学校，维护服务状态与学校管理责任"
          action={
            <button className="button primary" onClick={() => open("edit")}>
              <Plus size={18} />
              开通学校
            </button>
          }
        />
        <div className="table-toolbar">
          <SearchInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索学校名称或联系人"
          />
          <Select
            label="租户状态"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">全部状态</option>
            <option value="true">已启用</option>
            <option value="false">已停用</option>
          </Select>
          <span className="toolbar-spacer" />
          <span className="muted">共 {rows.length} 所学校</span>
        </div>
        {remote.error && (
          <ErrorBox error={remote.error} retry={remote.reload} />
        )}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {[
                  "学校名称",
                  "学校管理员",
                  "服务状态",
                  "服务使用",
                  "最近更新",
                  "操作",
                ].map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const schoolAdmins = !IS_LIVE
                    ? data.accounts.filter((a) => validSchoolAdmin(a, t.id))
                    : [],
                  main =
                    schoolAdmins.find((a) => a.id === t.school_admin_user_id) ||
                    schoolAdmins[0];
                const u = !IS_LIVE
                  ? data.platform?.usage?.find((u) => u.tenant_id === t.id)
                  : null;
                return (
                  <tr key={t.id}>
                    <td>
                      <span className="file-name">
                        <Buildings size={22} />
                        {t.name}
                      </span>
                      <small className="cell-subtext">
                        {t.service_plan || "学校服务"}
                      </small>
                    </td>
                    <td>
                      {IS_LIVE ? (
                        <button
                          className="text-button link"
                          onClick={() => open("admins", t)}
                        >
                          查看管理员
                        </button>
                      ) : main ? (
                        <>
                          {main.name}
                          <small className="cell-subtext">
                            {main.username}
                          </small>
                        </>
                      ) : (
                        <Badge tone="orange">待分配</Badge>
                      )}
                    </td>
                    <td>
                      <StateBadge active={t.is_active} />
                    </td>
                    <td>
                      {u
                        ? `${u.active_accounts ?? 0} 活跃账号 · ${size(u.storage_bytes)}`
                        : "暂无统计"}
                    </td>
                    <td>{dateTime(t.updated_at)}</td>
                    <td>
                      <div className="identity-row-actions">
                        <button
                          className="text-button link"
                          onClick={() => open("detail", t)}
                        >
                          详情
                        </button>
                        <button
                          className="text-button link"
                          onClick={() => open("edit", t)}
                        >
                          编辑
                        </button>
                        <button
                          className="text-button link"
                          onClick={() => open("toggle", t)}
                        >
                          {t.is_active === false ? "启用" : "停用"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {remote.loading && <Loading />}
          {!rows.length && !remote.loading && (
            <Empty
              title="暂无学校租户"
              description="开通学校后，可继续创建并分配校级管理员。"
            />
          )}
        </div>
        <p className="page-note">
          学校停用后保留已有数据；重新启用后恢复服务。学校管理员权限由账号角色与组织归属确定。
        </p>
      </section>
      {modal && (
        <Modal
          title={
            modal.mode === "edit"
              ? selected
                ? "维护学校资料"
                : "开通学校租户"
              : modal.mode === "toggle"
                ? selected.is_active === false
                  ? "启用学校租户"
                  : "停用学校租户"
                : modal.mode === "admins"
                  ? "学校管理员"
                  : "学校租户详情"
          }
          wide={modal.mode !== "toggle"}
          onClose={() => !busy && setModal(null)}
        >
          {error && <ErrorBox error={error} />}
          {modal.mode === "edit" ? (
            <form onSubmit={save}>
              <div className="form-grid">
                <Field label="学校名称" required full>
                  <input
                    name="name"
                    required
                    maxLength={100}
                    defaultValue={selected?.name || ""}
                  />
                </Field>
                <Field label="学校联系人">
                  <input
                    name="contact_name"
                    maxLength={50}
                    defaultValue={selected?.contact_name || ""}
                    placeholder="例如：党委组织部李老师"
                  />
                </Field>
                <Field label="联系电话">
                  <input
                    name="contact_phone"
                    maxLength={20}
                    defaultValue={selected?.contact_phone || ""}
                    placeholder="请输入便于联系的办公电话"
                  />
                </Field>
                <Field label="联系邮箱">
                  <input
                    name="contact_email"
                    type="email"
                    maxLength={100}
                    defaultValue={selected?.contact_email || ""}
                    placeholder="用于接收平台通知"
                  />
                </Field>
                {!IS_LIVE && (
                  <Field label="服务方案">
                    <select
                      name="service_plan"
                      defaultValue={selected?.service_plan || "标准学校服务"}
                    >
                      {selected?.service_plan &&
                        !["标准学校服务", "试用学校服务"].includes(
                          selected.service_plan,
                        ) && <option>{selected.service_plan}</option>}
                      <option>标准学校服务</option>
                      <option>试用学校服务</option>
                    </select>
                  </Field>
                )}
                <Field label="学校备注" full>
                  <textarea
                    name="description"
                    rows={3}
                    maxLength={500}
                    defaultValue={selected?.description || selected?.remark || ""}
                    placeholder="补充学校对接说明或服务备注"
                  />
                </Field>
                <p className="inline-note field full identity-form-guidance">
                  {selected
                    ? "学校名称和已登记联系资料可在此维护；服务方案按平台配置管理。"
                    : "开通学校只要求填写学校名称；联系人资料可同时登记，也可以开通后在学校详情中补充。服务方案按平台配置管理。"}
                </p>
              </div>
              <FormActions
                busy={busy}
                close={() => setModal(null)}
                label={selected ? "保存资料" : "开通学校"}
              />
            </form>
          ) : modal.mode === "toggle" ? (
            <>
              <div className="identity-confirm">
                <WarningCircle size={28} />
                <div>
                  <h3>{selected.name}</h3>
                  <p>
                    {selected.is_active === false
                      ? "启用后，该学校的有效账号可恢复使用平台。"
                      : "停用后，该学校账号将无法继续使用服务，已有业务数据与审计记录保留。"}
                  </p>
                </div>
              </div>
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => setModal(null)}
                  disabled={busy}
                >
                  取消
                </button>
                <button
                  className="button primary"
                  onClick={toggleTenant}
                  disabled={busy}
                >
                  {busy
                    ? "正在处理…"
                    : selected.is_active === false
                      ? "确认启用"
                      : "确认停用"}
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="identity-detail-banner">
                <Buildings size={30} />
                <div>
                  <h3>{selected.name}</h3>
                  <p>{selected.description || "独立的学校数据与管理范围"}</p>
                </div>
                <StateBadge active={selected.is_active} />
              </div>
              {modal.mode !== "admins" && (
                <>
                  <dl className="identity-details">
                    <dt>联系人</dt>
                    <dd>{selected.contact_name || "未登记"}</dd>
                    <dt>联系电话</dt>
                    <dd>{selected.contact_phone || "未登记"}</dd>
                    <dt>联系邮箱</dt>
                    <dd>{selected.contact_email || "未登记"}</dd>
                    <dt>服务方案</dt>
                    <dd>{selected.service_plan || (IS_LIVE ? "按平台配置" : "未登记")}</dd>
                    <dt>学校备注</dt>
                    <dd>{selected.description || selected.remark || "未登记"}</dd>
                  </dl>
                  <h3 className="identity-section-heading">服务使用情况</h3>
                  {IS_LIVE || !usage ? (
                    <p className="inline-note">
                      学校服务用量暂不可用，请稍后刷新或联系管理员。
                    </p>
                  ) : (
                    <div className="identity-usage">
                      <div>
                        <span>活跃账号</span>
                        <strong>{usage.active_accounts ?? 0}</strong>
                      </div>
                      <div>
                        <span>文件数量</span>
                        <strong>{usage.files_count ?? 0}</strong>
                      </div>
                      <div>
                        <span>存储使用</span>
                        <strong>{size(usage.storage_bytes)}</strong>
                        <small>容量 {size(usage.storage_limit_bytes)}</small>
                      </div>
                      <div>
                        <span>处理任务</span>
                        <strong>{usage.task_count ?? 0}</strong>
                        <small>{usage.period_label || "最近30天"}</small>
                      </div>
                    </div>
                  )}
                  <h3 className="identity-section-heading">本校档案导入</h3>
                  <div className="identity-handoff">
                    <strong>由学校管理员在学校端办理</strong>
                    <p>
                      平台管理员完成学校开通和校级管理员授权后，学校登录本校账号进入“组织与党员 → 党员档案与材料”，下载名册模板并按当前组织权限导入。
                    </p>
                    <ol>
                      <li>下载导入模板，按模板填写姓名、所属组织和当前发展阶段。</li>
                      <li>填写名册来源说明，先预检文件并处理逐行错误。</li>
                      <li>确认无误后提交；系统只登记基础档案台账，不导入材料原件、不建立账号关联，也不代替材料审核。</li>
                    </ol>
                    <span className="page-note">
                      平台管理员不会跨学校代导入人员档案，导入记录按学校租户写入审计。
                    </span>
                  </div>
                </>
              )}
              <h3 className="identity-section-heading">校级管理员</h3>
              {adminRemote.error && (
                <ErrorBox
                  error={adminRemote.error}
                  retry={adminRemote.reload}
                />
              )}
              {adminRemote.loading ? (
                <Loading />
              ) : admins.length ? (
                <form onSubmit={assignAdmin}>
                  <div className="identity-admin-list">
                    {admins.map((a) => (
                      <label key={a.id}>
                        <input
                          type="radio"
                          name="admin_id"
                          value={a.id}
                          defaultChecked={
                            a.id === selected.school_admin_user_id ||
                            (!selected.school_admin_user_id &&
                              a.id === admins[0].id)
                          }
                          disabled={IS_LIVE}
                        />
                        <div>
                          <strong>{a.name}</strong>
                          <small>{a.username}</small>
                        </div>
                        <Badge tone="green">校级管理员</Badge>
                      </label>
                    ))}
                  </div>
                  {!IS_LIVE && (
                    <div className="modal-actions">
                      <button
                        className="button primary"
                        disabled={busy || selected.is_active === false}
                      >
                        指定主要管理员
                      </button>
                    </div>
                  )}
                </form>
              ) : (
                <Empty
                  title="尚无有效校级管理员"
                  description="请在账号与权限中选择该学校，创建校级管理员并授权学校组织。"
                />
              )}
              {IS_LIVE && (
                <p className="page-note">
                  校级角色和所属学校共同确定管理员授权；请到“账号与权限”开户或调整授权，暂不支持单独指定主要负责人。
                </p>
              )}
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

export function PlatformAccounts() {
  const { setSession } = useApp();
  const {
    session,
    routeParams,
    data,
    update,
    notify,
    requireAdmin,
    audit,
    platform,
  } = useIdentity();
  const schoolScoped = session.user.role === "school_admin";
  const [platformTenantId, setTenantId] = useState(
      routeParams.tenantId || session.user.tenant_id || "platform-1",
    ),
    [query, setQuery] = useState(""),
    [roleFilter, setRoleFilter] = useState(""),
    [tab, setTab] = useState(
      schoolScoped
        ? "accounts"
        : routeParams.tab === "登录会话"
          ? "sessions"
          : routeParams.tab === "改密申请"
            ? "requests"
            : "accounts",
    ),
    [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(null),
    [formRole, setFormRole] = useState("school_admin");
  const tenantId = schoolScoped ? session.user.tenant_id : platformTenantId;
  useEffect(() => {
    if (schoolScoped) return;
    if (routeParams.tab)
      setTab(
        routeParams.tab === "登录会话"
          ? "sessions"
          : routeParams.tab === "改密申请"
            ? "requests"
            : "accounts",
      );
    if (routeParams.tenantId) setTenantId(routeParams.tenantId);
  }, [routeParams.tab, routeParams.tenantId, schoolScoped]);
  const tenantsRemote = useRemote(
    () =>
      schoolScoped
        ? Promise.resolve([
            {
              id: tenantId,
              name: session.user.tenant_name || "本校",
              tenant_type: "school",
            },
          ])
        : api.tenants(),
    [session.user.id, tenantId, schoolScoped],
  );
  const tenants = IS_LIVE
    ? list(tenantsRemote.value)
    : data.tenants.filter((t) => !schoolScoped || t.id === tenantId);
  const selectedTenant = tenants.find((t) => t.id === tenantId),
    isPlatform = selectedTenant?.tenant_type === "platform";
  const remote = useRemote(
    () => Promise.all([api.users(tenantId), api.orgs(tenantId)]),
    [tenantId, session.user.id],
  );
  const accounts = IS_LIVE
    ? list(remote.value?.[0]).map((a) => ({ ...a, tenant_id: tenantId }))
    : data.accounts.filter((a) => a.tenant_id === tenantId);
  const orgs = IS_LIVE
    ? list(remote.value?.[1])
    : tenantId === "school-1"
      ? accountOrganizations()
      : [
          {
            id: tenantId,
            name: selectedTenant?.name || "学校党委",
            org_type: "school",
          },
        ];
  const rows = accounts.filter(
    (a) =>
      (!query || `${a.username} ${a.name}`.includes(query)) &&
      (!roleFilter || a.role === roleFilter),
  );
  const sessionsRemote = useRemote(() => accountSecurityApi.sessions(tenantId), [tenantId, session.user.id]);
  const sessions = (IS_LIVE ? list(sessionsRemote.value) : data.platform?.sessions || []).filter(
    (s) =>
      s.tenant_id === tenantId &&
      (!query || `${s.username} ${s.client_label}`.includes(query)),
  );
  const selected = modal?.account;
  const passwordState = usePasswordState(session.user, {
    admin: true,
    tenantId,
  });
  const pendingPasswordRequests = passwordState.requests.filter(
    (request) => request.status === "pending",
  ).length;
  const orgOptions = orgs.filter(
    (o) =>
      o.is_active !== false && accountOrgTypes(formRole).includes(o.org_type),
  );
  const roles = accountRolesForTenant(selectedTenant, { create: !selected });
  const editingSelf = selected?.id === session.user.id;
  const personalOrgLocked =
    selected?.profile_id &&
    ["member", "applicant"].includes(selected.role) &&
    ["member", "applicant"].includes(formRole);
  function open(mode, account) {
    setError(null);
    setFormRole(
      account?.role || (isPlatform ? "system_admin" : "school_admin"),
    );
    setModal({ mode, account });
  }
  function ensureTenantEditable() {
    if (!hasPermission(session, "admin.identity"))
      throw new Error("当前账号没有账号管理权限。");
    if (!schoolScoped) requireAdmin();
    if (schoolScoped && tenantId !== session.user.tenant_id)
      throw new Error("学校管理员只能管理本校账号。");
    if (!selectedTenant) throw new Error("请先选择有效的管理租户。");
    if (IS_LIVE && (remote.loading || remote.error))
      throw new Error("请先成功加载本校账号与组织信息，再进行修改。");
    if (selectedTenant?.is_active === false)
      throw new Error("该学校已停用，请先启用学校租户。");
  }
  function ensureAccountChange(account, changes) {
    validateAccountUpdate(session.user, account, changes, {
      tenant: selectedTenant,
      accounts,
      orgs,
    });
  }
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      ensureTenantEditable();
      const f = new FormData(e.currentTarget),
        name = f.get("name").trim(),
        username = selected?.username || f.get("username").trim();
      if (!name || !username || /\s/.test(username))
        throw new Error("请填写姓名与不含空白字符的账号。");
      if (!roles.includes(formRole))
        throw new Error("该租户不支持选择的账号角色。");
      const orgId =
        formRole === "system_admin"
          ? null
          : personalOrgLocked || editingSelf
            ? selected.org_unit_id
            : f.get("org_unit_id");
      if (
        formRole !== "system_admin" &&
        !orgOptions.some((o) => o.id === orgId)
      )
        throw new Error("请选择与角色类型匹配的组织范围。");
      const body = { name, role: formRole, org_unit_id: orgId };
      const password = selected ? accountPasswordChange(f) : undefined;
      if (selected) {
        body.is_active = editingSelf
          ? selected.is_active !== false
          : f.get("is_active") === "true";
        ensureAccountChange(selected, body);
      } else {
        requireAdmin();
        if (!IS_LIVE && data.accounts.some((a) => a.username === username))
          throw new Error("该账号已存在，请填写全平台唯一的账号。");
        body.username = username;
        if (IS_LIVE) {
          const password = f.get("password");
          if (
            password.length < 8 ||
            new TextEncoder().encode(password).length > 72
          )
            throw new Error("初始密码需至少8位，且 UTF-8 编码不超过72字节。");
          body.password = password;
        }
      }
      const authorizationChanged =
        selected &&
        (body.role !== selected.role ||
          body.org_unit_id !== selected.org_unit_id ||
          body.is_active !== (selected.is_active !== false));
      if (IS_LIVE) {
        if (password) body.password = password;
        selected
          ? await api.updateUser(tenantId, selected.id, body)
          : await api.createUser(tenantId, body);
        remote.reload();
      } else {
        if (password)
          await demoPasswordService().setPassword(session.user, selected, {
            password,
            confirmation: f.get("password_confirmation"),
          });
        const organization = orgs.find((o) => o.id === orgId),
          record = {
            ...selected,
            ...body,
            id: selected?.id || crypto.randomUUID(),
            username,
            tenant_id: tenantId,
            is_active: selected ? body.is_active : true,
            org_name: organization?.name || "平台全局",
            department:
              formRole === "department_admin"
                ? organization?.name
                : organization?.department,
            ...(password
              ? {
                  force_password_change: false,
                  password_reset_at: new Date().toISOString(),
                }
              : {}),
            updated_at: new Date().toISOString(),
          };
        update("accounts", (prev) =>
          selected
            ? prev.map((a) => (a.id === selected.id ? record : a))
            : [record, ...prev],
        );
        audit(
          selected ? "编辑账号属性" : "创建管理员账号",
          "user",
          record.id,
          !selected || authorizationChanged || password
            ? "permission"
            : "operation",
          `${record.name} · ${ROLE_INFO[record.role].label} · ${record.org_name} · ${record.is_active ? "启用" : "停用"}${password ? " · 已修改密码" : ""}`,
          tenantId,
        );
        if (authorizationChanged || password)
          platform((p) => ({
            sessions: (p.sessions || []).map((s) =>
              s.user_id === selected.id
                ? {
                    ...s,
                    is_active: false,
                    revoked_at: new Date().toISOString(),
                  }
                : s,
            ),
          }));
      }
      if (editingSelf && (password || IS_LIVE)) {
        saveSession(null);
        setSession(null);
      } else if (editingSelf) {
        const nextSession = { ...session, user: { ...session.user, name } };
        saveSession(nextSession);
        setSession(nextSession);
      }
      notify(
        selected
          ? password
            ? editingSelf
              ? "密码已修改，请使用新密码重新登录"
              : "账号信息与新密码已保存"
            : "账号属性已保存"
          : IS_LIVE
            ? "管理员账号已创建"
            : "管理员账号已创建，请向账号使用者发放初始密码。",
      );
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      ensureTenantEditable();
      const body = { is_active: selected.is_active === false };
      ensureAccountChange(selected, body);
      if (IS_LIVE) {
        await api.updateUser(tenantId, selected.id, body);
        remote.reload();
      } else {
        update("accounts", (prev) =>
          prev.map((a) => (a.id === selected.id ? { ...a, ...body } : a)),
        );
        if (!body.is_active)
          platform((p) => ({
            sessions: (p.sessions || []).map((s) =>
              s.user_id === selected.id ? { ...s, is_active: false } : s,
            ),
          }));
        audit(
          body.is_active ? "启用账号" : "停用账号",
          "user",
          selected.id,
          "permission",
          selected.username,
          tenantId,
        );
      }
      notify(body.is_active ? "账号已启用" : "账号已停用");
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function resetPassword(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      ensureTenantEditable();
      if (selected.id === session.user.id)
        throw new Error("不能从管理列表重置当前登录账号的密码。");
      const form = new FormData(e.currentTarget);
      const password = accountPasswordChange(form, { required: true });
      ensureAccountChange(selected, {});
      if (IS_LIVE) {
        await api.updateUser(tenantId, selected.id, { password });
        remote.reload();
      } else {
        await demoPasswordService().setPassword(session.user, selected, {
          password,
          confirmation: form.get("password_confirmation"),
        });
        update("accounts", (prev) =>
          prev.map((a) =>
            a.id === selected.id
              ? {
                  ...a,
                  force_password_change: false,
                  password_reset_at: new Date().toISOString(),
                }
              : a,
          ),
        );
        platform((p) => ({
          sessions: (p.sessions || []).map((s) =>
            s.user_id === selected.id ? { ...s, is_active: false } : s,
          ),
        }));
        audit(
          "重置账号密码",
          "user",
          selected.id,
          "permission",
          "设置新密码，保留累计自主改密次数，不保存明文密码",
          tenantId,
        );
      }
      notify("新密码已设置，请通知账号本人使用新密码登录");
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function revokeSession() {
    setError(null);
    setBusy(true);
    try {
      requireAdmin();
      const s = modal.session;
      if (s.is_current)
        throw new Error("请通过右上角退出登录结束当前会话。");
      if (IS_LIVE) {
        await accountSecurityApi.revoke(s.id, tenantId);
        sessionsRemote.reload();
        notify("登录会话已撤销");
        setModal(null);
        return;
      }
      platform((p) => ({
        sessions: (p.sessions || []).map((r) =>
          r.id === s.id
            ? { ...r, is_active: false, revoked_at: new Date().toISOString() }
            : r,
        ),
      }));
      audit(
        "撤销登录会话",
        "session",
        s.id,
        "permission",
        s.username,
        tenantId,
      );
      notify("登录会话已撤销");
      setModal(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (
    !["system_admin", "school_admin"].includes(session.user.role) ||
    !hasPermission(session, "admin.identity")
  )
    return <Denied />;
  return (
    <div className="platform-identity-page">
      <Metrics
        items={[
          [
            schoolScoped ? "本校账号" : "当前租户账号",
            accounts.length,
            UsersThree,
            selectedTenant?.name || "选择管理范围",
          ],
          [
            "有效管理员",
            accounts.filter(
              (a) => ADMIN_ROLES.includes(a.role) && a.is_active !== false,
            ).length,
            ShieldCheck,
            "角色与组织范围一致",
          ],
          schoolScoped
            ? [
                "已停用账号",
                accounts.filter((a) => a.is_active === false).length,
                Key,
                "停用账号保留原有业务记录",
              ]
            : [
                "活跃会话",
                sessions.filter((s) => s.is_active !== false).length,
                Key,
                IS_LIVE ? "登录会话，最多展示最近500条" : "仅展示当前工作区的登录记录",
              ],
        ]}
      />
      <section className="panel workspace-panel">
        <PageHeader
          title={schoolScoped ? "本校账号管理" : "账号与权限"}
          subtitle={
            schoolScoped
              ? "维护本校账号信息、业务角色、组织归属、启停状态与密码"
              : "维护各类账号的基本信息、业务角色、组织归属、访问状态与密码"
          }
          action={
            !schoolScoped && (
              <button
                className="button primary"
                disabled={
                  !selectedTenant ||
                  selectedTenant.is_active === false ||
                  remote.loading
                }
                onClick={() => open("edit")}
              >
                <Plus size={18} />
                管理员开户
              </button>
            )
          }
        />
        <div className="identity-tenant-scope">
          <Buildings size={20} />
          <label>
            当前管理范围
            {schoolScoped ? (
              <strong>{selectedTenant?.name || "本校"}</strong>
            ) : (
              <select
                aria-label="账号管理租户"
                value={tenantId}
                onChange={(e) => {
                  setTenantId(e.target.value);
                  setQuery("");
                  setRoleFilter("");
                }}
              >
                {tenants.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.is_active === false ? "（已停用）" : ""}
                  </option>
                ))}
              </select>
            )}
          </label>
          <Badge tone={selectedTenant?.is_active === false ? "orange" : "red"}>
            {isPlatform ? "平台全局" : "学校数据范围"}
          </Badge>
        </div>
        {!schoolScoped && (
          <Tabs
            items={[
              { id: "accounts", label: "账号与授权" },
              { id: "sessions", label: "登录会话" },
              {
                id: "requests",
                label: `改密申请${pendingPasswordRequests ? `（${pendingPasswordRequests}）` : ""}`,
              },
              ...(IS_LIVE ? [{ id: "business-requests", label: "业务角色申请" }] : []),
            ]}
            active={tab}
            onChange={setTab}
          />
        )}
        <div className="table-toolbar">
          <SearchInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              tab === "sessions" ? "搜索账号或客户端" : "搜索账号或姓名"
            }
          />
          {tab === "accounts" && (
            <Select
              label="账号角色"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="">全部角色</option>
              {Object.entries(ROLE_INFO)
                .filter(([id]) => !schoolScoped || id !== "system_admin")
                .map(([id, role]) => (
                  <option key={id} value={id}>
                    {role.label}
                  </option>
                ))}
            </Select>
          )}
          <span className="toolbar-spacer" />
          <span className="muted">
            {tab === "accounts"
              ? `共 ${rows.length} 个账号`
              : tab === "requests"
                ? `待审核 ${pendingPasswordRequests} 条`
                : tab === "sessions" ? `共 ${sessions.length} 条会话` : "按当前学校范围办理"}
          </span>
        </div>
        {(remote.error || tenantsRemote.error) && (
          <ErrorBox
            error={remote.error || tenantsRemote.error}
            retry={() => {
              remote.reload();
              tenantsRemote.reload();
            }}
          />
        )}
        {tab === "business-requests" ? <LiveSchoolBusiness key={tenantId} mode="permissions" tenantId={tenantId} /> : tab === "requests" ? (
          <PasswordRequests key={tenantId} tenantId={tenantId} query={query} />
        ) : tab === "accounts" ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {[
                    "账号 / 姓名",
                    "系统角色",
                    "组织授权范围",
                    "状态",
                    "安全状态",
                    "操作",
                  ].map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.name}</strong>
                      <small className="cell-subtext">{a.username}</small>
                    </td>
                    <td>
                      <Badge tone="blue">
                        {ROLE_INFO[a.role]?.label || a.role}
                      </Badge>
                    </td>
                    <td>
                      {a.org_name ||
                        orgs.find((o) => o.id === a.org_unit_id)?.name ||
                        (a.role === "system_admin"
                          ? "平台全局"
                          : a.org_unit_id || "未授权")}
                    </td>
                    <td>
                      <StateBadge active={a.is_active} />
                    </td>
                    <td>
                      {a.force_password_change ? (
                        <Badge tone="orange">需修改密码</Badge>
                      ) : (
                        <span className="muted">常规</span>
                      )}
                    </td>
                    <td>
                      <div className="identity-row-actions">
                        <button
                          className="text-button link"
                          onClick={() => open("detail", a)}
                        >
                          详情
                        </button>
                        <button
                          className="text-button link"
                          disabled={selectedTenant?.is_active === false}
                          onClick={() => open("edit", a)}
                        >
                          编辑
                        </button>
                        <button
                          className="text-button link"
                          disabled={
                            a.id === session.user.id ||
                            selectedTenant?.is_active === false
                          }
                          onClick={() => open("reset", a)}
                        >
                          重置密码
                        </button>
                        <button
                          className="text-button link"
                          disabled={
                            a.id === session.user.id ||
                            selectedTenant?.is_active === false
                          }
                          onClick={() => open("toggle", a)}
                        >
                          {a.is_active === false ? "启用" : "停用"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {remote.loading && <Loading />}
            {!rows.length && !remote.loading && (
              <Empty
                title="当前范围暂无账号"
                description={
                  schoolScoped
                    ? "请调整筛选条件，或联系平台管理员开通账号。"
                    : "选择学校或开通管理员账号。"
                }
              />
            )}
          </div>
        ) : (
          <div className="table-scroll">
            {sessionsRemote.error && <ErrorBox error={sessionsRemote.error} />}
            {sessionsRemote.loading && <Loading />}
            <table>
              <thead>
                <tr>
                  {[
                    "账号",
                    "客户端",
                    "登录 IP",
                    "登录时间",
                    "会话状态",
                    "操作",
                  ].map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td>{s.username}</td>
                    <td>{s.client_label || "浏览器"}</td>
                    <td>{s.ip || "—"}</td>
                    <td>{dateTime(s.created_at || s.last_seen_at)}</td>
                    <td>
                      <Badge tone={s.is_active !== false ? "green" : "gray"}>
                        {s.is_active !== false ? "有效" : "已撤销"}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="text-button link"
                        disabled={
                          s.is_active === false ||
                          s.is_current
                        }
                        onClick={() => {
                          setError(null);
                          setModal({ mode: "revoke", session: s });
                        }}
                      >
                        撤销会话
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!sessions.length && <Empty title="当前范围暂无会话记录" />}
          </div>
        )}
        <p className="page-note">
          {schoolScoped
            ? "仅管理本校账号，账号开户由平台管理员办理。"
            : "所有账号均可编辑属性，"}
          修改保留审计记录，原密码不展示；本人档案绑定、当前账号权限和最后一位有效管理员受保护。
        </p>
      </section>
      {modal && (
        <Modal
          title={
            {
              edit: selected ? "编辑账号属性" : "管理员开户",
              detail: "账号详情",
              reset: "重置账号密码",
              toggle: selected?.is_active === false ? "启用账号" : "停用账号",
              revoke: "撤销登录会话",
            }[modal.mode]
          }
          wide={modal.mode === "edit"}
          onClose={() => !busy && setModal(null)}
        >
          {error && <ErrorBox error={error} />}
          {modal.mode === "edit" ? (
            <form onSubmit={save}>
              <p className="identity-form-scope">
                <Buildings size={18} />
                {selectedTenant?.name}
              </p>
              <div className="form-grid">
                <Field label="登录账号" required>
                  <input
                    name="username"
                    required
                    pattern="\S+"
                    maxLength={50}
                    readOnly={!!selected}
                    defaultValue={selected?.username || ""}
                    autoComplete="off"
                  />
                  {selected && (
                    <small>登录账号作为身份标识，创建后保持不变。</small>
                  )}
                </Field>
                <Field label="姓名" required>
                  <input
                    name="name"
                    required
                    maxLength={50}
                    defaultValue={selected?.name || ""}
                  />
                </Field>
                <Field
                  label={selected ? "业务角色" : "管理员角色"}
                  required
                  full
                >
                  <select
                    name="role"
                    disabled={editingSelf}
                    value={formRole}
                    onChange={(e) => setFormRole(e.target.value)}
                  >
                    {roles.map((r) => (
                      <option value={r} key={r}>
                        {ROLE_INFO[r].label}
                      </option>
                    ))}
                  </select>
                </Field>
                {formRole !== "system_admin" && (
                  <Field
                    label={
                      ["member", "applicant"].includes(formRole)
                        ? "组织归属"
                        : "组织授权范围"
                    }
                    required
                    full
                  >
                    <select
                      key={formRole}
                      name="org_unit_id"
                      disabled={!!personalOrgLocked || editingSelf}
                      required
                      defaultValue={
                        personalOrgLocked || selected?.role === formRole
                          ? selected.org_unit_id
                          : ""
                      }
                    >
                      <option value="" disabled>
                        请选择组织
                      </option>
                      {orgOptions.map((o) => (
                        <option value={o.id} key={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                    {!orgOptions.length && (
                      <small>该学校尚无此类组织，请先维护学校组织结构。</small>
                    )}
                    {personalOrgLocked && (
                      <small>
                        已关联本人档案，组织调整须与档案归属保持一致。
                      </small>
                    )}
                  </Field>
                )}
                {selected && (
                  <Field label="账号状态" required full>
                    <select
                      name="is_active"
                      disabled={editingSelf}
                      defaultValue={String(selected.is_active !== false)}
                    >
                      <option value="true">启用</option>
                      <option value="false">停用</option>
                    </select>
                    {editingSelf && (
                      <small>
                        当前登录账号可修改姓名与密码；修改密码后需重新登录。
                      </small>
                    )}
                  </Field>
                )}
                {selected && (
                  <AccountPasswordFields key={selected.id} disabled={busy} />
                )}
                {!selected &&
                  (IS_LIVE ? (
                    <Field label="初始密码" required full>
                      <input
                        name="password"
                        required
                        type="password"
                        minLength={8}
                        maxLength={72}
                        autoComplete="new-password"
                      />
                    </Field>
                  ) : (
                    <p className="inline-note field full">
                      新账号初始密码为123456，请通知账号使用者登录后及时修改。
                    </p>
                  ))}
              </div>
              <FormActions
                busy={busy}
                close={() => setModal(null)}
                label={selected ? "保存修改" : "创建管理员"}
              />
            </form>
          ) : modal.mode === "detail" ? (
            <>
              <div className="identity-detail-banner">
                <UsersThree size={30} />
                <div>
                  <h3>{selected.name}</h3>
                  <p>{selected.username}</p>
                </div>
                <StateBadge active={selected.is_active} />
              </div>
              <dl className="identity-details">
                <dt>学校租户</dt>
                <dd>{selectedTenant?.name}</dd>
                <dt>系统角色</dt>
                <dd>{ROLE_INFO[selected.role]?.label || selected.role}</dd>
                <dt>组织范围</dt>
                <dd>
                  {selected.org_name ||
                    orgs.find((o) => o.id === selected.org_unit_id)?.name ||
                    "平台全局"}
                </dd>
                <dt>本人档案绑定</dt>
                <dd>{selected.profile_id ? "已明确绑定" : "无本人档案绑定"}</dd>
                <dt>密码安全</dt>
                <dd>
                  {selected.force_password_change
                    ? "已标记需修改密码"
                    : "不展示密码信息"}
                </dd>
              </dl>
              <div className="modal-actions">
                <button
                  className="button primary"
                  disabled={selectedTenant?.is_active === false}
                  onClick={() => open("edit", selected)}
                >
                  编辑账号属性
                </button>
              </div>
            </>
          ) : modal.mode === "reset" ? (
            <form onSubmit={resetPassword}>
              <p>
                为{" "}
                <strong>
                  {selected.name}（{selected.username}）
                </strong>{" "}
                重置密码。
              </p>
              <AccountPasswordFields
                key={selected.id}
                required
                disabled={busy}
              />
              <p className="inline-note">
                重置密码保留累计自主改密次数。请通过校内可靠渠道通知账号本人。
              </p>
              <FormActions
                busy={busy}
                close={() => setModal(null)}
                label="确认重置"
              />
            </form>
          ) : modal.mode === "toggle" ? (
            <>
              <p>
                {selected.is_active === false ? "启用" : "停用"}账号{" "}
                <strong>
                  {selected.name}（{selected.username}）
                </strong>
                ？
              </p>
              <p className="muted">
                {selected.is_active === false
                  ? "启用后可按已有角色与组织范围访问。"
                  : "停用后该账号无法登录，现有业务记录保留。"}
              </p>
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => setModal(null)}
                  disabled={busy}
                >
                  取消
                </button>
                <button
                  className="button primary"
                  onClick={toggle}
                  disabled={busy}
                >
                  {busy ? "正在处理…" : "确认操作"}
                </button>
              </div>
            </>
          ) : (
            <>
              <p>
                撤销账号 <strong>{modal.session.username}</strong> 在{" "}
                {modal.session.client_label} 的登录会话？
              </p>
              <p className="muted">该会话将显示为已撤销，其他会话不受影响。</p>
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => setModal(null)}
                >
                  取消
                </button>
                <button className="button primary" onClick={revokeSession} disabled={busy}>
                  确认撤销
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

const AUDIT_CATEGORIES = {
  login: "登录日志",
  permission: "权限变更",
  operation: "关键操作",
  material: "材料访问与导出",
  anomaly: "异常访问",
};
function auditCategory(row) {
  if (row.category) return row.category;
  if (row.result === "denied" || row.result === "failed") return "anomaly";
  if (/login|logout|登录|登出/.test(row.action)) return "login";
  if (
    /user|permission|role|session/.test(row.resource_type) ||
    /授权|权限|账号|密码/.test(row.action)
  )
    return "permission";
  if (
    /material|export|download|file/.test(
      `${row.resource_type} ${row.action}`,
    ) ||
    /材料|导出|下载/.test(row.action)
  )
    return "material";
  return "operation";
}
export function PlatformAudit() {
  const { session, routeParams, data, audit, notify } = useIdentity();
  const passwordState = usePasswordState(session.user, { admin: true });
  const [query, setQuery] = useState(""),
    [category, setCategory] = useState(routeParams.category || ""),
    [result, setResult] = useState(
      IS_LIVE && routeParams.category === "anomaly" ? "denied" : "",
    ),
    [tenantId, setTenantId] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [page, setPage] = useState(1),
    [modal, setModal] = useState(null),
    [applied, setApplied] = useState(
      IS_LIVE && routeParams.category === "anomaly" ? { result: "denied" } : {},
    ),
    [formError, setFormError] = useState(null),
    [exporting, setExporting] = useState(false);
  useEffect(() => {
    if (routeParams.category) {
      setCategory(routeParams.category);
      setPage(1);
      if (IS_LIVE && routeParams.category === "anomaly") {
        setResult("denied");
        setApplied({ result: "denied" });
      }
    }
  }, [routeParams.category]);
  const tenantsRemote = useRemote(api.tenants, [session.user.id]);
  const tenants = IS_LIVE ? list(tenantsRemote.value) : data.tenants;
  const remote = useRemote(
    () => api.audit({ ...applied, page, page_size: 20 }),
    [JSON.stringify(applied), page, session.user.id],
  );
  const filtered = (
    IS_LIVE
      ? list(remote.value)
      : [...passwordState.audit, ...data.auditEntries]
  ).filter(
    (r) =>
      IS_LIVE ||
      ((!query ||
        `${r.action} ${r.user_name || ""} ${r.request_id || ""} ${r.resource_id || ""}`.includes(
          query,
        )) &&
        (!category ||
          (category === "anomaly"
            ? ["failed", "denied"].includes(r.result) ||
              r.category === "anomaly"
            : auditCategory(r) === category)) &&
        (!result || r.result === result) &&
        (!tenantId || r.tenant_id === tenantId) &&
        (!start ||
          new Date(r.created_at).getTime() >=
            new Date(`${start}T00:00:00`).getTime()) &&
        (!end ||
          new Date(r.created_at).getTime() <=
            new Date(`${end}T23:59:59.999`).getTime())),
  );
  const rows = IS_LIVE ? filtered : filtered.slice((page - 1) * 20, page * 20),
    total = IS_LIVE ? remote.value?.total || 0 : filtered.length;
  function apply(e) {
    e.preventDefault();
    setFormError(null);
    if (start && end && start > end) {
      setFormError(new Error("开始日期不能晚于结束日期。"));
      return;
    }
    setPage(1);
    setApplied({
      ...(query ? { action: query } : {}),
      ...(result ? { result } : {}),
      ...(tenantId ? { tenant_id: tenantId } : {}),
      ...(start
        ? { start_at: new Date(`${start}T00:00:00`).toISOString() }
        : {}),
      ...(end ? { end_at: new Date(`${end}T23:59:59.999`).toISOString() } : {}),
    });
  }
  async function exportLogs() {
    setExporting(true);
    setFormError(null);
    try {
      if (session.user.role !== "system_admin")
        throw new Error("仅平台管理员可以导出平台审计。");
      if (start && end && start > end)
        throw new Error("开始日期不能晚于结束日期。");
      if (IS_LIVE)
        downloadBlob(await api.exportAudit(applied), "平台安全审计.zip");
      else {
        exportCsv(
          [
            [
              "时间",
              "操作人",
              "分类",
              "操作",
              "对象类型",
              "对象编号",
              "结果",
              "IP",
              "请求编号",
            ],
            ...filtered.map((r) => [
              r.created_at,
              r.user_name || r.user_id,
              AUDIT_CATEGORIES[auditCategory(r)],
              r.action,
              r.resource_type,
              r.resource_id,
              r.result,
              r.ip_address || r.ip,
              r.request_id,
            ]),
          ],
          "平台安全审计.csv",
        );
        audit(
          "导出平台安全审计",
          "audit_export",
          crypto.randomUUID(),
          "material",
          `导出${filtered.length}条摘要记录`,
        );
      }
      notify("审计记录已导出");
    } catch (e) {
      setFormError(e);
    } finally {
      setExporting(false);
    }
  }
  if (session.user.role !== "system_admin") return <Denied />;
  return (
    <div className="platform-identity-page">
      <section className="panel workspace-panel">
        <PageHeader
          title="安全审计"
          subtitle="回溯登录、授权与关键操作，查询异常访问和材料导出轨迹"
          action={
            <button
              className="button secondary"
              disabled={exporting || remote.loading}
              onClick={exportLogs}
            >
              <DownloadSimple size={18} />
              {exporting ? "正在导出…" : "导出当前查询"}
            </button>
          }
        />
        {!IS_LIVE && (
          <Tabs
            items={[
              { id: "", label: "全部日志" },
              ...Object.entries(AUDIT_CATEGORIES).map(([id, label]) => ({
                id,
                label,
              })),
            ]}
            active={category}
            onChange={(v) => {
              setCategory(v);
              setPage(1);
            }}
          />
        )}
        <form className="identity-audit-filters" onSubmit={apply}>
          <SearchInput
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!IS_LIVE) setPage(1);
            }}
            placeholder={IS_LIVE ? "操作名称" : "搜索操作、操作人或请求编号"}
          />
          <Select
            label="审计租户"
            value={tenantId}
            onChange={(e) => {
              setTenantId(e.target.value);
              if (!IS_LIVE) setPage(1);
            }}
          >
            <option value="">全部授权租户</option>
            {tenants.map((t) => (
              <option value={t.id} key={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
          <Select
            label="操作结果"
            value={result}
            onChange={(e) => {
              setResult(e.target.value);
              if (!IS_LIVE) setPage(1);
            }}
          >
            <option value="">全部结果</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="denied">拒绝</option>
          </Select>
          <label>
            开始日期
            <input
              type="date"
              value={start}
              onChange={(e) => {
                setStart(e.target.value);
                if (!IS_LIVE) setPage(1);
              }}
              aria-label="审计开始日期"
            />
          </label>
          <label>
            结束日期
            <input
              type="date"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value);
                if (!IS_LIVE) setPage(1);
              }}
              aria-label="审计结束日期"
            />
          </label>
          <button className="button primary">查询日志</button>
        </form>
        {IS_LIVE && (
          <p className="page-note">
            可按操作名称、处理结果、学校及日期查询。分类标签仅筛选当前已加载记录，导出范围以已提交的查询条件为准。
          </p>
        )}
        {(formError || remote.error || tenantsRemote.error) && (
          <ErrorBox
            error={formError || remote.error || tenantsRemote.error}
            retry={remote.error ? remote.reload : undefined}
          />
        )}
        <div className="identity-audit-summary">
          <ShieldCheck size={18} />
          {remote.value?.scope_note ||
            "审计记录仅展示操作摘要；不展示材料正文与密码。"}
          <span>共 {total} 条记录</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {[
                  "操作时间",
                  "操作人",
                  "分类 / 操作",
                  "访问对象",
                  "结果",
                  "来源 IP",
                  "操作",
                ].map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="numeric">{dateTime(r.created_at)}</td>
                  <td>{r.user_name || r.user_id || "未登录用户"}</td>
                  <td>
                    <small className="cell-subtext">
                      {AUDIT_CATEGORIES[auditCategory(r)]}
                    </small>
                    {r.action}
                  </td>
                  <td>
                    {r.resource_type || "—"}
                    <small className="cell-subtext identity-truncate">
                      {r.resource_id || "—"}
                    </small>
                  </td>
                  <td>
                    <Badge
                      tone={
                        r.result === "success"
                          ? "green"
                          : r.result === "denied"
                            ? "orange"
                            : "red"
                      }
                    >
                      {{ success: "成功", denied: "拒绝", failed: "失败" }[
                        r.result
                      ] || r.result}
                    </Badge>
                  </td>
                  <td>{r.ip_address || r.ip || "—"}</td>
                  <td>
                    <button
                      className="text-button link"
                      onClick={() => setModal(r)}
                    >
                      查看详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {remote.loading && <Loading />}
          {!rows.length && !remote.loading && (
            <Empty
              title="暂无符合条件的审计记录"
              description="调整查询时间、操作名称或结果后重试。"
            />
          )}
        </div>
        <Pagination
          page={page}
          pages={Math.max(1, Math.ceil(total / 20))}
          total={total}
          onChange={setPage}
        />
      </section>
      {modal && (
        <Modal title="审计记录详情" wide onClose={() => setModal(null)}>
          <div className="identity-detail-banner">
            <ShieldCheck size={29} />
            <div>
              <h3>{modal.action}</h3>
              <p>{dateTime(modal.created_at)}</p>
            </div>
            <Badge tone={modal.result === "success" ? "green" : "orange"}>
              {{ success: "成功", denied: "拒绝", failed: "失败" }[
                modal.result
              ] || modal.result}
            </Badge>
          </div>
          <dl className="identity-details">
            <dt>操作人</dt>
            <dd>{modal.user_name || modal.user_id || "未登录用户"}</dd>
            <dt>日志分类</dt>
            <dd>{AUDIT_CATEGORIES[auditCategory(modal)]}</dd>
            <dt>租户范围</dt>
            <dd>
              {tenants.find((t) => t.id === modal.tenant_id)?.name ||
                modal.tenant_id ||
                "按当前账号授权范围确定"}
            </dd>
            <dt>对象类型</dt>
            <dd>{modal.resource_type}</dd>
            <dt>对象编号</dt>
            <dd>{modal.resource_id || "—"}</dd>
            <dt>来源 IP</dt>
            <dd>{modal.ip_address || modal.ip || "未记录"}</dd>
            <dt>请求编号</dt>
            <dd>{modal.request_id || "—"}</dd>
            <dt>数据级别</dt>
            <dd>{modal.data_level || "—"}</dd>
          </dl>
          {modal.detail && <p className="inline-note">{modal.detail}</p>}
          {(modal.old_value || modal.new_value) && (
            <p className="inline-note">
              该记录包含变更前后信息。当前界面显示脱敏操作摘要；原始字段不在此展开。
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
