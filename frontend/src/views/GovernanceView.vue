<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import * as api from '@/api/governance'
import type { Approval, AuditRecord, GovernanceConfig, JobRecord, NotificationChannel, NotificationDelivery, Operations, OrgRecord, ReviewRecord, RunLogRecord, TenantRecord, UserRecord, VersionChange, VersionTrail } from '@/api/governance'
import { ApiError } from '@/api/http'
import * as qaApi from '@/api/qa'
import { DOC_AUTHORITY_LABELS, DOC_AUTHORITY_ORDER, PERM, ROLE_LABELS, type QARecord, type UserRole, type VersionFingerprint } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import { session } from '@/stores/session'
import { downloadBlob, todayISO } from '@/utils/files'
import { uuid } from '@/utils/uuid'
import '@/styles/workbench.css'

const tab = ref('reviews')
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref('')
const tenants = ref<TenantRecord[]>([]), organizations = ref<OrgRecord[]>([]), users = ref<UserRecord[]>([])
const selectedTenant = ref(session.state.user?.tenant_id ?? '')
const config = ref<GovernanceConfig | null>(null), operations = ref<Operations | null>(null)
const reviews = ref<ReviewRecord[]>([]), jobs = ref<JobRecord[]>([]), logs = ref<AuditRecord[]>([])
// 通知渠道与投递台账：渠道是否就绪、事件路由、每次投递的渠道/状态/尝试次数。
const channels = ref<NotificationChannel[]>([]), deliveries = ref<NotificationDelivery[]>([])
const channelRoutes = ref<Record<string, string[]>>({})
const reviewHasMore = ref(false)
const reviewPage = ref(1), auditPage = ref(1), auditTotal = ref(0)
const detail = ref<ReviewRecord | null>(null), identitySearch = ref('')
const dialog = ref(''), editingId = ref<string | null>(null)
const form = reactive({name: '', username: '', password: '', role: 'member' as UserRole, org_unit_id: '',
  org_type: 'department', parent_id: '', is_active: true, source_kind: 'score', source_id: '',
  year: new Date().getFullYear(), round: 1, opinion: '', decision: 'approved', kind: 'member_reminders',
  document_ids: '', dedup_key: '', evidence: '', enabled: false, tenant_type: 'school'})
const configReason = ref(''), allowedHosts = ref(''), localHosts = ref('')
const auditFilters = reactive({user_id: '', resource_id: '', action: '', resource_type: '',
  data_level: '', result: '', tenant_id: '', start_at: '', end_at: ''})
const auditScope = ref('')
// 运行日志（T-SYS-06E）：任务执行与定时扫描的经过，从审计轨迹读取——不新起一张表
const runLogs = ref<RunLogRecord[]>([]), runLogPage = ref(1), runLogTotal = ref(0), runLogScope = ref('')
const runFilters = reactive({event: '', kind: '', result: '', start_at: '', end_at: ''})
// 版本留痕（T-SEC-11）：提示词版本与变更历史 / 工作流契约版本 / 知识库修订事件
const versionTrail = ref<VersionTrail | null>(null), versionPage = ref(1)
// 事件名由后端给出（列表用 event_text）；筛选项与任务类型的中文标签按同一套口径列出
const runEventText: Record<string,string> = {job_enqueue:'任务入队', job_attempt_failed:'执行失败',
  job_completed:'执行完成', member_scheduled_scan:'党员提醒扫描',
  assessment_scheduled_scan:'考核提醒扫描', assessment_reminders_scan:'考核提醒同步'}
const runKindKeys = ['member_reminders', 'assessment_reminders', 'embedding']
// 问答记录集中查看（T-SYS-06）：本人档案口径之外，学校级按提问人/级别/结果/依据筛选并可导出
const records = ref<QARecord[]>([]), recordPage = ref(1), recordTotal = ref(0), recordScope = ref('')
const recordFilters = reactive({user_id: '', keyword: '', data_level: '', result: '', evidence: '', start_at: '', end_at: '', include_deleted: false})
const canManage = computed(() => session.can(PERM.IDENTITY_MANAGE))
// 开户（POST /admin/users）与登记租户在服务端仅限平台系统管理员；学校管理员仍可
// 维护组织与既有账号。按钮按同一口径隐藏，避免点出必然 403 的入口。
const isPlatformAdmin = computed(() => session.state.user?.role === 'system_admin')
const tabs = computed(() => [
  ...(canManage.value ? [{key:'identity', label:'组织与账号'}] : []),
  {key:'reviews', label:'人工审核'},
  ...(session.can(PERM.CONFIG_MANAGE) ? [{key:'config', label:'学校配置'}] : []),
  {key:'jobs', label:'任务台账'},
  ...(session.can(PERM.OPS_QUERY) ? [{key:'operations', label:'运行审计'}] : []),
  ...(session.can(PERM.AUDIT_QUERY) ? [{key:'records', label:'问答记录'}] : []),
])
const visibleOrgs = computed(() => organizations.value.filter(row =>
  row.name.includes(identitySearch.value) || row.path.includes(identitySearch.value)))
const visibleUsers = computed(() => users.value.filter(row =>
  (row.name + row.username + ROLE_LABELS[row.role]).includes(identitySearch.value)))
const activeOrgs = computed(() => organizations.value.filter(row => row.is_active))
const statusText: Record<string,string> = {pending:'待审核', approved:'已通过', returned:'已退回',
  queued:'等待执行', running:'执行中', retry:'等待重试', done:'已完成', failed:'执行失败',
  superseded:'已由后续提交替代', confirmed:'已确认', revoked:'已撤销', configured:'已登记', success:'成功', denied:'拒绝'}
const kindText: Record<string,string> = {score:'辅助评分', vote:'选优汇总', meeting:'组织生活纪要',
  study_activity:'中心组学习纪要', study_plan:'中心组学习计划', assessment_report:'考核评价',
  assessment_plan:'年度工作建议', member_reminders:'发展党员提醒', assessment_reminders:'考核提醒',
  embedding:'文档向量化'}
// 投递状态与事件名：运维要能一眼看懂“哪条提醒、走哪个渠道、发出去没有”。
const deliveryText: Record<string,string> = {pending:'待投递', sent:'已投递', failed:'投递失败'}
// 问答记录（T-SYS-06）：级别与结果必须中文化，否则治理页读起来像调试输出
const levelText: Record<string,string> = {public:'公开', internal:'内部', sensitive:'敏感', classified:'涉密'}
const eventText: Record<string,string> = {member_reminder:'发展党员提醒', assessment_reminder:'考核进度提醒',
  member_stage_transition:'党员阶段流转', meeting_archived:'组织生活归档', assessment_completed:'年度考核完成',
  channel_self_test:'渠道自检'}
const approvalText: Record<string,string> = {registration:'真实组织登记', organization_approval:'组织部门评审',
  it_approval:'信息化部门评审', secrecy_approval:'保密部门评审', pilot_scope:'批准的试点范围'}
const approvals = ['registration','organization_approval','it_approval','secrecy_approval'] as const
const roles = Object.keys(ROLE_LABELS) as UserRole[]
/** 供给机制（T-KB-13）：五类权威来源固定成行——缺行就不显示，等于把机制藏起来。 */
const supplyRows = computed(() => DOC_AUTHORITY_ORDER.map(authority => ({
  authority,
  label: DOC_AUTHORITY_LABELS[authority],
  rule: config.value?.values.knowledge_supply?.[authority]
    ?? { owner_unit: '', owner_name: '', review_cycle_days: null },
})))
/** 后端对未登记的类别返回空对象；补齐空行以便学校直接登记，而不是先点一次“新增”。
 *  空行的周期留 null（渲染为空输入框），避免别人一进来就看到"每 0 天复核一次"。 */
function useConfig(value: GovernanceConfig): GovernanceConfig {
  if (!value.values.knowledge_supply) value.values.knowledge_supply = {}
  for (const authority of DOC_AUTHORITY_ORDER) {
    if (!value.values.knowledge_supply[authority]) {
      value.values.knowledge_supply[authority] = { owner_unit: '', owner_name: '', review_cycle_days: null }
    }
  }
  return value
}
const selectedRecord = computed(() => {
  const snapshot = detail.value?.snapshot
  return (snapshot?.record ?? snapshot ?? {}) as Record<string, unknown>
})
const snapshotText = computed(() => {
  const row = selectedRecord.value
  const parts: string[] = []
  for (const key of ['title','topic','content','transcript','disclaimer','notice']) {
    if (typeof row[key] === 'string') parts.push(String(row[key]))
  }
  if (row.weighted_score !== undefined) parts.push('辅助总分：' + String(row.weighted_score ?? '无依据'))
  return parts.join('\n\n')
})
function fail(err: unknown): void {
  error.value = err instanceof ApiError ? err.message + (err.traceId ? '（请求编号：' + err.traceId + '）' : '')
    : err instanceof Error ? err.message : '操作失败，请重试'
}
async function loadIdentity(): Promise<void> {
  const [orgs, accounts] = await Promise.all([api.listOrgs(selectedTenant.value), api.listUsers(selectedTenant.value)])
  organizations.value = orgs.items; users.value = accounts.items
}
async function loadNotifications(): Promise<void> {
  const [registered, ledger] = await Promise.all([
    api.listNotificationChannels(), api.listNotificationDeliveries({limit:20})])
  channels.value = registered.items; channelRoutes.value = registered.routes
  deliveries.value = ledger.items
}
function routedEvents(name: string): string {
  return Object.entries(channelRoutes.value).filter(([,names]) => names.includes(name))
    .map(([event]) => eventText[event] ?? event).join('、')
}
async function selfTest(): Promise<void> {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    // 每次自检都是一次新的投递事实，因此用新去重键，不被上一次去重命中。
    const result = await api.dispatchNotification({event:'channel_self_test', subject:'渠道投递自检',
      body:'由“运行审计”页发起的一次投递自检，不含真实人员信息。', dedup_key:uuid()})
    notice.value = '自检结果：' + (result.results.length
      ? result.results.map(row => row.channel + ' ' + (deliveryText[row.status] ?? row.status)
        + (row.error ? '（' + row.error + '）' : '')).join('；')
      : '当前没有配置任何通知渠道，未投递任何消息。')
    await loadNotifications()
  } catch (err) { fail(err) } finally { busy.value = false }
}
// 界面按北京时间填时间（与列表、导出显示同一口钟），传后端时显式带 +08:00，
// 免得被当成本机时区或 UTC 解释，筛出差 8 小时的结果。
function beijingIso(value: string): string {
  if (!value) return ''
  const [datePart, timePart = ''] = value.split('T')
  const [hour, minute] = timePart.split(':')
  return datePart + 'T' + (hour || '00') + ':' + (minute || '00') + ':00+08:00'
}
/** 列表与导出共用一个参数源：导出的必须是"当前看到的那一批"，不是另一次查询 */
function recordParams(): Record<string, string|number|boolean> {
  const params: Record<string, string|number|boolean> = {}
  if (recordFilters.user_id.trim()) params.user_id = recordFilters.user_id.trim()
  if (recordFilters.keyword.trim()) params.keyword = recordFilters.keyword.trim()
  if (recordFilters.data_level) params.data_level = recordFilters.data_level
  if (recordFilters.result) params.refused = recordFilters.result === 'refused'
  if (recordFilters.evidence) params.has_evidence = recordFilters.evidence === 'with'
  if (recordFilters.start_at) params.start_at = beijingIso(recordFilters.start_at)
  if (recordFilters.end_at) params.end_at = beijingIso(recordFilters.end_at)
  if (recordFilters.include_deleted) params.include_deleted = true
  return params
}
function resetRecordFilters(): void {
  Object.assign(recordFilters, {user_id:'', keyword:'', data_level:'', result:'', evidence:'',
    start_at:'', end_at:'', include_deleted:false})
  recordPage.value = 1
  void loadTab()
}
/** 审计查询与导出同样共用一个参数源：导出的必须是"当前看到的那一批" */
function auditParams(): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(auditFilters)) {
    if (key === 'start_at' || key === 'end_at') continue
    if (value) params[key] = value
  }
  if (auditFilters.start_at) params.start_at = beijingIso(auditFilters.start_at)
  if (auditFilters.end_at) params.end_at = beijingIso(auditFilters.end_at)
  return params
}
function resetAuditFilters(): void {
  Object.assign(auditFilters, {user_id:'', resource_id:'', action:'', resource_type:'',
    data_level:'', result:'', tenant_id:'', start_at:'', end_at:''})
  auditPage.value = 1
  void loadTab()
}
async function exportAudit(): Promise<void> {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    downloadBlob(await api.exportAudit(auditParams()), '审计日志-' + todayISO() + '.zip')
    notice.value = '已导出当前筛选范围（' + (auditScope.value || '未筛选') + '）的审计对账包，导出动作已写入审计。'
  } catch (err) { fail(err) } finally { busy.value = false }
}
/** 运行日志（T-SYS-06E）：与审计查询同一套时间口径（界面按北京时间填，发送带 +08:00） */
function runParams(): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  if (runFilters.event) params.event = runFilters.event
  if (runFilters.kind) params.kind = runFilters.kind
  if (runFilters.result) params.result = runFilters.result
  if (runFilters.start_at) params.start_at = beijingIso(runFilters.start_at)
  if (runFilters.end_at) params.end_at = beijingIso(runFilters.end_at)
  return params
}
function resetRunFilters(): void {
  Object.assign(runFilters, {event:'', kind:'', result:'', start_at:'', end_at:''})
  runLogPage.value = 1
  void loadRunLogs()
}
async function loadRunLogs(): Promise<void> {
  const page = await api.listRunLogs({...runParams(), page: runLogPage.value})
  runLogs.value = page.items; runLogTotal.value = page.total; runLogScope.value = page.scope_note
}
/** 版本留痕（T-SEC-11）：三块来源都是既有事实的可查视图，不新增登记表 */
async function loadVersionTrail(): Promise<void> {
  versionTrail.value = await api.getVersionTrail(versionPage.value)
}
// 提示词种类显示名：与导出台账同一套说法（后端 app/core/versions.py::PROMPT_LABELS）
const promptKindText: Record<string,string> = {qa:'问答提示词', rewrite:'追问改写'}
/** 版本指纹压成一行（与导出说明一致）；空指纹是留痕功能上线前的记录 */
function fingerprintText(versions?: VersionFingerprint): string {
  const prompt = versions?.prompt ?? {}, workflow = versions?.workflow ?? {}
  const parts: string[] = []
  const promptText = Object.entries(prompt).map(([kind, value]) => `${promptKindText[kind] ?? kind} ${value}`).join(' / ')
  const workflowText = Object.entries(workflow).map(([id, value]) => `${id} ${value}`).join(' / ')
  if (promptText) parts.push('提示词：' + promptText)
  if (workflowText) parts.push('工作流：' + workflowText)
  return parts.join('；')
}
const currentPromptText = computed(() => Object.entries(versionTrail.value?.prompt.current ?? {})
  .map(([kind, value]) => `${promptKindText[kind] ?? kind} ${value}`).join(' / '))
/** 一次变更压成一行：界面上"从什么改成了什么"要一眼可读 */
function changeText(change: VersionChange): string {
  return `${promptKindText[change.kind] ?? change.kind} ${change.before ?? '未设置'} → ${change.after}`
}
/** 知识库修订事件：入库即第 1 版；内容更新给出前后两个版本号 */
function revisionText(previous: number | null, revision: number | null): string {
  if (revision === null) return '—'
  return previous === null ? `第 ${revision} 版` : `第 ${previous} → ${revision} 版`
}
async function loadRecords(): Promise<void> {
  const page = await qaApi.listQaRecords({...recordParams(), page: recordPage.value})
  records.value = page.items; recordTotal.value = page.total; recordScope.value = page.scope_note
}
async function exportRecords(): Promise<void> {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    downloadBlob(await qaApi.exportQaRecords(recordParams()), '问答记录-' + todayISO() + '.xlsx')
    notice.value = '已导出当前筛选范围（' + (recordScope.value || '未筛选') + '）的问答记录，导出动作已写入审计。'
  } catch (err) { fail(err) } finally { busy.value = false }
}
async function loadTab(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    if (tab.value === 'identity') await loadIdentity()
    if (tab.value === 'reviews') {
      const page = await api.listReviews(reviewPage.value)
      reviews.value = page.items; reviewHasMore.value = page.has_more
    }
    if (tab.value === 'jobs') jobs.value = (await api.listJobs()).items
    if (tab.value === 'records') await loadRecords()
    if (tab.value === 'config') {
      const loaded = useConfig(await api.getGovernance())
      config.value = loaded
      allowedHosts.value = loaded.values.model_policy.allowed_hosts.join('\n')
      localHosts.value = loaded.values.model_policy.local_hosts.join('\n')
    }
    if (tab.value === 'operations') {
      const params = {...auditParams(), page: auditPage.value}
      const [stats, audit] = await Promise.all([api.getOperations(), api.listAudit(params), loadNotifications()])
      operations.value = stats; logs.value = audit.items; auditTotal.value = audit.total
      auditScope.value = audit.scope_note ?? ''
      // 运行日志与审计查询同一页展示：排障时"谁点了什么"和"任务跑成什么样"要能对上时间
      await Promise.all([loadRunLogs(), loadVersionTrail()])
    }
  } catch (err) { fail(err) } finally { loading.value = false }
}
onMounted(async () => {
  if (canManage.value) {
    try { tenants.value = (await api.listTenants()).items } catch (err) { fail(err) }
  }
  await loadTab()
})
watch(tab, () => { if (!busy.value) void loadTab() })
watch(selectedTenant, () => { if (tab.value === 'identity') void loadTab() })
function open(type: string, row?: OrgRecord | UserRecord | TenantRecord): void {
  error.value = ''; notice.value = ''; editingId.value = row?.id ?? null
  Object.assign(form, {name:'', username:'', password:'', role:'member', org_unit_id:'',
    org_type:'department', parent_id:'', is_active:true, source_kind:'score', source_id:'',
    year:new Date().getFullYear(), round:1, opinion:'', decision:'approved', kind:'member_reminders',
    document_ids:'', dedup_key:uuid(), evidence:'', enabled:false, tenant_type:'school'})
  if (row) Object.assign(form, row)
  if (type === 'tenant' && !row) form.parent_id = session.state.user?.tenant_id ?? ''
  if (type === 'archive') {
    form.enabled = config.value?.archive_policy?.enabled ?? false
    form.evidence = config.value?.archive_policy?.evidence ?? ''
  }
  dialog.value = type
}
async function viewReview(row: ReviewRecord): Promise<void> {
  error.value = ''
  try { detail.value = await api.getReview(row.id); open('decision') } catch (err) { fail(err) }
}
async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    if (dialog.value === 'organization') {
      const body = editingId.value ? {name:form.name, parent_id:form.parent_id || null, is_active:form.is_active}
        : {name:form.name, org_type:form.org_type, parent_id:form.parent_id || null}
      await api.saveOrg(editingId.value, body, selectedTenant.value)
    } else if (dialog.value === 'user') {
      const body = {name:form.name, role:form.role, org_unit_id:form.org_unit_id || null,
        ...(editingId.value ? {is_active:form.is_active} : {username:form.username, password:form.password})}
      await api.saveUser(editingId.value, body, selectedTenant.value)
    } else if (dialog.value === 'tenant') {
      if (editingId.value) await api.updateTenant(editingId.value, {name:form.name, is_active:form.is_active})
      else await api.createTenant({name:form.name, tenant_type:form.tenant_type, parent_id:form.parent_id})
      tenants.value = (await api.listTenants()).items
    } else if (dialog.value === 'submit') {
      await api.submitReview({source_kind:form.source_kind, source_id:form.source_id, year:form.year, round:form.round})
    } else if (dialog.value === 'decision' && detail.value) {
      await api.decideReview(detail.value.id, {decision:form.decision,
        source_version:detail.value.source_version, opinion:form.opinion})
    } else if (dialog.value === 'job') {
      await api.queueJob({kind:form.kind, dedup_key:form.dedup_key,
        document_ids:form.document_ids.split(/[\s,，]+/).filter(Boolean)})
    } else if (dialog.value === 'archive') {
      await api.saveArchivePolicy({enabled:form.enabled,
        expected_revision:config.value?.archive_policy?.revision ?? 0, evidence:form.evidence})
    }
    dialog.value = ''; form.password = ''; notice.value = '已保存。'; await loadTab()
  } catch (err) { fail(err) } finally { busy.value = false }
}
async function saveConfig(): Promise<void> {
  if (!config.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const values = JSON.parse(JSON.stringify(config.value.values)) as api.GovernanceValues
    values.model_policy.allowed_hosts = allowedHosts.value.split(/[\s,，]+/).filter(Boolean)
    values.model_policy.local_hosts = localHosts.value.split(/[\s,，]+/).filter(Boolean)
    // 供给机制：整行留空表示该权威类别尚未登记，直接丢弃；半填的行不能悄悄丢，
    // 否则学校会以为"登记好了"，实际上条目根本没有复核责任人与周期（T-KB-13）。
    const supply: api.GovernanceValues['knowledge_supply'] = {}
    for (const authority of DOC_AUTHORITY_ORDER) {
      const row = values.knowledge_supply?.[authority]
      if (!row) continue
      const owner = row.owner_unit.trim(), name = row.owner_name.trim()
      const cycle = Number(row.review_cycle_days)
      if (!owner && !name && !cycle) continue
      if (!owner || !name || !cycle) {
        throw new Error('供给机制「' + DOC_AUTHORITY_LABELS[authority]
          + '」要同时填写责任部门、责任人与更新周期（天）')
      }
      if (cycle < 30 || cycle > 3650) {
        throw new Error('供给机制「' + DOC_AUTHORITY_LABELS[authority]
          + '」的更新周期需在 30–3650 天之间')
      }
      supply[authority] = { owner_unit: owner, owner_name: name, review_cycle_days: cycle }
    }
    values.knowledge_supply = supply
    config.value = useConfig(await api.saveGovernance({expected_version:config.value.version, reason:configReason.value, values}))
    configReason.value = ''; notice.value = '配置已保存，版本 ' + config.value.version
  } catch (err) { fail(err) } finally { busy.value = false }
}
function approvalValue(key: typeof approvals[number]): Approval | undefined { return config.value?.values[key] }
function orgLabel(id: string | null): string { return organizations.value.find(row => row.id === id)?.name ?? '待绑定' }
function formatDate(value: string | null): string {
  return value ? new Intl.DateTimeFormat('zh-CN', {dateStyle:'medium', timeStyle:'short', timeZone:'Asia/Shanghai'})
    .format(new Date(value.endsWith('Z') ? value : value+'Z')) : '—'
}
</script>

<template>
  <div class="wb wb-stack governance" :aria-busy="loading || busy">
    <header class="wb-toolbar">
      <div><p class="u-eyebrow">学校治理 · 人工确认 · 运行追踪</p><h1 class="u-title">管理与审核</h1>
        <p class="u-muted">按当前账号授权管理。学校资料与正式审批未确认时保留待配置。</p></div>
      <button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="loadTab">刷新</button>
    </header>
    <p v-if="notice" class="governance__notice" role="status">{{ notice }}</p>
    <p v-if="error && !dialog" class="wb-error" role="alert">{{ error }}</p>
    <WorkspaceTabs v-model="tab" :items="tabs" label="管理工作区" :disabled="busy">
      <p v-if="loading" class="wb-empty" role="status">正在读取授权数据…</p>
      <section v-else-if="tab === 'identity'" class="wb-stack">
        <div class="wb-toolbar"><label class="wb-field"><span>管理租户</span><select class="select" v-model="selectedTenant">
          <option v-for="row in tenants" :key="row.id" :value="row.id">{{ row.name }}{{ row.is_active ? '' : '（已停用）' }}</option>
        </select></label><div class="wb-actions"><button v-if="isPlatformAdmin" class="btn btn--primary" type="button" @click="open('tenant')">登记租户</button>
          <button v-if="tenants.find(row=>row.id===selectedTenant)" class="btn btn--quiet" type="button" @click="open('tenant', tenants.find(row=>row.id===selectedTenant))">维护租户</button></div></div>
        <p class="wb-note">新租户默认待配置。组织登记须使用学校认可的名称和层级；停用先处理下级组织。</p>
        <label class="wb-field"><span>查找组织或账号</span><input class="input" v-model="identitySearch" type="search" placeholder="名称、账号或角色" /></label>
        <section class="wb-section wb-stack"><div class="wb-toolbar"><h2>组织目录</h2><button type="button" class="btn btn--primary" @click="open('organization')">新增组织</button></div>
          <div v-if="visibleOrgs.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>组织</th><th>类型</th><th>上级</th><th>状态</th><th>维护</th></tr></thead><tbody>
            <tr v-for="row in visibleOrgs" :key="row.id"><td>{{ row.name }}</td><td>{{ {school:'学校',department:'院系',branch:'支部'}[row.org_type] }}</td>
              <td>{{ row.parent_id ? orgLabel(row.parent_id) : '根组织' }}</td><td>{{ row.is_active ? '有效' : '已停用' }}</td>
              <td><button class="btn btn--quiet" type="button" :aria-label="'维护组织 '+row.name" @click="open('organization',row)">维护</button></td></tr>
          </tbody></table></div><p v-else class="wb-empty">组织尚未登记，请补充学校确认的组织资料。</p>
        </section>
        <section class="wb-section wb-stack"><div class="wb-toolbar"><h2>用户与角色</h2><button v-if="isPlatformAdmin" type="button" class="btn btn--primary" @click="open('user')">新增用户</button></div>
          <div v-if="visibleUsers.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>用户</th><th>账号</th><th>角色</th><th>所属组织</th><th>状态</th><th>维护</th></tr></thead><tbody>
            <tr v-for="row in visibleUsers" :key="row.id"><td>{{ row.name }}</td><td>{{ row.username }}</td><td>{{ ROLE_LABELS[row.role] }}</td><td>{{ orgLabel(row.org_unit_id) }}</td>
              <td>{{ row.is_active ? '有效' : '已停用' }}</td><td><button class="btn btn--quiet" type="button" :aria-label="'维护用户 '+row.name" @click="open('user',row)">维护</button></td></tr>
          </tbody></table></div><p v-else class="wb-empty">暂无符合条件的账号。</p>
          <p class="wb-note">角色或组织变更在下一次请求生效。公共知识库仅由系统管理员维护。</p>
        </section>
      </section>
      <section v-else-if="tab === 'reviews'" class="wb-stack">
        <div class="wb-toolbar"><div><h2 class="u-title-sub">人工审核台账</h2><p class="wb-note">提交人不能自审。源内容变化后须重新提交。</p></div><button type="button" class="btn btn--primary" @click="open('submit')">提交审核</button></div>
        <div v-if="reviews.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>业务</th><th>对象编号</th><th>当前状态</th><th>提交时间</th><th>审核</th></tr></thead><tbody>
          <tr v-for="row in reviews" :key="row.id"><td>{{ kindText[row.source_kind] }}</td><td class="governance__id">{{ row.source_id }}</td>
            <td>{{ row.stale ? '源内容已变更，须重新提交' : statusText[row.effective_status] }}</td><td>{{ formatDate(row.created_at) }}</td>
            <td><button type="button" class="btn btn--quiet" @click="viewReview(row)">查看材料</button></td></tr>
        </tbody></table></div><p v-else class="wb-empty">当前页没有可访问的审核记录。</p>
        <div class="wb-pager"><button class="btn btn--quiet" type="button" :disabled="reviewPage===1" @click="reviewPage--; loadTab()">上一页</button><span>第 {{ reviewPage }} 页</span>
          <button class="btn btn--quiet" type="button" :disabled="!reviewHasMore" @click="reviewPage++; loadTab()">下一页</button></div>
      </section>
      <form v-else-if="tab === 'config' && config" class="wb-stack" @submit.prevent="saveConfig">
        <div class="governance__admission"><h2>学校准入资料{{ config.admission.status==='pending' ? '待配置' : '已登记' }}</h2>
          <p>{{ config.admission.pending.map(key=>approvalText[key] ?? key).join('、') || config.admission.notice }}</p>
          <p>电子归档：{{ config.admission.electronic_archive==='confirmed' ? '已确认' : '待学校确认' }} · 配置版本 {{ config.version }}</p></div>
        <section class="wb-section wb-stack"><h2>组织资料与三方评审</h2><div v-for="key in approvals" :key="key" class="wb-grid">
          <label class="wb-field"><span>{{ approvalText[key] }}</span><select class="select" v-if="approvalValue(key)" v-model="config.values[key].status">
            <option value="pending">待确认</option><option value="confirmed">已确认</option><option value="revoked">已撤销</option></select></label>
          <label class="wb-field"><span>确认依据</span><input class="input" v-model="config.values[key].evidence" maxlength="2000" placeholder="学校认可的文件或审批记录编号" /></label>
        </div><label class="wb-field"><span>批准的试点范围</span><textarea class="textarea" v-model="config.values.pilot_scope" rows="2" maxlength="1000" placeholder="资料未确认时留空" /></label></section>
        <section class="wb-section wb-stack"><h2>模型使用范围</h2><p class="wb-note">云端聊天、向量和重排均受此范围约束。敏感及涉密资料禁止发送云端；校内敏感分析另需确认。</p>
          <div class="wb-grid"><label class="wb-check"><input v-model="config.values.model_policy.external_enabled" type="checkbox" />学校已确认外部模型使用</label>
            <label class="wb-check"><input v-model="config.values.model_policy.internal_approved" type="checkbox" />学校已确认内部资料出网</label>
            <label class="wb-check"><input v-model="config.values.model_policy.local_sensitive_enabled" type="checkbox" />学校已确认校内敏感分析范围</label></div>
          <label class="wb-field"><span>模型使用审批依据</span><textarea class="textarea" v-model="config.values.model_policy.evidence" rows="2" maxlength="2000" /></label>
          <div class="wb-grid"><label class="wb-field"><span>获准外部模型主机</span><textarea class="textarea" v-model="allowedHosts" rows="3" placeholder="每行一个精确主机名，须在部署批准范围内" /></label>
            <label class="wb-field"><span>获准校内模型主机</span><textarea class="textarea" v-model="localHosts" rows="3" /></label></div>
          <label v-for="kind in ['llm','embedding','reranker']" :key="kind" class="wb-field"><span>{{ {llm:'聊天模型',embedding:'向量模型',reranker:'重排模型'}[kind] }}</span>
            <select class="select" v-model="config.values.model_routes[kind]"><option :value="undefined">继承部署配置</option><option v-for="model in config.model_catalog.filter(row=>row.type===kind)" :key="model.id" :value="model.id">{{ model.id }} · {{ model.deployment==='external' ? '云端' : '校内' }}</option></select></label>
        </section>
        <section class="wb-section wb-stack"><h2>业务规则与提示词</h2><div class="wb-grid">
          <label v-for="key in ['qa','rewrite']" :key="key" class="wb-field"><span>{{ key==='qa' ? '问答提示词' : '追问改写提示词' }}</span><select class="select" v-model="config.values.prompt_versions[key]"><option :value="undefined">继承部署配置</option><option value="v1">第 1 版</option><option value="v2">第 2 版（加强越权与指令检查）</option></select></label>
        </div><p class="wb-note">辅助评分维度采用经审定的业务规则；权重总和必须为 1。</p>
          <div class="wb-grid"><label v-for="key in Object.keys(config.values.scoring_weights)" :key="key" class="wb-field"><span>{{ {theory_test:'理论测试',volunteer_service:'志愿服务',academic:'学业表现',public_review:'群众评议',party_review:'党员意见'}[key] ?? key }}</span><input class="input" v-model.number="config.values.scoring_weights[key]" type="number" min="0.01" max="1" step="0.01" /></label></div>
          <button v-if="!Object.keys(config.values.scoring_weights).length" type="button" class="btn btn--quiet" @click="config.values.scoring_weights={theory_test:0.2,volunteer_service:0.2,academic:0.2,public_review:0.2,party_review:0.2}">配置学校评分权重</button>
          <label class="wb-field"><span>文件保留天数</span><input class="input" v-model.number="config.values.retention.file_days" type="number" min="365" max="36500" /></label>
          <label class="wb-field"><span>审计保留天数（不少于一年）</span><input class="input" v-model.number="config.values.retention.audit_days" type="number" min="365" max="36500" /></label>
          <p class="wb-note">物理清理默认禁用。软删除保留历史证据，清理须按学校批准的保留与删除流程执行。</p>
        </section>
        <section class="wb-section wb-stack"><h2>知识库供给机制</h2>
          <p class="wb-note">按权威来源明确供给责任部门、责任人与更新周期。条目入库即据此排定下次复核日期，到期后在知识库列表提示「待复核」；未登记的类别不排日程。法规修订后更新正文视为一次复核，日程随之重排。</p>
          <div v-for="row in supplyRows" :key="row.authority" class="wb-grid">
            <label class="wb-field"><span>{{ row.label }} · 责任部门</span>
              <input class="input" v-model="row.rule.owner_unit" maxlength="100" placeholder="如：党委组织部" /></label>
            <label class="wb-field"><span>责任人</span>
              <input class="input" v-model="row.rule.owner_name" maxlength="50" placeholder="如：组织科 张老师" /></label>
            <label class="wb-field"><span>更新周期（天，30–3650）</span>
              <input class="input" v-model.number="row.rule.review_cycle_days" type="number" min="30" max="3650" /></label>
          </div>
        </section>
        <section class="wb-section wb-toolbar"><div><h2>电子记录效力</h2><p>{{ config.archive_policy?.enabled ? '学校已确认，可按业务权限归档' : '尚未确认，归档默认关闭' }}</p></div><button class="btn btn--quiet" type="button" @click="open('archive')">登记或撤销确认</button></section>
        <label class="wb-field"><span>本次变更说明</span><input class="input" v-model="configReason" required maxlength="500" /></label>
        <div><button class="btn btn--primary" type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存学校配置' }}</button></div>
      </form>
      <section v-else-if="tab === 'jobs'" class="wb-stack"><div class="wb-toolbar"><h2 class="u-title-sub">我的任务</h2><button class="btn btn--primary" type="button" @click="open('job')">创建任务</button></div>
        <p class="wb-note">提醒与批量处理持久保存。同一去重编号的重试复用原任务；执行时重新检查当前权限。</p>
        <div v-if="jobs.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>任务</th><th>状态</th><th>已尝试</th><th>结果</th><th>创建时间</th></tr></thead><tbody>
          <tr v-for="row in jobs" :key="row.id"><td>{{ kindText[row.kind] }}</td><td>{{ statusText[row.status] }}</td><td>{{ row.attempts }} / {{ row.max_attempts }}</td>
            <td>{{ row.result?.processed ?? (row.error_code ? '失败记录已保存，请联系管理员核对' : '待执行') }}</td><td>{{ formatDate(row.created_at) }}</td></tr></tbody></table></div>
        <p v-else class="wb-empty">暂无任务。任务创建后会在此显示执行状态。</p>
      </section>
      <section v-else-if="tab === 'operations' && operations" class="wb-stack"><section class="wb-section"><h2>运行概况 · 最近 24 小时</h2>
        <dl class="governance__facts"><div><dt>待审核</dt><dd>{{ operations.reviews.pending ?? 0 }}</dd></div><div><dt>待执行任务</dt><dd>{{ (operations.jobs.queued ?? 0)+(operations.jobs.retry ?? 0) }}</dd></div><div><dt>审计待重放</dt><dd>{{ operations.audit_spool_pending }}</dd></div></dl>
        <p v-if="!operations.model_usage.length" class="wb-note">当前时间窗暂无模型调用记录。性能验收需要批准的模型和真实负载。</p>
        <p v-for="row in operations.model_usage" :key="row.type+row.result">{{ row.type }} · {{ statusText[row.result] }} {{ row.calls }} 次 · 平均 {{ row.mean_seconds.toFixed(2) }} 秒</p>
        <p v-for="row in operations.alerts" :key="row.action+row.result" class="wb-error">异常活动：{{ row.action }} / {{ statusText[row.result] }} {{ row.count }} 次，可按下方动作筛选追查。</p>
      </section>
        <form class="wb-section wb-stack" @submit.prevent="auditPage=1; loadTab()"><h2>审计查询</h2>
          <p class="wb-note">按动作 / 对象 / 级别 / 结果 / 时间查看本租户审计记录；跨租户检索仅平台系统管理员，填租户编号即可。导出为对账包：台账 CSV + 导出说明（口径 / 条数 / 导出人 / 时区），导出的就是下方这批记录，导出动作同样写入审计。</p>
          <div class="wb-grid">
          <label class="wb-field"><span>用户编号</span><input class="input" v-model="auditFilters.user_id" /></label><label class="wb-field"><span>对象编号</span><input class="input" v-model="auditFilters.resource_id" /></label>
          <label class="wb-field"><span>动作</span><input class="input" v-model="auditFilters.action" placeholder="query、update、export…" /></label><label class="wb-field"><span>对象类型</span><input class="input" v-model="auditFilters.resource_type" placeholder="user、member、knowledge_doc…" /></label>
          <label class="wb-field"><span>数据级别</span><select class="select" v-model="auditFilters.data_level"><option value="">全部级别</option><option value="public">公开</option><option value="internal">内部</option><option value="sensitive">敏感</option><option value="classified">涉密</option></select></label><label class="wb-field"><span>结果</span><select class="select" v-model="auditFilters.result"><option value="">全部结果</option><option value="success">成功</option><option value="denied">拒绝</option><option value="failed">失败</option></select></label>
          <label v-if="isPlatformAdmin" class="wb-field"><span>租户编号（跨租户）</span><input class="input" v-model="auditFilters.tenant_id" placeholder="留空查本租户" /></label>
          <label class="wb-field"><span>开始时间（北京时间）</span><input class="input" v-model="auditFilters.start_at" type="datetime-local" /></label><label class="wb-field"><span>结束时间（北京时间）</span><input class="input" v-model="auditFilters.end_at" type="datetime-local" /></label>
        </div><div class="wb-actions"><button class="btn btn--primary" type="submit">查询审计记录</button><button class="btn btn--quiet" type="button" @click="resetAuditFilters">清空条件</button><button class="btn btn--quiet" type="button" :disabled="busy || !logs.length" @click="exportAudit">{{ busy ? '导出中…' : '导出当前筛选（对账包）' }}</button></div></form>
        <p v-if="auditScope" class="wb-note">当前口径：{{ auditScope }}。页面与导出用同一批条件；台账按北京时间正序排列，便于按时间轴对账。</p>
        <div v-if="logs.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>时间</th><th>用户编号</th><th>动作 / 对象</th><th>结果</th><th>请求编号</th></tr></thead><tbody>
          <tr v-for="row in logs" :key="row.id"><td>{{ formatDate(row.created_at) }}</td><td class="governance__id">{{ row.user_id }}</td><td>{{ row.action }} / {{ row.resource_type }}<small>{{ row.resource_id }}</small></td><td>{{ statusText[row.result] ?? row.result }}</td><td class="governance__id">{{ row.request_id }}</td></tr></tbody></table></div>
        <p v-else class="wb-empty">没有符合条件的审计记录。</p><div class="wb-pager"><button class="btn btn--quiet" type="button" :disabled="auditPage===1" @click="auditPage--; loadTab()">上一页</button><span>第 {{ auditPage }} 页 · 共 {{ auditTotal }} 条</span><button class="btn btn--quiet" type="button" :disabled="auditPage*40>=auditTotal" @click="auditPage++; loadTab()">下一页</button></div>
        <section class="wb-section wb-stack"><h2>运行日志</h2>
          <p class="wb-note">任务执行与定时扫描的经过：每次入队、每次尝试失败（第几次 / 错误类型 / 耗时）、每次完成（处理条数 / 耗时）以及三处定时扫描的结果。失败只记错误类型与状态，不记供应商错误正文；任务类型以任务台账为准，按类型筛时不显示定时扫描（扫描不属于某一条任务，用事件筛可单独看）。</p>
          <div class="wb-grid">
            <label class="wb-field"><span>事件</span><select class="select" v-model="runFilters.event"><option value="">全部事件</option><option v-for="(label, key) in runEventText" :key="key" :value="key">{{ label }}</option></select></label>
            <label class="wb-field"><span>任务类型</span><select class="select" v-model="runFilters.kind"><option value="">全部类型</option><option v-for="key in runKindKeys" :key="key" :value="key">{{ kindText[key] }}</option></select></label>
            <label class="wb-field"><span>结果</span><select class="select" v-model="runFilters.result"><option value="">全部结果</option><option value="success">成功</option><option value="denied">拒绝</option><option value="failed">失败</option></select></label>
            <label class="wb-field"><span>开始时间（北京时间）</span><input class="input" v-model="runFilters.start_at" type="datetime-local" /></label>
            <label class="wb-field"><span>结束时间（北京时间）</span><input class="input" v-model="runFilters.end_at" type="datetime-local" /></label>
          </div>
          <div class="wb-actions"><button class="btn btn--primary" type="button" :disabled="loading" @click="runLogPage=1; loadRunLogs()">查询运行日志</button><button class="btn btn--quiet" type="button" @click="resetRunFilters">清空条件</button></div>
          <p v-if="runLogScope" class="wb-note">当前口径：{{ runLogScope }}。列表最新在前；耗时能区分"秒挂"和"跑到超时"。</p>
          <div v-if="runLogs.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>时间</th><th>事件</th><th>任务类型</th><th>结果</th><th>第几次</th><th>耗时</th><th>处理条数</th><th>失败原因</th><th>任务编号</th></tr></thead><tbody>
            <tr v-for="row in runLogs" :key="row.id"><td>{{ formatDate(row.created_at) }}</td><td>{{ row.event_text }}</td><td>{{ row.kind ? (kindText[row.kind] ?? row.kind) : '—' }}</td><td>{{ statusText[row.result] ?? row.result }}</td><td>{{ row.attempt ?? '—' }}</td><td>{{ row.duration_ms === null ? '—' : row.duration_ms + ' 毫秒' }}</td><td>{{ row.processed ?? row.reminder_count ?? '—' }}</td><td>{{ row.error_code ?? '—' }}</td><td class="governance__id">{{ row.resource_id ?? '—' }}</td></tr></tbody></table></div>
          <p v-else class="wb-empty">没有符合条件的运行记录。任务入队、执行与定时扫描都会在此留痕。</p>
          <div class="wb-pager"><button class="btn btn--quiet" type="button" :disabled="runLogPage===1" @click="runLogPage--; loadRunLogs()">上一页</button><span>第 {{ runLogPage }} 页 · 共 {{ runLogTotal }} 条</span><button class="btn btn--quiet" type="button" :disabled="runLogPage*40>=runLogTotal" @click="runLogPage++; loadRunLogs()">下一页</button></div>
        </section>
        <section v-if="versionTrail" class="wb-section wb-stack"><h2>版本留痕</h2>
          <p class="wb-note">一条回答由"提示词 + 工作流契约 + 被引知识版本"共同决定，三者都要能查到。三处来源各自权威，不另起一张登记表：提示词版本来自学校配置的变更历史（谁、何时、为什么改），工作流契约版本随代码发布，知识库版本随每条引用记在问答记录里。历史版本不会被当前配置覆盖——查询看到的始终是当时的取值。</p>
          <h3 class="u-title-sub">提示词版本</h3>
          <p class="wb-note">当前生效：{{ currentPromptText || '未登记' }}。<small>{{ versionTrail.prompt.scope_note }}</small></p>
          <div v-if="versionTrail.prompt.history.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>配置版本</th><th>变更时间</th><th>操作人</th><th>变更</th><th>原因</th></tr></thead><tbody>
            <tr v-for="row in versionTrail.prompt.history" :key="row.config_version"><td>第 {{ row.config_version }} 版</td><td>{{ formatDate(row.changed_at) }}</td><td>{{ row.actor }}<small>{{ row.username }}</small></td>
              <td><span v-for="change in row.changes" :key="change.kind" class="governance__change">{{ changeText(change) }}</span></td><td>{{ row.reason || '—' }}</td></tr></tbody></table></div>
          <p v-else class="wb-note">该校配置从未改动过提示词版本，一直在用出厂默认版本；改动后这里会留下"谁、何时、为什么改"。</p>
          <h3 class="u-title-sub">工作流契约版本</h3>
          <p class="wb-note"><small>{{ versionTrail.workflow.scope_note }}</small></p>
          <div class="wb-table-wrap"><table class="wb-table"><thead><tr><th>工作流</th><th>用途</th><th>契约版本</th></tr></thead><tbody>
            <tr v-for="row in versionTrail.workflow.items" :key="row.workflow"><td>{{ row.workflow }}</td><td>{{ row.name }}</td><td>{{ row.version }}</td></tr></tbody></table></div>
          <h3 class="u-title-sub">知识库版本</h3>
          <p class="wb-note"><small>{{ versionTrail.knowledge.scope_note }}</small></p>
          <div v-if="versionTrail.knowledge.items.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>时间</th><th>条目</th><th>事件</th><th>修订</th><th>操作人</th></tr></thead><tbody>
            <tr v-for="(row, index) in versionTrail.knowledge.items" :key="(row.resource_id ?? '') + index"><td>{{ formatDate(row.created_at) }}</td>
              <td>{{ row.title ?? '条目已删除或查不到' }}<small>{{ row.doc_id ?? row.resource_id ?? '—' }}</small></td>
              <td>{{ row.event_text }}</td><td>{{ revisionText(row.previous_revision, row.revision) }}</td><td>{{ row.actor }}<small>{{ row.username }}</small></td></tr></tbody></table></div>
          <p v-else class="wb-empty">暂无知识库修订记录。条目入库与内容更新都会在此留痕。</p>
          <div class="wb-pager"><button class="btn btn--quiet" type="button" :disabled="versionPage===1" @click="versionPage--; loadVersionTrail()">上一页</button><span>第 {{ versionTrail.knowledge.page }} 页 · 共 {{ versionTrail.knowledge.total }} 条</span><button class="btn btn--quiet" type="button" :disabled="versionTrail.knowledge.page * versionTrail.knowledge.page_size >= versionTrail.knowledge.total" @click="versionPage++; loadVersionTrail()">下一页</button></div>
        </section>
        <section class="wb-section wb-stack"><div class="wb-toolbar"><div><h2>通知渠道与投递台账</h2>
          <p class="wb-note">事件→渠道全部可配置；未配置凭据的渠道不参与投递，投递失败会留在台账并进入审计。系统不替组织自动外发。</p></div>
          <button v-if="session.can(PERM.CONFIG_MANAGE)" class="btn btn--quiet" type="button" :disabled="busy" @click="selfTest">{{ busy ? '投递中…' : '发起渠道自检' }}</button></div>
          <div v-if="channels.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>渠道</th><th>用途</th><th>凭据</th><th>已配置路由</th></tr></thead><tbody>
            <tr v-for="row in channels" :key="row.name"><td>{{ row.name }}</td><td>{{ row.description }}</td><td>{{ row.configured ? '已就绪' : '未配置（不投递）' }}</td><td>{{ routedEvents(row.name) || '未路由' }}</td></tr></tbody></table></div>
          <p v-else class="wb-note">尚无已登记渠道。</p>
          <div v-if="deliveries.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>时间</th><th>事件</th><th>渠道</th><th>状态</th><th>尝试</th><th>说明</th></tr></thead><tbody>
            <tr v-for="row in deliveries" :key="row.id"><td>{{ formatDate(row.created_at) }}</td><td>{{ eventText[row.event] ?? row.event }}</td><td>{{ row.channel }}</td><td>{{ deliveryText[row.status] ?? row.status }}</td><td>{{ row.attempts }}</td><td>{{ row.last_error ?? '—' }}</td></tr></tbody></table></div>
          <p v-else class="wb-empty">暂无投递记录。配置路由或发起自检后在此留痕。</p>
        </section>
      </section>
      <section v-else-if="tab === 'records'" class="wb-stack">
        <div class="wb-toolbar"><div><h2 class="u-title-sub">问答记录</h2>
          <p class="wb-note">集中查看本租户的问答记录：可核对谁在什么时候问了什么、是否拒答、有没有依据、用的是哪个级别的数据；每条记录还留有生成它时的版本（提示词 / 工作流契约），功能上线前的记录标"未留痕"——不按当前配置倒推，否则旧答案会被说成新版本的产物。提问人本人删除的记录默认不显示，勾选后可查看——删除只是不再显示，不是销毁证据。</p></div>
          <button class="btn btn--quiet" type="button" :disabled="busy || !records.length" @click="exportRecords">{{ busy ? '导出中…' : '导出当前筛选（Excel）' }}</button></div>
        <form class="wb-section wb-stack" @submit.prevent="recordPage=1; loadTab()"><div class="wb-grid">
          <label class="wb-field"><span>提问人编号</span><input class="input" v-model="recordFilters.user_id" /></label><label class="wb-field"><span>问题或回答包含</span><input class="input" v-model="recordFilters.keyword" maxlength="100" placeholder="如：转正" /></label>
          <label class="wb-field"><span>数据级别</span><select class="select" v-model="recordFilters.data_level"><option value="">全部级别</option><option v-for="level in ['public','internal','sensitive','classified']" :key="level" :value="level">{{ levelText[level] }}</option></select></label>
          <label class="wb-field"><span>回答结果</span><select class="select" v-model="recordFilters.result"><option value="">全部结果</option><option value="answered">已作答</option><option value="refused">无依据拒答</option></select></label>
          <label class="wb-field"><span>依据情况</span><select class="select" v-model="recordFilters.evidence"><option value="">全部</option><option value="with">有依据</option><option value="without">无依据</option></select></label>
          <label class="wb-field"><span>开始时间（北京时间）</span><input class="input" v-model="recordFilters.start_at" type="datetime-local" /></label><label class="wb-field"><span>结束时间（北京时间）</span><input class="input" v-model="recordFilters.end_at" type="datetime-local" /></label>
          <label class="wb-check"><input v-model="recordFilters.include_deleted" type="checkbox" />包含提问人已删除的记录</label>
        </div><div class="wb-actions"><button class="btn btn--primary" type="submit">查询问答记录</button><button class="btn btn--quiet" type="button" @click="resetRecordFilters">清空条件</button></div></form>
        <p class="wb-note">当前范围：{{ recordScope || '未筛选' }}。</p>
        <div v-if="records.length" class="wb-table-wrap"><table class="wb-table"><thead><tr><th>时间</th><th>提问人</th><th>问题</th><th>数据级别</th><th>结果</th><th>依据</th><th>引用</th><th>状态</th><th>版本</th></tr></thead><tbody>
          <tr v-for="row in records" :key="row.id"><td>{{ formatDate(row.created_at) }}</td><td>{{ row.asker }}<small>{{ row.username }}</small></td><td>{{ row.question }}</td>
            <td>{{ levelText[row.data_level] ?? row.data_level }}</td><td>{{ row.refused ? '无依据拒答' : '已作答' }}</td><td>{{ row.has_sufficient_evidence ? '有依据' : '无依据' }}</td><td>{{ row.citation_count }}</td><td>{{ row.is_deleted ? '提问人已删除' : '正常' }}</td>
            <td>{{ fingerprintText(row.versions) || '未留痕（功能上线前的记录）' }}</td></tr></tbody></table></div>
        <p v-else class="wb-empty">当前范围没有问答记录。可清空条件或放宽时间范围再看；跨租户记录需平台管理员指定租户。</p>
        <div class="wb-pager"><button class="btn btn--quiet" type="button" :disabled="recordPage===1" @click="recordPage--; loadTab()">上一页</button><span>第 {{ recordPage }} 页 · 共 {{ recordTotal }} 条</span><button class="btn btn--quiet" type="button" :disabled="recordPage*40>=recordTotal" @click="recordPage++; loadTab()">下一页</button></div>
      </section>
    </WorkspaceTabs>
    <ActionDialog :open="Boolean(dialog)" :title="({organization:'维护组织',user:'维护用户',tenant:'登记或维护租户',submit:'提交人工审核',decision:'审核材料与结论',job:'创建任务',archive:'电子记录效力确认'} as Record<string,string>)[dialog] ?? '管理'" :busy="busy" wide @close="dialog=''">
      <form class="wb-stack" @submit.prevent="submit">
        <p v-if="error" class="wb-error" role="alert">{{ error }}</p>
        <template v-if="['organization','user','tenant'].includes(dialog)">
          <label class="wb-field"><span>名称</span><input class="input" v-model="form.name" required :maxlength="dialog==='user' ? 50 : 100" /></label>
          <template v-if="dialog==='organization'"><label v-if="!editingId" class="wb-field"><span>组织类型</span><select class="select" v-model="form.org_type"><option value="school">学校</option><option value="department">院系</option><option value="branch">支部</option></select></label>
            <label class="wb-field"><span>上级组织</span><select class="select" v-model="form.parent_id" aria-label="上级组织"><option value="">无上级（学校根组织）</option><option v-for="row in activeOrgs.filter(row=>row.id!==editingId)" :key="row.id" :value="row.id">{{ row.name }}</option></select></label></template>
          <template v-if="dialog==='user'"><label v-if="!editingId" class="wb-field"><span>登录账号</span><input class="input" v-model="form.username" required minlength="3" maxlength="50" autocomplete="off" /></label>
            <label v-if="!editingId" class="wb-field"><span>初始密码（至少 12 字符）</span><input class="input" v-model="form.password" type="password" required minlength="12" maxlength="72" autocomplete="new-password" /></label>
            <label class="wb-field"><span>授权角色</span><select class="select" v-model="form.role"><option v-for="role in roles" :key="role" :value="role">{{ ROLE_LABELS[role] }}</option></select></label>
            <label class="wb-field"><span>所属组织</span><select class="select" v-model="form.org_unit_id"><option value="">待绑定</option><option v-for="row in activeOrgs" :key="row.id" :value="row.id">{{ row.name }}</option></select></label></template>
          <template v-if="dialog==='tenant' && !editingId"><label class="wb-field"><span>租户类型</span><select class="select" v-model="form.tenant_type"><option value="school">学校</option><option value="department">院系</option><option value="branch">支部</option></select></label>
            <label class="wb-field"><span>父租户</span><select class="select" v-model="form.parent_id" required><option v-for="row in tenants.filter(row=>row.is_active)" :key="row.id" :value="row.id">{{ row.name }}</option></select></label></template>
          <label v-if="editingId" class="wb-check"><input v-model="form.is_active" type="checkbox" />保持有效（取消将停用）</label>
        </template>
        <template v-else-if="dialog==='submit'"><label class="wb-field"><span>业务类型</span><select class="select" v-model="form.source_kind"><option v-for="kind in ['score','vote','meeting','study_activity','study_plan','assessment_report','assessment_plan']" :key="kind" :value="kind">{{ kindText[kind] }}</option></select></label>
          <label class="wb-field"><span>{{ form.source_kind==='vote' ? '选优批次编号' : '业务对象编号' }}</span><input class="input" v-model="form.source_id" required maxlength="200" /></label><label class="wb-field"><span>统计年度</span><input class="input" v-model.number="form.year" type="number" min="2000" max="2100" required /></label>
          <label v-if="form.source_kind==='vote'" class="wb-field"><span>投票轮次</span><input class="input" v-model.number="form.round" type="number" min="1" max="100" required /></label><p class="wb-note">审核材料由系统读取当前授权内容，提交后保留该版本快照。</p></template>
        <template v-else-if="dialog==='decision' && detail"><p>{{ kindText[detail.source_kind] }} · {{ statusText[detail.effective_status] }} · {{ detail.source_id }}</p>
          <article class="governance__snapshot">{{ snapshotText || '请核对以下材料和来源。' }}</article>
          <details><summary>完整材料与依据</summary><pre class="governance__snapshot">{{ JSON.stringify(detail.snapshot,null,2) }}</pre></details>
          <p v-if="detail.stale" class="wb-error">源内容已变化，当前快照不能继续审核，请重新提交。</p>
          <p v-if="detail.submitted_by===session.state.user?.id" class="wb-note">你是此版本提交人，须由另一位授权人员审核。</p>
          <p v-if="detail.opinion">既有意见：{{ detail.opinion }}</p>
          <template v-if="detail.status==='pending' && !detail.stale && detail.submitted_by!==session.state.user?.id"><label class="wb-field"><span>人工结论</span><select class="select" v-model="form.decision"><option value="approved">通过</option><option value="returned">退回补充</option></select></label><label class="wb-field"><span>审核意见</span><textarea class="textarea" v-model="form.opinion" required rows="4" maxlength="2000" /></label></template>
        </template>
        <template v-else-if="dialog==='job'"><label class="wb-field"><span>任务类型</span><select class="select" v-model="form.kind"><option value="member_reminders">发展党员提醒扫描</option><option value="assessment_reminders">考核提醒扫描</option><option value="embedding">文档批量向量化</option></select></label><label class="wb-field"><span>去重编号</span><input class="input" v-model="form.dedup_key" required maxlength="160" /></label>
          <label v-if="form.kind==='embedding'" class="wb-field"><span>文档内部编号（每行一个，最多 50 个）</span><textarea class="textarea" v-model="form.document_ids" required rows="4" /></label></template>
        <template v-else-if="dialog==='archive'"><p class="wb-note">只有学校授权人员完成正式确认后，才启用电子归档。未确认时保持关闭。</p><label class="wb-check"><input v-model="form.enabled" type="checkbox" />学校已确认电子记录效力</label><label class="wb-field"><span>学校确认或撤销依据</span><textarea class="textarea" v-model="form.evidence" required maxlength="2000" rows="4" /></label></template>
        <div class="wb-actions"><button v-if="dialog!=='decision' || (detail?.status==='pending' && !detail.stale && detail.submitted_by!==session.state.user?.id)" class="btn btn--primary" type="submit" :disabled="busy">{{ busy ? '保存中…' : dialog==='decision' ? '保存人工结论' : '保存' }}</button>
          <button class="btn btn--quiet" type="button" :disabled="busy" @click="dialog=''">关闭</button></div>
      </form>
    </ActionDialog>
  </div>
</template>

<style scoped>
.governance { width:100%; max-width:1280px; margin:0 auto; padding:var(--space-6); }
@media (max-width:767px) { .governance { padding:var(--space-4); } }
.governance__notice { padding:var(--space-3); border-left:3px solid var(--accent); background:var(--paper-raised); }
.governance__admission { padding:var(--space-5); border:var(--border); border-left:4px solid var(--accent); background:var(--paper-raised); border-radius:var(--radius-md); }
.governance__admission h2 { margin-bottom:var(--space-2); font-size:var(--text-lg); }
.governance__admission p + p { margin-top:var(--space-2); }
.governance .wb-table { min-width:640px; }
.governance__id { max-width:230px; overflow-wrap:anywhere; font-family:var(--font-mono); font-size:var(--text-sm); }
.governance__facts { display:flex; flex-wrap:wrap; gap:var(--space-6); margin:var(--space-4) 0; }
.governance__facts dt { color:var(--ink-soft); font-size:var(--text-sm); }
.governance__facts dd { margin-top:var(--space-2); font-size:var(--text-2xl); font-variant-numeric:tabular-nums; }
/* 版本变更单元格：同一次配置提交可能同时改了多个提示词，逐条成行显示 */
.governance__change { display:block; white-space:nowrap; font-variant-numeric:tabular-nums; }
.governance__snapshot { white-space:pre-wrap; overflow-wrap:anywhere; max-height:400px; overflow:auto; padding:var(--space-4); border:var(--border); border-radius:var(--radius-sm); font-size:var(--text-sm); }
small { display:block; color:var(--ink-soft); overflow-wrap:anywhere; }
details summary { cursor:pointer; margin-bottom:var(--space-3); }
</style>
