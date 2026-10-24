import { useEffect, useState } from "react";
import {
  Pulse,
  Buildings,
  UsersThree,
  WarningCircle,
  ListChecks,
  Clock,
  ArrowRight,
  ArrowClockwise,
  CheckCircle,
  ShieldCheck,
  HardDrives,
  GearSix,
  ChartBar,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { roleApi } from "../role-api";
import { platformOpsApi } from "../platform-ops-api";
import { platformSummary } from "../platform-data";
import { usePasswordState } from "../password-hooks";
import {
  PageHeader,
  PanelTitle,
  Badge,
  ErrorBox,
  Loading,
  Empty,
} from "../components";
import "../platform-home.css";

const stateTone = { healthy: "green", warning: "orange", offline: "red" };
const stateName = { healthy: "运行正常", warning: "需关注", offline: "不可用" };
const checkNames = {
  database: "业务数据库",
  redis: "缓存与队列",
  schema: "数据库结构",
  models: "模型服务",
  encryption: "文件加密",
  audit_storage: "审计存储",
  model_warm: "模型预热",
  runtime_role: "运行角色",
  school_admission: "学校准入",
  jwt_secret: "认证密钥",
};
function numeric(value) {
  return typeof value === "number" ? value : "—";
}
export function PlatformHome() {
  const { navigate, session } = useApp();
  const { data, notify } = useStore();
  const passwordState = usePasswordState(session.user, { admin: true });
  const passwordRequests = passwordState.requests.filter((request) => request.status === "pending");
  const [remote, setRemote] = useState({});
  const [busy, setBusy] = useState(IS_LIVE);
  const [errors, setErrors] = useState([]);
  const [tick, setTick] = useState(0);
  const [updated, setUpdated] = useState(null);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setBusy(true);
    Promise.allSettled([
      roleApi.tenants(),
      roleApi.users(),
      platformOpsApi.overview(),
      platformOpsApi.health(),
    ]).then((results) => {
      if (!active) return;
      const next = {},
        failures = [];
      ["tenants", "users", "operations", "health"].forEach((key, i) => {
        if (results[i].status === "fulfilled") next[key] = results[i].value;
        else failures.push(results[i].reason);
      });
      setRemote(next);
      setErrors(failures);
      setUpdated(new Date());
      setBusy(false);
    });
    return () => {
      active = false;
    };
  }, [tick]);
  const summary = platformSummary(data),
    state = data.platform || {};
  const schools = IS_LIVE
    ? remote.tenants?.items?.filter((t) => t.tenant_type === "school") || []
    : data.tenants.filter((t) => t.tenant_type === "school");
  const incidents = IS_LIVE
    ? Array.isArray(remote.operations?.alerts)
      ? remote.operations.alerts.map((a, i) => ({
          id: a.id || String(i),
          message:
            a.message ||
            a.title ||
            `${{ login: "登录", export: "导出", login_denied: "登录拒绝" }[a.action] || a.action || "访问"} · 最近 ${a.window_hours || 24} 小时 ${a.count || 0} 次${a.result === "denied" ? "拒绝记录" : a.result === "failed" ? "失败记录" : "异常记录"}`,
          severity: a.severity || "medium",
          endpoint: a.code || a.action || "运行监测",
        }))
      : []
    : (state.incidents || []).filter((i) => i.status === "open");
  const failedJobs = IS_LIVE
    ? remote.operations?.jobs
      ? numeric(remote.operations.jobs.failed ?? 0)
      : "—"
    : (state.jobs || []).filter((j) => j.status === "failed").length;
  const failedRows = IS_LIVE
    ? []
    : (state.jobs || []).filter((j) => j.status === "failed");
  const pending = IS_LIVE
    ? remote.operations?.reviews
      ? numeric(remote.operations.reviews.pending ?? 0)
      : "—"
    : incidents.length + failedJobs + passwordRequests.length;
  const services = IS_LIVE
    ? Object.entries(remote.health?.checks || {}).map(([key, val]) => ({
        id: key,
        name: checkNames[key] || key,
        description:
          typeof val === "object"
            ? val?.detail || val?.message || "服务就绪检查"
            : String(val),
        status: ["ok", "ready", "healthy", true].includes(
          typeof val === "object" ? val?.status : val,
        )
          ? "healthy"
          : (typeof val === "object" ? val?.status : val) === "unverified"
            ? "observing"
            : "warning",
      }))
    : state.services || [];
  const normal = IS_LIVE
    ? remote.health?.status === "ready"
    : summary.healthyServices === summary.services;
  const metrics = [
    {
      name: "系统健康",
      value: IS_LIVE
        ? remote.health
          ? normal
            ? "正常"
            : "需处理"
          : "—"
        : `${summary.healthyServices}/${summary.services}`,
      hint: IS_LIVE ? "服务就绪状态" : "正常运行的服务",
      icon: Pulse,
      tone: normal ? "green" : "orange",
    },
    {
      name: "学校租户",
      value: IS_LIVE
        ? remote.tenants
          ? schools.length
          : "—"
        : summary.schools,
      hint: `${schools.filter((t) => t.is_active).length} 所已启用`,
      icon: Buildings,
      tone: "red",
    },
    {
      name: IS_LIVE ? "当前范围账号" : "启用账号",
      value: IS_LIVE
        ? remote.users?.items
          ? remote.users.items.filter((a) => a.is_active).length
          : "—"
        : summary.activeAccounts,
      hint: "按账号状态统计",
      icon: UsersThree,
      tone: "blue",
    },
    {
      name: "异常告警",
      value: IS_LIVE
        ? remote.operations
          ? incidents.length
          : "—"
        : summary.incidents,
      hint: "需要关注的事件",
      icon: WarningCircle,
      tone: incidents.length ? "orange" : "green",
    },
    {
      name: "失败任务",
      value: failedJobs,
      hint: IS_LIVE ? "当前租户的任务统计" : "核对原因后处理",
      icon: ListChecks,
      tone: "red",
    },
    {
      name: "待处理事项",
      value: pending,
      hint: IS_LIVE ? "当前租户待审核项" : "告警、失败任务与改密申请",
      icon: Clock,
      tone: "blue",
    },
  ];
  function refresh() {
    if (IS_LIVE) setTick((t) => t + 1);
    else notify("已重新读取本地运行数据");
  }
  return (
    <div className="platform-home">
      <section className="panel platform-home-heading">
        <PageHeader
          title="平台工作台"
          subtitle="集中查看运行状态，及时处理异常与平台管理事项"
          action={
            <button
              className="button secondary"
              disabled={busy}
              onClick={refresh}
            >
              <ArrowClockwise size={16} />
              刷新概览
            </button>
          }
        />
        <div className="platform-overview-status">
          <span>
            <span
              className={`platform-status-dot ${normal ? "healthy" : "warning"}`}
            />
            {busy
              ? "正在检查运行状态"
              : IS_LIVE
                ? remote.health
                  ? normal
                    ? "核心服务已就绪"
                    : "存在需要处理的运行检查"
                  : "运行状态未取得"
                : `${summary.services - summary.healthyServices} 项服务需关注，${summary.failedJobs} 个任务处理失败`}
          </span>
          <small>
            {IS_LIVE
              ? updated
                ? "更新于 " + updated.toLocaleTimeString("zh-CN")
                : "等待服务响应"
              : "工作区运行记录"}
          </small>
        </div>
      </section>
      {errors.length > 0 && <ErrorBox error={errors[0]} retry={refresh} />}
      <div className="platform-summary-grid">
        {metrics.map((m) => (
          <section className="panel" key={m.name}>
            <span className={`metric-icon ${m.tone}`}>
              <m.icon size={22} weight="duotone" />
            </span>
            <p>{m.name}</p>
            <strong>{m.value}</strong>
            <small>{m.hint}</small>
          </section>
        ))}
      </div>
      <div className="platform-home-columns">
        <section className="panel">
          <PanelTitle
            title="异常告警"
            action="查看全部"
            onAction={() => navigate("operations", { tab: "接口异常" })}
          />
          <div className="platform-alert-list">
            {incidents.slice(0, 4).map((i) => (
              <button
                key={i.id}
                onClick={() => navigate("operations", { tab: "接口异常" })}
              >
                <span
                  className={`platform-alert-icon ${i.severity === "high" ? "critical" : ""}`}
                >
                  <WarningCircle size={21} />
                </span>
                <div>
                  <h3>{i.message}</h3>
                  <p>
                    {i.endpoint}{" "}
                    {i.last_seen && "· " + i.last_seen.slice(11, 16)}
                  </p>
                </div>
                <Badge tone={i.severity === "high" ? "red" : "orange"}>
                  {i.severity === "high" ? "优先处理" : "需关注"}
                </Badge>
              </button>
            ))}
            {!incidents.length && !busy && (
              <Empty
                title={
                  IS_LIVE && !remote.operations
                    ? "尚未取得告警信息"
                    : "当前没有未处理告警"
                }
                description="运行告警与访问异常会在这里集中展示。"
              />
            )}
            {busy && <Loading />}
          </div>
        </section>
        <section className="panel">
          <PanelTitle
            title="待处理事项"
            action="进入运维"
            onAction={() => navigate("operations", { tab: "异步任务" })}
          />
          <div className="platform-pending-list">
            {passwordRequests.map((request) => <button key={request.id} onClick={() => navigate("accounts", { tenantId: request.tenant_id, tab: "改密申请" })}><ShieldCheck size={22} /><div><h3>{request.name}的改密申请</h3><p>{data.tenants.find((tenant) => tenant.id === request.tenant_id)?.name || request.tenant_id} · 等待核验并批准一次修改</p></div><ArrowRight size={16} /></button>)}
            {failedRows.map((j) => (
              <button
                key={j.id}
                onClick={() => navigate("operations", { tab: "异步任务" })}
              >
                <ListChecks size={22} />
                <div>
                  <h3>{j.name}</h3>
                  <p>
                    {j.tenant_name} · {j.error}
                  </p>
                </div>
                <ArrowRight size={16} />
              </button>
            ))}
            {!failedRows.length && (
              <div className="platform-summary-note">
                <CheckCircle size={26} />
                <p>
                  {IS_LIVE
                    ? "失败任务按当前账号授权范围统计，进入系统运维核对任务详情。"
                    : "当前没有待处理的失败任务。"}
                </p>
              </div>
            )}
            <button
              className="platform-pending-action"
              onClick={() => navigate("tenants")}
            >
              <Buildings size={19} />
              <span>核对学校租户与管理员归属</span>
              <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
      <div className="platform-home-columns">
        <section className="panel">
          <PanelTitle
            title="服务健康"
            action="查看服务状态"
            onAction={() => navigate("operations")}
          />
          <div className="platform-service-list">
            {services.map((s) => (
              <div key={s.id}>
                <span className={`platform-status-dot ${s.status}`} />
                <div>
                  <h3>{s.name}</h3>
                  <p>{s.description}</p>
                </div>
                <span className="platform-latency">
                  {s.latency != null ? s.latency + " ms" : ""}
                </span>
                <Badge tone={stateTone[s.status] || "blue"}>
                  {stateName[s.status] || "观察项"}
                </Badge>
              </div>
            ))}
            {!services.length && !busy && <Empty title="暂无服务检查结果" />}
          </div>
        </section>
        <section className="panel">
          <PanelTitle title="管理快捷入口" />
          <div className="platform-quick-grid">
            {[
              ["tenants", "租户管理", "接入学校与服务使用", Buildings],
              ["accounts", "账号与权限", "管理员与组织授权", UsersThree],
              ["configuration", "平台配置", "平台规则与服务接入", GearSix],
              ["audit", "安全审计", "操作追溯与异常查询", ShieldCheck],
            ].map(([id, title, note, Icon]) => (
              <button key={id} onClick={() => navigate(id)}>
                <Icon size={23} weight="duotone" />
                <div>
                  <h3>{title}</h3>
                  <p>{note}</p>
                </div>
                <ArrowRight size={14} />
              </button>
            ))}
          </div>
          <div className="platform-resource-summary">
            <HardDrives size={23} />
            <div>
              <p>存储使用情况</p>
              {IS_LIVE ? (
                <small>容量指标暂不可用，可前往系统运维查看相关记录。</small>
              ) : (
                <>
                  <strong>
                    {state.storage?.used_gb}{" "}
                    <small>/ {state.storage?.capacity_gb} GB</small>
                  </strong>
                  <progress
                    aria-label="平台存储使用率"
                    value={state.storage?.used_gb || 0}
                    max={state.storage?.capacity_gb || 1}
                  />
                </>
              )}
            </div>
            <button
              className="text-button link"
              onClick={() => navigate("operations", { tab: "备份恢复" })}
            >
              查看
            </button>
          </div>
        </section>
      </div>
      <section className="panel">
        <PanelTitle
          title="学校租户概览"
          action="管理租户"
          onAction={() => navigate("tenants")}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>学校名称</th>
                <th>学校管理员</th>
                <th>账号数量</th>
                <th>服务使用</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {schools.map((t) => {
                const a = data.accounts.find(
                    (a) => a.id === t.school_admin_user_id,
                  ),
                  usage = IS_LIVE
                    ? null
                    : state.usage?.find((u) => u.tenant_id === t.id);
                return (
                  <tr key={t.id}>
                    <td>
                      <span className="platform-tenant-name">
                        <Buildings size={18} />
                        {t.name}
                      </span>
                    </td>
                    <td>{IS_LIVE ? "按学校账号核对" : a?.name || "待指定"}</td>
                    <td>
                      {IS_LIVE
                        ? "—"
                        : data.accounts.filter((a) => a.tenant_id === t.id)
                            .length}
                    </td>
                    <td>
                      {usage
                        ? `${(usage.storage_bytes / 1024 ** 3).toFixed(1)} GB · ${usage.files_count} 份文件`
                        : "前往租户详情核对"}
                    </td>
                    <td>
                      <Badge tone={t.is_active ? "green" : "orange"}>
                        {t.is_active ? "已启用" : "已停用"}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="text-button link"
                        onClick={() => navigate("tenants", { tenantId: t.id })}
                      >
                        管理
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!schools.length && !busy && <Empty title="暂无学校租户" />}
        </div>
      </section>
      {IS_LIVE && (
        <div className="page-note">
          运行、任务与账号指标按当前授权范围统计；容量与学校用量暂不可用时显示“—”。
        </div>
      )}
    </div>
  );
}
