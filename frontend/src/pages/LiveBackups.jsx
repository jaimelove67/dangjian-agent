import { formatBusinessTime } from "../business-time";
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { request } from "../api";
import { PageHeader, Modal, downloadBlob } from "../components";
import { get, send, key, rows } from "../business-api";
import { BusinessForm, BusinessTable, ResourceState, Status, useResource } from "../components/BusinessForms";

export function LiveBackups() {
  const { notify } = useStore();
  const jobs = useResource(() => get("/admin/backups"), []);
  const [form, setForm] = useState(null), [selected, setSelected] = useState(null);
  const caps = jobs.value?.capabilities;
  const currentSelection = selected && (rows(jobs.value).find(r => r.id === selected.id) || selected);
  const active = rows(jobs.value).some(r => ["queued", "running"].includes(r.status));
  useEffect(() => { if (!active) return; const timer = setInterval(jobs.reload, 2000); return () => clearInterval(timer); }, [active]);
  function create(source) {
    const dedup = crypto.randomUUID();
    setForm({ title: source ? "执行隔离恢复演练" : "创建加密备份", fields: [{ name: "name", label: "任务名称", value: source ? `恢复演练 · ${source.name}` : `手工备份 ${new Date().toLocaleString("zh-CN")}` }, { name: "confirm_maintenance", label: "确认短暂暂停业务请求，并将恢复仅写入新隔离目标", type: "checkbox" }],
      description: source ? "从选定备份校验加密、数据哈希、原件与认证吊销记录，然后写入服务器新建的隔离数据库和目录。此页面不切换当前业务数据库。" : "备份包括当前服务数据库、认证加密原件和认证吊销记录。执行期间保留任务查询，其他业务请求稍后重试。",
      submit: async values => { if (!values.confirm_maintenance) throw new Error("请先确认维护窗口与恢复范围"); await send("/admin/backups", { ...values, dedup_key: dedup, source_id: source?.id || null }); jobs.reload(); notify("维护任务已登记，请核对实际执行结果"); },
    });
  }
  return <section className="panel workspace-panel"><PageHeader title="备份与隔离恢复" subtitle={caps?.scope || "读取受控运维能力与任务状态"} action={<button className="button primary" disabled={!caps?.enabled || !caps?.database_tools || active} onClick={() => create()}>创建加密备份</button>} />
    <ResourceState resource={jobs} />{caps && (!caps.enabled || !caps.database_tools) && <p className="inline-note">当前服务{!caps.enabled ? "尚未启用备份与恢复服务" : "缺少 PostgreSQL 备份恢复客户端"}。请先联系运维人员完成配置，再提交维护任务。</p>}
    {caps && !caps.restore_configured && <p className="inline-note">独立恢复目标尚未配置，当前不开放恢复执行。</p>}
    {caps?.restore_configured && <p className="inline-note">隔离恢复要求独立且为空的 Redis 目标。已使用的演练目标保留供核对，再次演练前请由运维准备新的空目标。</p>}
    <div className="business-actions"><button className="button secondary" onClick={jobs.reload}>刷新任务状态</button>{active && <span role="status">维护任务处理中，页面自动刷新</span>}</div>
    <BusinessTable items={rows(jobs.value)} columns={[["任务", r => r.name], ["类型", r => r.kind === "backup" ? "加密备份" : "隔离恢复演练"], ["创建时间", r => formatBusinessTime(r.created_at)], ["状态", r => <Status value={r.status} />], ["结果", r => r.result?.error_code || (r.status === "succeeded" ? "数据及文件校验完成" : "等待执行结果")], ["操作", r => <div className="inline-controls"><button className="text-button link" onClick={() => setSelected(r)}>查看结果</button>{r.kind === "backup" && r.status === "succeeded" && <button className="text-button link" disabled={!caps?.restore_configured || active} onClick={() => create(r)}>隔离恢复演练</button>}</div>]]} />
    {selected && <Modal title="维护任务实际结果" wide flat onClose={() => setSelected(null)}><h3>{currentSelection.name}</h3><Status value={currentSelection.status} /><dl className="detail-list"><dt>任务编号</dt><dd>{currentSelection.id}</dd><dt>操作人</dt><dd>{currentSelection.actor_id}</dd><dt>完成时间</dt><dd>{currentSelection.finished_at ? formatBusinessTime(currentSelection.finished_at) : "尚未完成"}</dd><dt>校验和</dt><dd className="business-content">{currentSelection.result?.sha256 || currentSelection.result?.data_checksum || (currentSelection.kind === "restore_drill" && currentSelection.status === "succeeded" ? "已按备份清单验证数据库与原件" : "尚未生成")}</dd><dt>备份字节</dt><dd>{currentSelection.result?.bytes ?? "—"}</dd><dt>隔离目标</dt><dd>{currentSelection.result?.isolated_database || "—"}</dd><dt>错误类别</dt><dd>{currentSelection.result?.error_code || "—"}</dd></dl>{currentSelection.result?.message && <p>{currentSelection.result.message}</p>}{currentSelection.kind === "restore_drill" && currentSelection.status === "succeeded" && <p className="inline-note">隔离数据恢复已校验；恢复后的运行账号权限仍须单独配置，当前服务未切换到该数据库。</p>}{currentSelection.kind === "backup" && currentSelection.status === "succeeded" && <button className="button secondary" onClick={() => setForm({ title: "下载加密备份", fields: [{ name: "confirm", label: "按授权范围保管本备份", type: "checkbox" }], submit: async values => { if (!values.confirm) throw new Error("请先确认"); downloadBlob(await request(`/admin/backups/${key(currentSelection.id)}/file`, { download: true, timeout: 180000 }), `backup-${currentSelection.id}.sealed`); } })}>下载加密备份</button>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
