import { useEffect, useState } from "react";
import {
  Plus,
  UsersThree,
  Buildings,
  ShieldCheck,
  DownloadSimple,
  PencilSimple,
  FileText,
  ArrowRight,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { roleApi } from "../role-api";
import { ROLE_INFO, accountOrganizations, roleLabel } from "../roles";
import { newAudit } from "../role-data";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Modal,
  Field,
  Empty,
  Loading,
  ErrorBox,
  exportCsv,
  downloadBlob,
} from "../components";
export function Administration({ section }) {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [remote, setRemote] = useState([]);
  const [orgs, setOrgs] = useState(() =>
    IS_LIVE ? [] : accountOrganizations(),
  );
  const [candidates, setCandidates] = useState([]);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [createRole, setCreateRole] = useState("member");
  const [profileId, setProfileId] = useState("");
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setBusy(true);
    setError(null);
    (section === "accounts"
      ? Promise.all([
          roleApi.users(),
          roleApi.accountOrgs(),
          roleApi.memberCandidates(),
        ])
      : section === "tenants"
        ? Promise.all([roleApi.tenants()])
        : Promise.all([
            roleApi.audit({
              ...(query ? { action: query } : {}),
              ...(filter ? { result: filter } : {}),
            }),
          ])
    )
      .then(([records, options, people]) => {
        if (!active) return;
        setRemote(records.items || []);
        if (options) setOrgs(options);
        if (people) setCandidates(people);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [section, tick, filter, session.user.id]);
  const all = IS_LIVE
    ? remote
    : section === "accounts"
      ? data.accounts
      : section === "tenants"
        ? data.tenants
        : data.auditEntries.filter(
            (r) =>
              session.user.role === "system_admin" ||
              (r.tenant_id || "school-1") === session.user.tenant_id,
          );
  const rows = all.filter(
    (r) =>
      (!query ||
        `${r.name || ""} ${r.username || ""} ${r.action || ""} ${r.user_name || ""}`.includes(
          query,
        )) &&
      (!filter ||
        (section === "accounts"
          ? r.role === filter
          : section === "audit"
            ? r.result === filter
            : true)),
  );
  const people = IS_LIVE
    ? candidates
    : data.members.filter(
        (m) => !data.accounts.some((a) => a.profile_id === m.id),
      );
  const profile = people.find((m) => m.id === profileId);
  const orgOptions = orgs.filter((o) =>
    createRole === "system_admin"
      ? false
      : createRole === "school_admin"
        ? o.org_type === "school"
        : createRole === "department_admin"
          ? o.org_type === "department"
          : o.org_type === "branch",
  );
  async function saveAccount(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const f = new FormData(e.currentTarget);
      const username = f.get("username").trim(),
        name = profile?.name || f.get("name").trim(),
        password = IS_LIVE ? f.get("password") : null,
        orgId =
          createRole === "system_admin"
            ? null
            : profile?.org_unit_id || profile?.orgId || f.get("org_unit_id");
      if (!username || !name) throw new Error("请填写账号和姓名。");
      if (createRole !== "system_admin" && !orgId)
        throw new Error("请选择符合角色的组织归属。");
      if (!IS_LIVE && data.accounts.some((a) => a.username === username))
        throw new Error("账号已存在，请更换唯一账号。");
      let record;
      if (IS_LIVE) {
        if (new TextEncoder().encode(password).length > 72)
          throw new Error("密码编码不能超过 72 字节。");
        record = await roleApi.createAccount({
          username,
          name,
          password,
          role: createRole,
          org_unit_id: orgId,
          ...(profileId ? { member_id: profileId } : {}),
        });
        setTick((t) => t + 1);
      } else {
        record = {
          id: crypto.randomUUID(),
          username,
          name,
          role: createRole,
          tenant_id: "school-1",
          org_unit_id: orgId,
          org_name: orgs.find((o) => o.id === orgId)?.name || "平台级账号",
          is_active: true,
          profile_id: profileId || null,
          department:
            profile?.department ||
            (createRole === "department_admin"
              ? orgs.find((o) => o.id === orgId)?.name
              : orgs.find((o) => o.id === orgId)?.department),
        };
        update("accounts", (prev) => [record, ...prev]);
        update("auditEntries", (prev) => [
          newAudit(session.user, "创建账号", "user", record.id),
          ...prev,
        ]);
      }
      setModal(null);
      setQuery("");
      setFilter("");
      notify(
        IS_LIVE ? "账号已创建" : "账号已创建，请向账号使用者发放初始密码。",
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function saveTenant(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const f = new FormData(e.currentTarget);
      const body = {
        name: f.get("name").trim(),
        tenant_type: f.get("tenant_type"),
        parent_id: f.get("parent_id"),
      };
      if (!body.name || !body.parent_id)
        throw new Error("请填写租户名称并选择上级租户。");
      if (IS_LIVE) {
        await roleApi.createTenant(body);
        setTick((t) => t + 1);
      } else {
        if (data.tenants.some((t) => t.name === body.name))
          throw new Error("该租户名称已存在。");
        const id = crypto.randomUUID();
        update("tenants", (prev) => [
          ...prev,
          { ...body, id, is_active: true },
        ]);
        update("auditEntries", (prev) => [
          newAudit(session.user, "登记租户", "tenant", id),
          ...prev,
        ]);
      }
      setModal(null);
      setQuery("");
      notify("租户信息已登记");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function exportLogs() {
    try {
      if (IS_LIVE) {
        downloadBlob(
          await roleApi.exportAudit({
            ...(query ? { action: query } : {}),
            ...(filter ? { result: filter } : {}),
          }),
          "审计对账包.zip",
        );
      } else
        exportCsv(
          [
            ["操作人", "操作", "对象", "结果", "时间", "请求编号"],
            ...rows.map((r) => [
              r.user_name,
              r.action,
              r.resource_type,
              r.result,
              r.created_at,
              r.request_id,
            ]),
          ],
          "操作审计.csv",
        );
    } catch (e) {
      notify(e.message, "error");
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title={
          section === "accounts"
            ? "账号管理"
            : section === "tenants"
              ? "租户管理"
              : "审计日志"
        }
        subtitle={
          section === "accounts"
            ? "按真实组织归属开户，将人员身份与管理权限分开"
            : section === "tenants"
              ? "维护租户层级，明确学校与组织的管理边界"
              : "按授权范围查阅操作轨迹，保留责任与请求标识"
        }
        action={
          section === "audit" ? (
            <button className="button secondary" onClick={exportLogs}>
              <DownloadSimple size={17} />
              导出审计
            </button>
          ) : (
            <button
              className="button primary"
              onClick={() => {
                setModal("create");
                setError(null);
                setProfileId("");
                setCreateRole("member");
              }}
            >
              <Plus size={18} />
              {section === "accounts" ? "创建账号" : "登记租户"}
            </button>
          )
        }
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={
            section === "accounts"
              ? "搜索账号或姓名"
              : section === "tenants"
                ? "搜索租户名称"
                : "搜索操作或操作人"
          }
        />
        {section !== "tenants" && (
          <Select
            label={section === "accounts" ? "筛选角色" : "筛选结果"}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">
              {section === "accounts" ? "全部角色" : "全部结果"}
            </option>
            {section === "accounts"
              ? Object.entries(ROLE_INFO).map(([value, role]) => (
                  <option value={value} key={value}>
                    {role.label}
                  </option>
                ))
              : Object.entries({
                  success: "成功",
                  denied: "拒绝",
                  failed: "失败",
                }).map(([v, l]) => (
                  <option value={v} key={v}>
                    {l}
                  </option>
                ))}
          </Select>
        )}
        {IS_LIVE && section === "audit" && (
          <button
            className="button secondary"
            onClick={() => setTick((t) => t + 1)}
          >
            查询
          </button>
        )}
        <span className="toolbar-spacer" />
        <Badge tone="red">
          {section === "audit" ? "按权限查阅" : "平台管理员"}
        </Badge>
      </div>
      {error && !modal && (
        <ErrorBox error={error} retry={() => setTick((t) => t + 1)} />
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {(section === "accounts"
                ? ["账号", "姓名", "系统角色", "所属组织", "状态", "操作"]
                : section === "tenants"
                  ? ["租户名称", "类型", "上级租户", "状态", "操作"]
                  : [
                      "操作时间",
                      "操作人",
                      "操作",
                      "业务对象",
                      "结果",
                      "请求编号",
                    ]
              ).map((t) => (
                <th key={t}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                {section === "accounts" ? (
                  <>
                    <td className="numeric">{r.username}</td>
                    <td>{r.name}</td>
                    <td>
                      <Badge tone="blue">
                        {ROLE_INFO[r.role]?.label || "未识别角色"}
                      </Badge>
                    </td>
                    <td>
                      {r.org_name ||
                        orgs.find((o) => o.id === r.org_unit_id)?.name ||
                        r.org_unit_id ||
                        "平台级账号"}
                    </td>
                    <td>
                      <Badge tone={r.is_active ? "green" : "orange"}>
                        {r.is_active ? "启用" : "停用"}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="text-button link"
                        onClick={() => setModal(r)}
                      >
                        查看归属
                      </button>
                    </td>
                  </>
                ) : section === "tenants" ? (
                  <>
                    <td>
                      <span className="file-name">
                        <Buildings size={21} />
                        {r.name}
                      </span>
                    </td>
                    <td>
                      {{
                        school: "学校",
                        department: "院系",
                        branch: "支部",
                        platform: "平台",
                      }[r.tenant_type] || r.tenant_type}
                    </td>
                    <td>
                      {all.find((t) => t.id === r.parent_id)?.name || "无上级"}
                    </td>
                    <td>
                      <Badge tone={r.is_active ? "green" : "orange"}>
                        {r.is_active ? "启用" : "停用"}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="text-button link"
                        onClick={() => setModal(r)}
                      >
                        查看
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td>{r.created_at.replace("T", " ").slice(0, 19)}</td>
                    <td>{r.user_name || r.user_id}</td>
                    <td>{r.action}</td>
                    <td>{r.resource_type}</td>
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
                    <td>
                      <button
                        className="text-button link numeric"
                        onClick={() => setModal(r)}
                      >
                        {r.request_id}
                      </button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {busy && !modal && <Loading />}
        {!rows.length && !busy && <Empty />}
      </div>
      <div className="page-note">
        {section === "accounts"
          ? "账号创建不会凭姓名猜测档案。党员与申请人的本人服务需明确关联既有档案。"
          : section === "tenants"
            ? "登记租户不自动创建学校账号或授予组织权限。"
            : "审计记录保留操作摘要，不在此展示被操作对象的原文与私有材料。"}
      </div>
      {modal === "create" && (
        <Modal
          title={section === "accounts" ? "创建登录账号" : "登记租户"}
          wide
          onClose={() => !busy && setModal(null)}
        >
          <form onSubmit={section === "accounts" ? saveAccount : saveTenant}>
            <div className="form-grid">
              {section === "accounts" ? (
                <>
                  <Field label="系统角色" required full>
                    <select
                      name="role"
                      value={createRole}
                      onChange={(e) => {
                        setCreateRole(e.target.value);
                        setProfileId("");
                      }}
                    >
                      {Object.entries(ROLE_INFO).map(([value, role]) => (
                        <option value={value} key={value}>
                          {role.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {["member", "applicant"].includes(createRole) && (
                    <Field label="关联既有档案（可选）" full>
                      <select
                        value={profileId}
                        onChange={(e) => setProfileId(e.target.value)}
                      >
                        <option value="">暂不关联，开户后由组织人员核对</option>
                        {people.slice(0, 200).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} · {p.org_name || p.organization}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  <Field label="登录账号" required>
                    <input
                      name="username"
                      required
                      pattern="\S+"
                      maxLength={50}
                      autoComplete="off"
                    />
                  </Field>
                  <Field label="姓名" required>
                    <input
                      name="name"
                      key={profileId}
                      defaultValue={profile?.name || ""}
                      readOnly={!!profile}
                      required
                      maxLength={50}
                    />
                  </Field>
                  {createRole !== "system_admin" && (
                    <Field label="所属组织" required full>
                      <select
                        name="org_unit_id"
                        required
                        disabled={!!profile}
                        key={createRole + profileId}
                        defaultValue={profile?.org_unit_id || profile?.orgId}
                      >
                        {orgOptions.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  <Field
                    label={IS_LIVE ? "初始密码（8–72字节）" : "初始密码"}
                    required
                    full
                  >
                    <input
                      name="password"
                      type={IS_LIVE ? "password" : "text"}
                      required={IS_LIVE}
                      minLength={IS_LIVE ? 8 : undefined}
                      maxLength={72}
                      autoComplete="new-password"
                      defaultValue={IS_LIVE ? "" : "123456"}
                      readOnly={!IS_LIVE}
                    />
                  </Field>
                  {!IS_LIVE && (
                    <div className="inline-note field full">
                      新账号初始密码为
                      123456，请通知账号使用者登录后及时修改。
                    </div>
                  )}
                </>
              ) : (
                <>
                  <Field label="租户名称" required full>
                    <input
                      name="name"
                      required
                      maxLength={100}
                      placeholder="请输入学校或组织名称"
                    />
                  </Field>
                  <Field label="租户类型" required>
                    <select name="tenant_type">
                      <option value="school">学校</option>
                      <option value="department">院系</option>
                      <option value="branch">支部</option>
                    </select>
                  </Field>
                  <Field label="上级租户" required>
                    <select name="parent_id" required>
                      {all
                        .filter((t) => t.is_active)
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                </>
              )}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => setModal(null)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "确认创建"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal && typeof modal === "object" && (
        <Modal
          title={
            section === "accounts"
              ? "账号归属"
              : section === "tenants"
                ? "租户详情"
                : "操作记录"
          }
          onClose={() => setModal(null)}
        >
          <dl className="detail-list">
            {(section === "accounts"
              ? [
                  ["姓名", modal.name],
                  ["登录账号", modal.username],
                  ["系统角色", ROLE_INFO[modal.role]?.label],
                  [
                    "所属组织",
                    modal.org_name || modal.org_unit_id || "平台级账号",
                  ],
                  [
                    "档案关联",
                    modal.profile_id ? "已明确关联" : "以组织登记为准",
                  ],
                ]
              : section === "tenants"
                ? [
                    ["租户名称", modal.name],
                    ["租户类型", modal.tenant_type],
                    [
                      "上级租户",
                      all.find((t) => t.id === modal.parent_id)?.name ||
                        "无上级",
                    ],
                    ["状态", modal.is_active ? "启用" : "停用"],
                  ]
                : [
                    ["操作人", modal.user_name || modal.user_id],
                    ["操作", modal.action],
                    ["业务对象", modal.resource_type],
                    ["对象编号", modal.resource_id || "—"],
                    ["操作结果", modal.result],
                    ["时间", modal.created_at],
                    ["请求编号", modal.request_id],
                  ]
            ).map(([key, value]) => (
              <div className="detail-pair" key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </Modal>
      )}
    </section>
  );
}
