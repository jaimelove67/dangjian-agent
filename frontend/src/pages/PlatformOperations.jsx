import { useEffect, useState } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  CheckCircle,
  WarningCircle,
  Database,
  HardDrives,
  ShieldCheck,
  GearSix,
  Key,
  EnvelopeSimple,
  Cpu,
  SlidersHorizontal,
  Clock,
  FileText,
  DownloadSimple,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { newAudit } from "../role-data";
import { platformOpsApi, validatePlatformConfig } from "../platform-ops-api";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  Modal,
  Field,
  Badge,
  ErrorBox,
  Empty,
  Loading,
  Select,
  downloadBlob,
} from "../components";
import "../platform-ops.css";
import { LiveBackups } from "./LiveBackups";

export const DEFAULT_PLATFORM_CONFIG = {
  auth: {
    password_login: true,
    sso_enabled: false,
    sso_issuer: "",
    session_minutes: 120,
    mfa_required: false,
  },
  notifications: {
    in_app: true,
    email_enabled: false,
    sender_email: "",
    webhook_enabled: false,
  },
  uploads: {
    max_file_mb: 20,
    allowed_extensions: ["pdf", "docx", "txt", "md", "png", "jpg", "jpeg"],
    retention_days: 365,
  },
  model: {
    provider: "qwen",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model_name: "qwen-plus",
    timeout_seconds: 60,
    enabled: true,
    credential_configured: false,
  },
  general: {
    platform_name: "高校智慧党建平台",
    support_email: "",
    timezone: "Asia/Shanghai",
    maintenance_mode: false,
  },
};
const emptyPlatform = {
  services: [],
  incidents: [],
  jobs: [],
  backups: [],
  storage: null,
  config: DEFAULT_PLATFORM_CONFIG,
  configSavedAt: {},
};
const operationTabs = [
  { id: "overview", label: "运行概览" },
  { id: "incidents", label: "接口异常" },
  { id: "jobs", label: "文件与任务" },
  { id: "backups", label: "备份与恢复" },
];
const JOB_STATUS = {
  failed: "失败",
  completed: "已完成",
  succeeded: "已完成",
  done: "已完成",
  processing: "处理中",
  running: "处理中",
  pending: "等待执行",
  queued: "等待执行",
  retry: "等待重试",
  dead: "已终止",
};
const CHECK_NAMES = {
  database: "数据库",
  redis: "缓存",
  schema: "数据结构",
  models: "模型服务",
  encryption: "数据加密",
  audit_storage: "审计存储",
  jwt_secret: "认证密钥",
  model_warm: "模型预热",
  runtime_role: "运行角色",
  school_admission: "学校准入",
};
const CHECK_LABELS = {
  healthy: "正常",
  unhealthy: "异常",
  unknown: "未知",
  configuration_required: "待配置",
  migration_required: "待迁移",
  unverified: "未验证",
  ready: "就绪",
  ok: "正常",
};
const localTime = (date) =>
  date ? new Date(date).toLocaleString("zh-CN", { hour12: false }) : "—";
const tone = (status) =>
  ["healthy", "completed", "succeeded", "done", "resolved", "ok"].includes(
    status,
  )
    ? "green"
    : ["failed", "offline", "high", "dead"].includes(status)
      ? "red"
      : "orange";
function Notice({ children }) {
  return (
    <div className="pops-notice">
      <ShieldCheck size={18} />
      <p>{children}</p>
    </div>
  );
}
function Metric({ icon: Icon, value, label, note, color = "red" }) {
  return (
    <div className="pops-metric panel">
      <div className={`pops-metric-icon ${color}`}>
        <Icon size={25} weight="duotone" />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </div>
    </div>
  );
}
function useOperations() {
  const { session } = useApp();
  const [remote, setRemote] = useState(null),
    [error, setError] = useState(null);
  const [loading, setLoading] = useState(IS_LIVE),
    [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setLoading(true);
    setError(null);
    Promise.allSettled([
      platformOpsApi.operations(),
      platformOpsApi.jobs(),
      platformOpsApi.runLogs(),
      platformOpsApi.health(),
    ])
      .then((results) => {
        if (!active) return;
        const keys = ["operations", "jobs", "logs", "health"];
        setRemote(
          Object.fromEntries(
            results.map((result, i) => [
              keys[i],
              result.status === "fulfilled" ? result.value : null,
            ]),
          ),
        );
        const failure = results.find((r) => r.status === "rejected");
        if (failure) setError(failure.reason);
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
  }, [refresh, session.user.id]);
  return { remote, error, loading, reload: () => setRefresh((v) => v + 1) };
}

export function PlatformOperations() {
  const { session, routeParams } = useApp();
  const { data, update, notify } = useStore();
  const p = { ...emptyPlatform, ...data.platform };
  const { remote, error, loading, reload } = useOperations();
  const [tab, setTab] = useState(
      () =>
        ({ 接口异常: "incidents", 异步任务: "jobs", 备份恢复: "backups" })[
          routeParams?.tab
        ] ||
        (operationTabs.some((t) => t.id === routeParams?.tab)
          ? routeParams.tab
          : "overview"),
    ),
    [filter, setFilter] = useState("");
  const [modal, setModal] = useState(null),
    [formError, setFormError] = useState(null);
  const jobs = IS_LIVE ? remote?.jobs?.items || [] : p.jobs;
  const incidents = IS_LIVE ? remote?.logs?.items || [] : p.incidents;
  const failed = IS_LIVE
    ? Object.entries(remote?.operations?.jobs || {})
        .filter(([key]) => ["failed", "dead"].includes(key))
        .reduce((n, [, count]) => n + Number(count || 0), 0)
    : jobs.filter((j) => j.status === "failed").length;
  const openIncidents = IS_LIVE
    ? (remote?.operations?.alerts || []).reduce(
        (n, alert) => n + Number(alert.count || 0),
        0,
      )
    : incidents.filter((r) => r.status !== "resolved").length;
  const storagePercent = p.storage
    ? Math.round((p.storage.used_gb / p.storage.capacity_gb) * 100)
    : 0;
  function audit(action, type, id) {
    update("auditEntries", (rows) => [
      newAudit(session.user, action, type, id),
      ...rows,
    ]);
  }
  function closeModal() {
    setModal(null);
    setFormError(null);
  }
  function retryJob(id) {
    if (IS_LIVE) return;
    const job = p.jobs.find((j) => j.id === id);
    if (!job || job.status !== "failed") {
      setFormError(new Error("任务状态已变化，请关闭后重新查看。"));
      return;
    }
    update("platform", (prev) => ({
      ...prev,
      jobs: prev.jobs.map((j) =>
        j.id === id
          ? {
              ...j,
              status: "completed",
              error: "",
              attempts: (j.attempts || 0) + 1,
              finished_at: new Date().toISOString(),
            }
          : j,
      ),
    }));
    audit("platform.job.retry", "async_job", id);
    closeModal();
    notify("任务处理记录已更新。");
  }
  function createBackup(event) {
    event.preventDefault();
    if (IS_LIVE) return;
    const name = String(
      new FormData(event.currentTarget).get("name") || "",
    ).trim();
    if (!name) {
      setFormError(new Error("请填写备份名称。"));
      return;
    }
    const backup = {
      id: crypto.randomUUID(),
      name,
      status: "completed",
      size_mb: 0,
      created_at: new Date().toISOString(),
      scope: "配置与业务索引记录",
      restore_drills: [],
      checksum: "",
      record_count: data.members.length + data.meetings.length,
    };
    update("platform", (prev) => ({
      ...prev,
      backups: [backup, ...(prev.backups || [])],
    }));
    audit("platform.backup.create", "backup_record", backup.id);
    closeModal();
    notify("备份信息已登记。");
  }
  function runRestore(event) {
    event.preventDefault();
    if (IS_LIVE) return;
    const form = new FormData(event.currentTarget);
    if (form.get("confirmation") !== "恢复演练") {
      setFormError(new Error("请输入“恢复演练”后继续。"));
      return;
    }
    const backup = p.backups.find((r) => r.id === modal.backup.id);
    if (!backup || backup.status !== "completed") {
      setFormError(new Error("该备份当前不可演练，请重新选择。"));
      return;
    }
    const drill = {
      id: crypto.randomUUID(),
      created_at: new Date().toISOString(),
      operator: session.user.name,
      result: "passed",
      note: String(form.get("note") || "").trim(),
    };
    update("platform", (prev) => ({
      ...prev,
      backups: prev.backups.map((r) =>
        r.id === backup.id
          ? { ...r, restore_drills: [drill, ...(r.restore_drills || [])] }
          : r,
      ),
    }));
    audit("platform.backup.restore_drill", "backup_record", backup.id);
    closeModal();
    notify("恢复演练记录已保存，请以实际执行结果为准。");
  }
  const visibleJobs = jobs.filter((j) => !filter || j.status === filter);
  return (
    <div className="pops-workspace">
      <PageHeader
        title="系统运维"
        subtitle="查看平台运行情况，跟进异常与后台任务。"
        action={
          <button
            className="button secondary"
            onClick={() =>
              IS_LIVE ? reload() : notify("工作区状态已刷新。")
            }
          >
            <ArrowClockwise size={16} />
            刷新状态
          </button>
        }
      />
      {IS_LIVE && (
        <Notice>
          运行汇总仅覆盖当前登录租户；任务列表仅显示本人提交的任务。告警来源为近
          展示近24小时的运行与审计情况；容量监控和任务重试暂不可用，备份请进入“备份与恢复”办理。
        </Notice>
      )}
      {error && <ErrorBox error={error} retry={reload} />}
      <div className="pops-metrics">
        <Metric
          icon={ShieldCheck}
          label="服务健康"
          value={
            IS_LIVE
              ? remote?.health
                ? remote.health.status === "ready"
                  ? "已就绪"
                  : "需处理"
                : "—"
              : `${p.services.filter((s) => s.status === "healthy").length}/${p.services.length}`
          }
          note={IS_LIVE ? "就绪检查结果" : "关键服务正常"}
          color="green"
        />
        <Metric
          icon={WarningCircle}
          label="异常告警"
          value={IS_LIVE && !remote?.operations ? "—" : openIncidents}
          note={IS_LIVE ? "服务告警统计" : "等待跟进的异常"}
        />
        <Metric
          icon={Clock}
          label="失败任务"
          value={IS_LIVE && !remote?.operations ? "—" : failed}
          note={IS_LIVE ? "当前租户任务汇总" : "查看原因并登记处理结果"}
          color="orange"
        />
        <Metric
          icon={HardDrives}
          label="存储使用率"
          value={IS_LIVE || !p.storage ? "—" : `${storagePercent}%`}
          note={
            IS_LIVE
              ? "容量监控暂不可用"
              : p.storage
                ? `${p.storage.used_gb} / ${p.storage.capacity_gb} GB`
                : "暂无容量记录"
          }
          color="blue"
        />
      </div>
      <section className="panel pops-main">
        <Tabs
          items={operationTabs}
          active={tab}
          onChange={(id) => {
            setTab(id);
            setFilter("");
          }}
        />
        {loading ? (
          <Loading />
        ) : tab === "overview" ? (
          <div className="pops-overview">
            <section className="pops-service-section">
              <div className="pops-section-heading">
                <h2>关键服务</h2>
                <Badge tone={IS_LIVE ? "blue" : "green"}>
                  {IS_LIVE ? "就绪探测" : "本地工作区状态"}
                </Badge>
              </div>
              {IS_LIVE ? (
                <>
                  <div className="pops-live-health">
                    <ShieldCheck size={32} />
                    <div>
                      <h3>
                        {remote?.health
                          ? remote.health.status === "ready"
                            ? "关键服务依赖已就绪"
                            : "部分服务依赖尚未就绪"
                          : "尚未获取就绪状态"}
                      </h3>
                      <p>模型预热属于观察项；“未验证”不等于服务不可用。</p>
                    </div>
                  </div>
                  <div className="pops-health-checks">
                    {Object.entries(remote?.health?.checks || {}).map(
                      ([key, raw]) => {
                        const status =
                          typeof raw === "string"
                            ? raw
                            : raw?.status || "unknown";
                        return (
                          <div key={key}>
                            <span>{CHECK_NAMES[key] || key}</span>
                            <Badge
                              tone={
                                status === "healthy" || status === "ok"
                                  ? "green"
                                  : status === "unhealthy"
                                    ? "red"
                                    : "orange"
                              }
                            >
                              {CHECK_LABELS[status] || status}
                            </Badge>
                          </div>
                        );
                      },
                    )}
                  </div>
                </>
              ) : (
                <div className="pops-service-grid">
                  {p.services.map((service) => (
                    <article className="pops-service" key={service.id}>
                      <div>
                        <span className={`pops-status-dot ${service.status}`} />
                        <h3>{service.name}</h3>
                        <Badge tone={tone(service.status)}>
                          {{
                            healthy: "正常",
                            warning: "需关注",
                            offline: "不可用",
                          }[service.status] || service.status}
                        </Badge>
                      </div>
                      <p>{service.description}</p>
                      <footer>
                        <span>响应 {service.latency ?? "—"} ms</span>
                        <span>检查于 {localTime(service.checked_at)}</span>
                      </footer>
                    </article>
                  ))}
                </div>
              )}
            </section>
            <div className="pops-overview-bottom">
              <section className="pops-storage">
                <h2>存储容量</h2>
                {!IS_LIVE && p.storage ? (
                  <>
                    <div className="pops-capacity">
                      <strong>
                        {p.storage.used_gb}
                        <small> GB 已使用</small>
                      </strong>
                      <span>总容量 {p.storage.capacity_gb} GB</span>
                    </div>
                    <div
                      className="pops-capacity-track"
                      role="progressbar"
                      aria-label="存储使用率"
                      aria-valuenow={Math.min(storagePercent, 100)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                    >
                      <i
                        style={{ width: `${Math.min(storagePercent, 100)}%` }}
                      />
                    </div>
                    <div className="pops-storage-legend">
                      <span>
                        <i />
                        材料文件 {p.storage.material_gb} GB
                      </span>
                      <span>
                        <i />
                        备份文件 {p.storage.backup_gb} GB
                      </span>
                      <span>
                        其他{" "}
                        {Math.max(
                          0,
                          p.storage.used_gb -
                            p.storage.material_gb -
                            p.storage.backup_gb,
                        )}{" "}
                        GB
                      </span>
                    </div>
                  </>
                ) : (
                  <p className="pops-muted">存储容量监控暂不可用，请联系运维人员核查。</p>
                )}
              </section>
              <section className="pops-follow-up">
                <h2>需要处理</h2>
                <button onClick={() => setTab("incidents")}>
                  <span>
                    <WarningCircle size={18} />
                    接口异常与告警
                  </span>
                  <strong>
                    {IS_LIVE && !remote?.operations ? "—" : openIncidents}
                    <ArrowRight size={16} />
                  </strong>
                </button>
                <button onClick={() => setTab("jobs")}>
                  <span>
                    <FileText size={18} />
                    失败后台任务
                  </span>
                  <strong>
                    {IS_LIVE && !remote?.operations ? "—" : failed}
                    <ArrowRight size={16} />
                  </strong>
                </button>
                <button onClick={() => setTab("backups")}>
                  <span>
                    <Database size={18} />
                    备份与恢复演练
                  </span>
                  <strong>
                    {IS_LIVE ? "查看任务" : p.backups.length}
                    <ArrowRight size={16} />
                  </strong>
                </button>
              </section>
            </div>
          </div>
        ) : tab === "incidents" ? (
          <div className="pops-tab-content">
            {IS_LIVE && remote?.operations?.alerts?.length > 0 && (
              <div className="pops-alert-summary">
                <h2>近 24 小时审计告警</h2>
                {remote.operations.alerts.map((alert, i) => (
                  <div key={`${alert.action}-${alert.result}-${i}`}>
                    <WarningCircle size={17} />
                    <span>{alert.action} · {alert.result}</span>
                    <strong>{alert.count} 次</strong>
                  </div>
                ))}
                <p>按访问拒绝、登录失败或高频导出规则聚合，不代表逐次接口调用明细。</p>
              </div>
            )}
            <div className="pops-section-heading">
              <h2>{IS_LIVE ? "失败运行日志" : "接口异常记录"}</h2>
              <span className="pops-muted">
                {IS_LIVE
                  ? `共 ${remote?.logs?.total || 0} 条，展示最近 40 条`
                  : `共 ${incidents.length} 条`}
              </span>
            </div>
            {incidents.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{IS_LIVE ? "事件 / 请求" : "异常接口"}</th>
                      <th>异常说明</th>
                      <th>{IS_LIVE ? "耗时" : "发生次数"}</th>
                      <th>最近发生</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((r) => (
                      <tr key={r.id}>
                        <td className="pops-mono">
                          {IS_LIVE ? r.event_text || r.event : r.endpoint}
                          <small className="cell-subtext">
                            {r.request_id || r.id}
                          </small>
                        </td>
                        <td>{r.message || r.error_code || "未返回异常原因"}</td>
                        <td>
                          {IS_LIVE ? `${r.duration_ms ?? "—"} ms` : r.count}
                        </td>
                        <td>{localTime(r.last_seen || r.created_at)}</td>
                        <td>
                          <Badge tone={IS_LIVE ? "red" : tone(r.status)}>
                            {IS_LIVE
                              ? "失败"
                              : r.status === "resolved"
                                ? "已处理"
                                : "待处理"}
                          </Badge>
                        </td>
                        <td>
                          <button
                            className="text-button link"
                            onClick={() =>
                              setModal({ type: "incident", incident: r })
                            }
                          >
                            查看详情
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                title="暂无异常记录"
                description={
                  IS_LIVE
                    ? "未查询到当前权限范围内的失败运行日志。"
                    : "接口异常处理后仍保留记录供追溯。"
                }
              />
            )}
          </div>
        ) : tab === "jobs" ? (
          <div className="pops-tab-content">
            <div className="pops-section-heading">
              <div>
                <h2>异步处理任务</h2>
                <p>
                  {IS_LIVE
                    ? "显示本人提交的最近40条任务；失败任务请联系运维人员处理。"
                    : "查看文件解析、向量索引与提醒任务的执行结果。"}
                </p>
              </div>
              <Select
                label="任务状态"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="">全部状态</option>
                {[...new Set(jobs.map((j) => j.status))].map((status) => (
                  <option key={status} value={status}>
                    {JOB_STATUS[status] || status}
                  </option>
                ))}
              </Select>
            </div>
            {visibleJobs.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>任务名称</th>
                      <th>状态</th>
                      <th>尝试次数</th>
                      <th>创建时间</th>
                      <th>处理结果</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleJobs.map((job) => (
                      <tr key={job.id}>
                        <td>
                          {job.name ||
                            {
                              embedding: "文件向量索引",
                              member_reminders: "党员发展提醒",
                              assessment_reminders: "考核任务提醒",
                            }[job.kind] ||
                            job.kind}
                          <small className="cell-subtext">
                            {job.tenant_name || job.id}
                          </small>
                        </td>
                        <td>
                          <Badge tone={tone(job.status)}>
                            {JOB_STATUS[job.status] || job.status}
                          </Badge>
                        </td>
                        <td>
                          {job.attempts || 0}
                          {job.max_attempts ? ` / ${job.max_attempts}` : ""}
                        </td>
                        <td>{localTime(job.created_at)}</td>
                        <td className="pops-job-result">
                          {job.error ||
                            job.error_code ||
                            (job.status === "completed" ||
                            job.status === "succeeded" || job.status === "done"
                              ? "处理完成"
                              : "等待处理结果")}
                        </td>
                        <td>
                          <button
                            className="text-button link"
                            onClick={() => setModal({ type: "job", job })}
                          >
                            详情
                          </button>
                          {!IS_LIVE && job.status === "failed" && (
                            <button
                              className="text-button link separated-action"
                              onClick={() => setModal({ type: "retry", job })}
                            >
                              登记处理结果
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                title="暂无此状态的任务"
                description="可以调整状态筛选查看其他任务。"
              />
            )}
          </div>
        ) : (
          <div className="pops-tab-content">
            {IS_LIVE && <LiveBackups />}
            {!IS_LIVE && <div className="pops-section-heading">
              <div>
                <h2>备份记录</h2>
                <p>
                  {IS_LIVE
                    ? "备份服务尚未配置，请联系运维人员。"
                    : "登记备份信息及恢复演练结果，数据备份状态以实际执行结果为准。"}
                </p>
              </div>
              {!IS_LIVE && (
                <button
                  className="button primary"
                  onClick={() => setModal({ type: "create-backup" })}
                >
                  <Database size={16} />
                  登记备份
                </button>
              )}
            </div>}
            {IS_LIVE ? null : p.backups.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>备份名称</th>
                      <th>备份范围</th>
                      <th>创建时间</th>
                      <th>状态</th>
                      <th>最近演练</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.backups.map((backup) => (
                      <tr key={backup.id}>
                        <td>
                          <span className="file-name">
                            <Database size={20} />
                            {backup.name}
                          </span>
                        </td>
                        <td>{backup.scope}</td>
                        <td>{localTime(backup.created_at)}</td>
                        <td>
                          <Badge tone={tone(backup.status)}>
                            {backup.status === "completed"
                              ? "记录已就绪"
                              : backup.status}
                          </Badge>
                        </td>
                        <td>
                          {localTime(backup.restore_drills?.[0]?.created_at)}
                        </td>
                        <td>
                          <button
                            className="text-button link"
                            onClick={() => setModal({ type: "backup", backup })}
                          >
                            详情
                          </button>
                          <button
                            className="text-button link separated-action"
                            disabled={backup.status !== "completed"}
                            onClick={() =>
                              setModal({ type: "restore", backup })
                            }
                          >
                            登记演练结果
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                title="暂无备份记录"
                description="请先登记备份信息，再记录恢复演练结果。"
              />
            )}
          </div>
        )}
      </section>
      {modal && (
        <Modal
          title={
            {
              incident: "异常详情",
              job: "任务详情",
              retry: "登记任务处理结果",
              "create-backup": "登记备份信息",
              backup: "备份详情",
              restore: "登记恢复演练结果",
            }[modal.type]
          }
          onClose={closeModal}
        >
          {formError && <ErrorBox error={formError} />}
          {modal.type === "incident" ? (
            <>
              <dl className="pops-detail">
                <dt>事件</dt>
                <dd>
                  {modal.incident.endpoint ||
                    modal.incident.event_text ||
                    modal.incident.event}
                </dd>
                <dt>异常说明</dt>
                <dd>
                  {modal.incident.message ||
                    modal.incident.error_code ||
                    "未返回"}
                </dd>
                <dt>发生时间</dt>
                <dd>
                  {localTime(
                    modal.incident.last_seen || modal.incident.created_at,
                  )}
                </dd>
                <dt>请求编号</dt>
                <dd className="pops-mono">
                  {modal.incident.request_id || modal.incident.id}
                </dd>
                <dt>{IS_LIVE ? "执行状态" : "处理状态"}</dt>
                <dd>
                  {IS_LIVE ? "执行失败" : modal.incident.status === "resolved" ? "已处理" : "待处理"}
                </dd>
              </dl>
              {!IS_LIVE && modal.incident.status !== "resolved" && (
                <div className="modal-actions">
                  <button
                    className="button primary"
                    onClick={() => {
                      const id = modal.incident.id;
                      update("platform", (prev) => ({
                        ...prev,
                        incidents: prev.incidents.map((r) =>
                          r.id === id
                            ? {
                                ...r,
                                status: "resolved",
                                resolved_at: new Date().toISOString(),
                              }
                            : r,
                        ),
                      }));
                      audit("platform.incident.resolve", "incident", id);
                      closeModal();
                      notify("已标记处理，记录已保留。");
                    }}
                  >
                    标记已处理
                  </button>
                </div>
              )}
            </>
          ) : modal.type === "job" || modal.type === "retry" ? (
            <>
              <dl className="pops-detail">
                <dt>任务</dt>
                <dd>{modal.job.name || modal.job.kind}</dd>
                <dt>任务编号</dt>
                <dd className="pops-mono">{modal.job.id}</dd>
                <dt>状态</dt>
                <dd>{JOB_STATUS[modal.job.status] || modal.job.status}</dd>
                <dt>尝试次数</dt>
                <dd>{modal.job.attempts || 0}</dd>
                <dt>错误原因</dt>
                <dd>{modal.job.error || modal.job.error_code || "无"}</dd>
                <dt>创建时间</dt>
                <dd>{localTime(modal.job.created_at)}</dd>
              </dl>
              {modal.type === "retry" && (
                <>
                  <Notice>
                    本次仅更新任务处理记录，请核对执行结果后登记。
                  </Notice>
                  <div className="modal-actions">
                    <button className="button secondary" onClick={closeModal}>
                      取消
                    </button>
                    <button
                      className="button primary"
                      onClick={() => retryJob(modal.job.id)}
                    >
                      <ArrowClockwise size={16} />
                      保存处理记录
                    </button>
                  </div>
                </>
              )}
            </>
          ) : modal.type === "create-backup" ? (
            <form onSubmit={createBackup}>
              <Notice>
                本次仅登记备份信息，尚未执行数据备份；请另行核对备份文件。
              </Notice>
              <Field label="备份名称" required>
                <input
                  name="name"
                  maxLength={80}
                  required
                  defaultValue={`手动备份 ${new Date().toLocaleDateString("zh-CN")}`}
                />
              </Field>
              <div className="modal-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={closeModal}
                >
                  取消
                </button>
                <button className="button primary" type="submit">
                  创建记录
                </button>
              </div>
            </form>
          ) : modal.type === "restore" ? (
            <form onSubmit={runRestore}>
              <Notice>
                本次登记恢复演练记录，请核对实际执行结果后保存。
              </Notice>
              <dl className="pops-detail">
                <dt>选中备份</dt>
                <dd>{modal.backup.name}</dd>
                <dt>创建时间</dt>
                <dd>{localTime(modal.backup.created_at)}</dd>
              </dl>
              <Field label="演练说明">
                <textarea
                  name="note"
                  maxLength={300}
                  rows={3}
                  placeholder="填写本次演练目的或核对事项"
                />
              </Field>
              <Field label="输入“恢复演练”确认" required>
                <input
                  name="confirmation"
                  required
                  autoComplete="off"
                  placeholder="恢复演练"
                />
              </Field>
              <div className="modal-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={closeModal}
                >
                  取消
                </button>
                <button className="button primary" type="submit">
                  保存记录
                </button>
              </div>
            </form>
          ) : (
            <>
              <dl className="pops-detail">
                <dt>备份名称</dt>
                <dd>{modal.backup.name}</dd>
                <dt>备份范围</dt>
                <dd>{modal.backup.scope}</dd>
                <dt>校验标识</dt>
                <dd className="pops-mono">
                  {modal.backup.checksum || "未登记"}
                </dd>
                <dt>演练次数</dt>
                <dd>{modal.backup.restore_drills?.length || 0}</dd>
              </dl>
              <h3 className="pops-modal-subtitle">演练记录</h3>
              {modal.backup.restore_drills?.length ? (
                <ul className="pops-drill-list">
                  {modal.backup.restore_drills.map((drill) => (
                    <li key={drill.id}>
                      <CheckCircle size={17} />
                      <div>
                        <strong>
                          {localTime(drill.created_at)} · {drill.operator}
                        </strong>
                        <p>
                          {drill.note || "恢复演练记录已登记，执行结果待核对。"}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="pops-muted">尚未进行恢复演练。</p>
              )}
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => {
                    downloadBlob(
                      new Blob(
                        [
                          JSON.stringify(
                            {
                              ...modal.backup,
                              type: "backup_record_metadata",
                              includes_original_files: false,
                            },
                            null,
                            2,
                          ),
                        ],
                        { type: "application/json" },
                      ),
                      `backup-${modal.backup.id}.json`,
                    );
                    audit(
                      "platform.backup.metadata_export",
                      "backup_record",
                      modal.backup.id,
                    );
                  }}
                >
                  <DownloadSimple size={16} />
                  导出备份记录
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

const CONFIG_SECTIONS = [
  {
    id: "auth",
    label: "登录认证",
    description: "登录方式与会话策略",
    icon: Key,
  },
  {
    id: "notifications",
    label: "通知渠道",
    description: "站内、邮件与消息推送",
    icon: EnvelopeSimple,
  },
  {
    id: "uploads",
    label: "文件上传",
    description: "文件格式、大小与保留期限",
    icon: FileText,
  },
  {
    id: "model",
    label: "模型服务",
    description: "模型连接与请求参数",
    icon: Cpu,
  },
  {
    id: "general",
    label: "通用参数",
    description: "平台名称与运行方式",
    icon: SlidersHorizontal,
  },
];
function Toggle({ label, description, checked, onChange, disabled = false }) {
  return (
    <label className="pops-toggle-row">
      <span>
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={Boolean(checked)}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        aria-label={label}
      />
    </label>
  );
}
export function PlatformConfiguration() {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [section, setSection] = useState("auth"),
    [draft, setDraft] = useState(null),
    [error, setError] = useState(null),
    [confirm, setConfirm] = useState(null),
    [liveDirty, setLiveDirty] = useState(false);
  const config = { ...DEFAULT_PLATFORM_CONFIG, ...data.platform?.config };
  const current = { ...DEFAULT_PLATFORM_CONFIG[section], ...config[section] };
  const values = draft || current;
  const dirty = IS_LIVE
    ? liveDirty
    : draft !== null && JSON.stringify(values) !== JSON.stringify(current);
  const selected = CONFIG_SECTIONS.find((s) => s.id === section);
  function field(name, value) {
    setDraft((v) => ({ ...(v || current), [name]: value }));
    setError(null);
  }
  function changeSection(id) {
    if (id === section) return;
    if (dirty) setConfirm({ type: "leave", id });
    else {
      setSection(id);
      setDraft(null);
      setError(null);
    }
  }
  function persist() {
    if (IS_LIVE) return;
    const message = validatePlatformConfig(section, values);
    if (message) {
      setError(new Error(message));
      setConfirm(null);
      return;
    }
    const normalized = { ...values };
    for (const name of [
      "session_minutes",
      "max_file_mb",
      "retention_days",
      "timeout_seconds",
    ])
      if (Object.hasOwn(normalized, name))
        normalized[name] = Number(normalized[name]);
    for (const [name, value] of Object.entries(normalized))
      if (typeof value === "string") normalized[name] = value.trim();
    // Secret-bearing fields are deliberately excluded from the draft and storage.
    delete normalized.api_key;
    delete normalized.password;
    delete normalized.webhook_url;
    update("platform", (prev) => ({
      ...prev,
      config: { ...prev?.config, [section]: normalized },
      configSavedAt: {
        ...prev?.configSavedAt,
        [section]: new Date().toISOString(),
      },
    }));
    update("auditEntries", (rows) => [
      newAudit(
        session.user,
        `platform.config.${section}.update`,
        "platform_config",
        section,
      ),
      ...rows,
    ]);
    setDraft(null);
    setError(null);
    setConfirm(null);
    notify(`${selected.label}配置已保存在当前工作区。`);
  }
  function submit(event) {
    event.preventDefault();
    const message = validatePlatformConfig(section, values);
    if (message) {
      setError(new Error(message));
      return;
    }
    if (
      section === "auth" ||
      (section === "general" &&
        values.maintenance_mode !== current.maintenance_mode)
    )
      setConfirm({ type: "save" });
    else persist();
  }
  return (
    <div className="pops-workspace">
      <PageHeader
        title="平台配置"
        subtitle="按分区维护平台规则、服务接入与通用参数。"
        action={<Badge tone="red">平台级配置</Badge>}
      />
      <Notice>
        {IS_LIVE
          ? "按当前授权范围读取生效策略。认证方式、上传限制和通知渠道暂不支持在此修改，请联系平台管理员。"
          : "配置保存在当前工作区，实际运行参数以已生效的系统配置为准。"}
      </Notice>
      <div className="pops-config-layout">
        <nav className="panel pops-config-nav" aria-label="平台配置分类">
          {CONFIG_SECTIONS.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              className={section === id ? "active" : ""}
              onClick={() => changeSection(id)}
            >
              <Icon size={21} />
              <span>
                <strong>{label}</strong>
                <small>{description}</small>
              </span>
              <ArrowRight size={14} />
            </button>
          ))}
        </nav>
        <section className="panel pops-config-panel">
          <div className="pops-config-heading">
            <div>
              <selected.icon size={22} />
              <h2>{selected.label}</h2>
            </div>
            {!IS_LIVE && (
              <span className={`pops-save-indicator ${dirty ? "dirty" : ""}`}>
                {dirty ? (
                  "有未保存的修改"
                ) : data.platform?.configSavedAt?.[section] ? (
                  <>
                    <CheckCircle size={15} />
                    已保存 · {localTime(data.platform.configSavedAt[section])}
                  </>
                ) : (
                  "尚未修改"
                )}
              </span>
            )}
          </div>
          {IS_LIVE ? (
            <LiveConfiguration
              key={section}
              section={section}
              onDirty={setLiveDirty}
            />
          ) : (
            <form onSubmit={submit} className="pops-config-form">
              {error && <ErrorBox error={error} />}
              {section === "auth" ? (
                <>
                  <p className="pops-section-description">
                    设置管理员与成员可用的登录方式，避免关闭所有登录入口。
                  </p>
                  <Toggle
                    label="账号密码登录"
                    description="允许使用平台账号与密码登录"
                    checked={values.password_login}
                    onChange={(v) => field("password_login", v)}
                  />
                  <Toggle
                    label="学校统一身份认证"
                    description="通过学校身份提供方完成登录"
                    checked={values.sso_enabled}
                    onChange={(v) => field("sso_enabled", v)}
                  />
                  {values.sso_enabled && (
                    <Field label="身份提供方地址" required>
                      <input
                        type="url"
                        value={values.sso_issuer}
                        onChange={(e) => field("sso_issuer", e.target.value)}
                        placeholder="https://sso.example.edu.cn"
                      />
                    </Field>
                  )}
                  <div className="form-grid">
                    <Field label="会话有效期（分钟）" required>
                      <input
                        type="number"
                        min={15}
                        max={1440}
                        step={1}
                        value={values.session_minutes}
                        onChange={(e) =>
                          field("session_minutes", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                  <Toggle
                    label="管理员多因素认证"
                    description="身份验证服务尚未配置，当前仅记录二次验证要求。"
                    checked={values.mfa_required}
                    onChange={(v) => field("mfa_required", v)}
                  />
                </>
              ) : section === "notifications" ? (
                <>
                  <p className="pops-section-description">
                    维护事件通知的可用渠道，收件对象由各业务流程确定。
                  </p>
                  <Toggle
                    label="站内消息"
                    description="在平台通知中心显示待办和系统消息"
                    checked={values.in_app}
                    onChange={(v) => field("in_app", v)}
                  />
                  <Toggle
                    label="邮件通知"
                    description="启用后需在服务端配置邮件服务器凭据"
                    checked={values.email_enabled}
                    onChange={(v) => field("email_enabled", v)}
                  />
                  {values.email_enabled && (
                    <Field label="发件邮箱" required>
                      <input
                        type="email"
                        value={values.sender_email}
                        onChange={(e) => field("sender_email", e.target.value)}
                        placeholder="notice@example.edu.cn"
                      />
                    </Field>
                  )}
                  <Toggle
                    label="消息推送渠道"
                    description="启用服务端预先配置的 Webhook 通道"
                    checked={values.webhook_enabled}
                    onChange={(v) => field("webhook_enabled", v)}
                  />
                  <Notice>
                    邮件密码、Webhook
                    地址与签名密钥通过服务端环境配置管理，前端不接收或保存。
                  </Notice>
                </>
              ) : section === "uploads" ? (
                <>
                  <p className="pops-section-description">
                    文件须通过权限、格式与大小检查后才能保存。这里维护平台默认上传策略。
                  </p>
                  <div className="form-grid">
                    <Field label="单个文件上限（MB）" required>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={1}
                        value={values.max_file_mb}
                        onChange={(e) => field("max_file_mb", e.target.value)}
                      />
                    </Field>
                    <Field label="文件保留期限（天）" required>
                      <input
                        type="number"
                        min={30}
                        max={3650}
                        step={1}
                        value={values.retention_days}
                        onChange={(e) =>
                          field("retention_days", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                  <fieldset className="pops-extension-options">
                    <legend>
                      允许的文件格式 <b>*</b>
                    </legend>
                    {["pdf", "docx", "txt", "md", "png", "jpg", "jpeg"].map(
                      (ext) => (
                        <label key={ext}>
                          <input
                            type="checkbox"
                            checked={values.allowed_extensions.includes(ext)}
                            onChange={(e) =>
                              field(
                                "allowed_extensions",
                                e.target.checked
                                  ? [...values.allowed_extensions, ext]
                                  : values.allowed_extensions.filter(
                                      (r) => r !== ext,
                                    ),
                              )
                            }
                          />
                          <span>.{ext}</span>
                        </label>
                      ),
                    )}
                  </fieldset>
                  <Notice>
                    上传文件须符合平台文件类型与大小限制，具体要求以当前生效的上传策略为准。
                  </Notice>
                </>
              ) : section === "model" ? (
                <>
                  <p className="pops-section-description">
                    设置党建智能体使用的服务地址和模型名称，凭据由服务端管理。
                  </p>
                  <Toggle
                    label="启用模型服务"
                    description="允许智能体向已配置的模型服务发起请求"
                    checked={values.enabled}
                    onChange={(v) => field("enabled", v)}
                  />
                  <div className="form-grid">
                    <Field label="服务提供方" required>
                      <select
                        value={values.provider}
                        onChange={(e) => field("provider", e.target.value)}
                      >
                        <option value="qwen">阿里云百炼 · 通义千问</option>
                        <option value="openai_compatible">
                          OpenAI 兼容服务
                        </option>
                        <option value="private">校内模型服务</option>
                      </select>
                    </Field>
                    <Field label="模型名称" required>
                      <input
                        value={values.model_name}
                        maxLength={100}
                        onChange={(e) => field("model_name", e.target.value)}
                      />
                    </Field>
                    <Field label="服务地址" required full>
                      <input
                        type="url"
                        value={values.base_url}
                        onChange={(e) => field("base_url", e.target.value)}
                        placeholder="https://.../v1"
                      />
                    </Field>
                    <Field label="请求超时（秒）" required>
                      <input
                        type="number"
                        min={5}
                        max={300}
                        step={1}
                        value={values.timeout_seconds}
                        onChange={(e) =>
                          field("timeout_seconds", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                  <div className="pops-credential-state">
                    <Key size={20} />
                    <div>
                      <strong>服务端凭据</strong>
                      <p>密钥仅通过服务端环境变量配置，本页不保存密钥。</p>
                    </div>
                    <Badge
                      tone={values.credential_configured ? "green" : "orange"}
                    >
                      {values.credential_configured
                        ? "已登记配置状态"
                        : "凭据状态暂不可用"}
                    </Badge>
                  </div>
                </>
              ) : (
                <>
                  <p className="pops-section-description">
                    维护平台显示信息、服务时间与维护开关。
                  </p>
                  <div className="form-grid">
                    <Field label="平台名称" required full>
                      <input
                        value={values.platform_name}
                        maxLength={40}
                        onChange={(e) => field("platform_name", e.target.value)}
                      />
                    </Field>
                    <Field label="服务邮箱">
                      <input
                        type="email"
                        value={values.support_email}
                        onChange={(e) => field("support_email", e.target.value)}
                        placeholder="support@example.edu.cn"
                      />
                    </Field>
                    <Field label="平台时区">
                      <select
                        value={values.timezone}
                        onChange={(e) => field("timezone", e.target.value)}
                      >
                        <option value="Asia/Shanghai">
                          北京时间 · UTC+08:00
                        </option>
                        <option value="UTC">协调世界时 · UTC</option>
                      </select>
                    </Field>
                  </div>
                  <Toggle
                    label="维护模式"
                    description="当前仅保存维护状态说明，服务启停由运维人员执行。"
                    checked={values.maintenance_mode}
                    onChange={(v) => field("maintenance_mode", v)}
                  />
                </>
              )}
              <div className="pops-config-actions">
                <span>仅保存当前分区</span>
                <button
                  className="button secondary"
                  type="button"
                  disabled={!dirty}
                  onClick={() => {
                    setDraft(null);
                    setError(null);
                  }}
                >
                  撤销修改
                </button>
                <button
                  className="button primary"
                  type="submit"
                  disabled={!dirty}
                >
                  <CheckCircle size={16} />
                  保存配置
                </button>
              </div>
            </form>
          )}
        </section>
      </div>
      {confirm && (
        <Modal
          title={
            confirm.type === "leave" ? "存在未保存的修改" : "确认保存平台策略"
          }
          onClose={() => setConfirm(null)}
        >
          {confirm.type === "leave" ? (
            <>
              <p>当前分区的修改尚未保存。切换后，这些修改将被丢弃。</p>
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => setConfirm(null)}
                >
                  继续编辑
                </button>
                <button
                  className="button primary"
                  onClick={() => {
                    setSection(confirm.id);
                    setDraft(null);
                    setError(null);
                    setConfirm(null);
                  }}
                >
                  放弃修改并切换
                </button>
              </div>
            </>
          ) : (
            <>
              <Notice>
                本次保存当前工作区的策略记录，平台运行规则以实际生效配置为准。
              </Notice>
              <p>确认保存“{selected.label}”中的修改？</p>
              <div className="modal-actions">
                <button
                  className="button secondary"
                  onClick={() => setConfirm(null)}
                >
                  继续编辑
                </button>
                <button className="button primary" onClick={persist}>
                  确认保存
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}

function LiveConfiguration({ section, onDirty }) {
  const { notify } = useStore();
  const [remote, setRemote] = useState(null),
    [draft, setDraft] = useState(null),
    [error, setError] = useState(null);
  const [loading, setLoading] = useState(section !== "auth"),
    [busy, setBusy] = useState(false),
    [revision, setRevision] = useState(0),
    [confirmation, setConfirmation] = useState(false);
  useEffect(() => {
    if (section === "auth") return;
    let active = true;
    setLoading(true);
    setError(null);
    setDraft(null);
    const pending =
      section === "notifications"
        ? platformOpsApi.notificationChannels()
        : section === "general"
          ? platformOpsApi.configuration()
          : section === "uploads"
            ? Promise.all([
                platformOpsApi.governance(),
                platformOpsApi.retention(),
              ]).then(([governance, retention]) => ({
                ...governance,
                report: retention,
              }))
            : platformOpsApi.governance();
    pending
      .then((value) => {
        if (active) setRemote(value);
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
  }, [section, revision]);
  const current =
    section === "model"
      ? remote?.values?.model_routes
      : section === "uploads"
        ? remote?.values?.retention
        : remote;
  const values = draft || current || {};
  const dirty = Boolean(
    draft && JSON.stringify(draft) !== JSON.stringify(current),
  );
  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  function field(name, value) {
    setDraft((prev) => ({ ...(prev || current), [name]: value }));
    setError(null);
  }
  function validate() {
    if (section === "general") {
      for (const key of ["retrieval_top_k", "rerank_top_k"])
        if (
          !Number.isInteger(Number(values[key])) ||
          Number(values[key]) < 1 ||
          Number(values[key]) > 50
        )
          return "检索数量与重排数量应为 1–50 的整数。";
      if (
        Number(values.no_evidence_threshold) < 0.05 ||
        Number(values.no_evidence_threshold) > 1 ||
        !Number.isFinite(Number(values.no_evidence_threshold))
      )
        return "无依据阈值应介于 0.05 与 1 之间。";
      for (const key of ["activist_training_days", "probationary_period_days"])
        if (
          !Number.isInteger(Number(values[key])) ||
          Number(values[key]) < 1 ||
          Number(values[key]) > 3650
        )
          return "培养与预备期应为 1–3650 的整数天数。";
    }
    if (section === "uploads")
      for (const key of ["file_days", "audit_days"])
        if (
          !Number.isInteger(Number(values[key])) ||
          Number(values[key]) < 365 ||
          Number(values[key]) > 36500
        )
          return "文件与审计记录的保留期应为 365–36500 的整数天数。";
    return "";
  }
  async function save(event) {
    event.preventDefault();
    const message = validate();
    if (message) {
      setError(new Error(message));
      setConfirmation(false);
      return;
    }
    const reason = String(
      new FormData(event.currentTarget).get("reason") || "",
    ).trim();
    if (section !== "general" && !reason) {
      setError(new Error("请填写变更原因。"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let result;
      if (section === "general") {
        const payload = Object.fromEntries(
          [
            "retrieval_top_k",
            "rerank_top_k",
            "no_evidence_threshold",
            "activist_training_days",
            "probationary_period_days",
          ].map((key) => [key, Number(values[key])]),
        );
        payload.exclude_expired_by_default = Boolean(
          values.exclude_expired_by_default,
        );
        result = await platformOpsApi.saveConfiguration(payload);
      } else {
        const key = section === "model" ? "model_routes" : "retention";
        const replacement = { ...values };
        if (key === "retention") {
          replacement.file_days = Number(replacement.file_days);
          replacement.audit_days = Number(replacement.audit_days);
        }
        result = await platformOpsApi.saveGovernance({
          expected_version: remote.version,
          reason,
          values: { ...remote.values, [key]: replacement },
        });
      }
      setRemote(result);
      setDraft(null);
      setConfirmation(false);
      notify("配置已由服务端保存。");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <Loading />;
  if (section === "auth")
    return (
      <Empty
        title="认证策略由服务端管理"
        description="登录方式、多因素认证与会话有效期需由运维人员配置。"
      />
    );
  if (!remote)
    return (
      <div className="pops-config-form">
        {error && (
          <ErrorBox error={error} retry={() => setRevision((v) => v + 1)} />
        )}
      </div>
    );
  return (
    <>
      <form
        className="pops-config-form"
        onSubmit={(event) => {
          event.preventDefault();
          const message = validate();
          if (message) setError(new Error(message));
          else setConfirmation(true);
        }}
      >
        {error && !confirmation && (
          <ErrorBox error={error} retry={() => setRevision((v) => v + 1)} />
        )}
        {section === "notifications" ? (
          <>
            <p className="pops-section-description">
              渠道由服务端预先配置。本页展示配置状态与事件路由，不发送测试通知。
            </p>
            <div className="pops-readonly-list">
              {(remote.items || []).map((channel) => (
                <div key={channel.name}>
                  <div>
                    <strong>{channel.name}</strong>
                    <p>{channel.description}</p>
                  </div>
                  <Badge tone={channel.configured ? "green" : "orange"}>
                    {channel.configured ? "已配置" : "未配置"}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="pops-readonly-list">
              {Object.entries(remote.routes || {}).map(([event, channels]) => (
                <div key={event}>
                  <strong>{event}</strong>
                  <span className="pops-muted">
                    {channels.join("、") || "未指定渠道"}
                  </span>
                </div>
              ))}
            </div>
            <Notice>
              最大重试次数：{remote.max_attempts ?? "—"}
              。渠道凭据与路由需由运维人员配置。
            </Notice>
          </>
        ) : section === "model" ? (
          <>
            <p className="pops-section-description">
              为不同模型能力选择服务端已经登记的部署。模型地址、API
              密钥与部署注册由服务端管理。
            </p>
            <div className="form-grid">
              {Object.entries({
                llm: "问答生成模型",
                embedding: "文本向量模型",
                reranker: "检索重排模型",
              }).map(([kind, label]) => (
                <Field key={kind} label={label} required>
                  <select
                    value={values[kind] || ""}
                    onChange={(event) => field(kind, event.target.value)}
                  >
                    <option value="">未指定</option>
                    {(remote.model_catalog || [])
                      .filter(
                        (model) =>
                          model.type === kind ||
                          (kind === "llm" && model.type === "chat"),
                      )
                      .map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.id} · {model.provider || model.deployment}
                        </option>
                      ))}
                  </select>
                </Field>
              ))}
            </div>
            <Notice>
              当前版本 {String(remote.version)}
              。此处仅修改路由，不开启外部或敏感模型的准入。
            </Notice>
          </>
        ) : section === "uploads" ? (
          <>
            <Notice>
              上传文件类型与大小需由运维人员配置。此处保存文件保留期限，文件清理须另行办理。
            </Notice>
            <div className="form-grid">
              <Field label="文件保留期（天）" required>
                <input
                  type="number"
                  min={365}
                  max={36500}
                  value={values.file_days ?? ""}
                  onChange={(e) => field("file_days", e.target.value)}
                />
              </Field>
              <Field label="审计保留期（天）" required>
                <input
                  type="number"
                  min={365}
                  max={36500}
                  value={values.audit_days ?? ""}
                  onChange={(e) => field("audit_days", e.target.value)}
                />
              </Field>
              <Field label="物理清理策略" full>
                <select
                  value={values.physical_purge || "disabled"}
                  onChange={(e) => field("physical_purge", e.target.value)}
                >
                  <option value="disabled">禁止物理清理</option>
                  <option value="approval_required">须经人工审批</option>
                </select>
              </Field>
              <Field label="策略依据" full>
                <textarea
                  rows={3}
                  maxLength={500}
                  value={values.evidence || ""}
                  onChange={(e) => field("evidence", e.target.value)}
                />
              </Field>
            </div>
            <div className="pops-readonly-list">
              <div>
                <strong>已登记文件</strong>
                <span>{remote.report?.files?.total ?? "—"}</span>
              </div>
              <div>
                <strong>已删除文档标记</strong>
                <span>{remote.report?.files?.deleted_docs_total ?? "—"}</span>
              </div>
            </div>
            <p className="pops-muted">
              统计时间：{localTime(remote.report?.as_of)}
              。文件数量不代表存储容量。
            </p>
          </>
        ) : (
          <>
            <p className="pops-section-description">
              当前租户的检索与培养周期参数。平台名称、时区和维护开关仍由服务端环境配置管理。
            </p>
            <div className="form-grid">
              <Field label="检索文档数量" required>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={values.retrieval_top_k}
                  onChange={(e) => field("retrieval_top_k", e.target.value)}
                />
              </Field>
              <Field label="重排文档数量" required>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={values.rerank_top_k}
                  onChange={(e) => field("rerank_top_k", e.target.value)}
                />
              </Field>
              <Field label="无依据阈值" required>
                <input
                  type="number"
                  min={0.05}
                  max={1}
                  step={0.01}
                  value={values.no_evidence_threshold}
                  onChange={(e) =>
                    field("no_evidence_threshold", e.target.value)
                  }
                />
              </Field>
              <Field label="积极分子培养期（天）" required>
                <input
                  type="number"
                  min={1}
                  max={3650}
                  value={values.activist_training_days}
                  onChange={(e) =>
                    field("activist_training_days", e.target.value)
                  }
                />
              </Field>
              <Field label="预备党员预备期（天）" required>
                <input
                  type="number"
                  min={1}
                  max={3650}
                  value={values.probationary_period_days}
                  onChange={(e) =>
                    field("probationary_period_days", e.target.value)
                  }
                />
              </Field>
            </div>
            <Toggle
              label="默认排除已失效资料"
              description="检索时排除已经到期的制度资料"
              checked={values.exclude_expired_by_default}
              onChange={(v) => field("exclude_expired_by_default", v)}
            />
          </>
        )}
        {section !== "notifications" && (
          <div className="pops-config-actions">
            <span>保存到当前登录租户</span>
            <button
              type="button"
              className="button secondary"
              disabled={!dirty || busy}
              onClick={() => {
                setDraft(null);
                setError(null);
              }}
            >
              撤销修改
            </button>
            <button
              type="submit"
              className="button primary"
              disabled={!dirty || busy}
            >
              保存配置
            </button>
          </div>
        )}
      </form>
      {confirmation && (
        <Modal
          title="确认修改配置"
          onClose={() => {
            if (!busy) setConfirmation(false);
          }}
        >
          <form onSubmit={save}>
            {error && <ErrorBox error={error} />}
            <Notice>
              保存后由服务端校验并生效，权限与版本冲突会返回错误。
              {section === "uploads"
                ? "此次只改保留策略，不执行文件清理。"
                : ""}
            </Notice>
            {section !== "general" && (
              <div className="pops-modal-input">
                <Field label="变更原因" required>
                  <textarea
                    name="reason"
                    required
                    maxLength={500}
                    rows={3}
                    placeholder="说明本次调整的依据与目的"
                  />
                </Field>
              </div>
            )}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => setConfirmation(false)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy} type="submit">
                {busy ? "正在保存…" : "确认保存"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
