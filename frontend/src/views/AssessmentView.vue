<script setup lang="ts">
import { computed, onMounted, reactive, ref, toRaw } from 'vue'

import { assessmentApi } from '@/api/assessment'
import type { AssessmentEvidence, AssessmentIndicator, AssessmentOrg, AssessmentRunDetail, AssessmentSource, AssessmentTask, AssessmentWorkspace, IndicatorInput, SourceReference, TaskInput } from '@/api/assessment'
import { ApiError } from '@/api/http'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

const orgs = ref<AssessmentOrg[]>([])
const filters = reactive({ year: new Date().getFullYear(), org: '' })
const workspace = ref<AssessmentWorkspace | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const busy = ref(false)
const actionError = ref('')
const success = ref('')
const tab = ref('indicators')
const tabs = [{ id: 'indicators', label: '指标与归集' }, { id: 'tasks', label: '年度任务' }, { id: 'evidence', label: '佐证与缺项' }, { id: 'plan', label: '计划草案' }, { id: 'reminders', label: '提醒与设置' }]
const labels: Record<AssessmentSource, string> = { organizations: '组织建设', members: '人员阶段登记', member_materials: '人员材料核验', meetings: '组织生活', studies: '中心组学习', documents: '制度文件', manual: '人工特色创新' }
const reviewLabels: Record<string, string> = { pending: '待人工审核', approved: '人工审核通过', returned: '退回补充' }
const reminderLabels: Record<string, string> = { overdue: '任务逾期', due_soon: '临近任务期限', missing_evidence: '来源或佐证缺项' }
const reminderStates: Record<string, string> = { open: '待处理', handled: '已登记处理', resolved: '条件已解除' }
const canManage = computed(() => session.can('assessment.manage'))
const canReview = computed(() => session.can('assessment.review'))
const canConfigure = computed(() => session.can('assessment.configure') && filters.org === workspace.value?.school_org_id)
const currentRun = computed(() => workspace.value?.runs.find((run) => run.fingerprint === workspace.value?.fingerprint) ?? null)
const activeRules = computed(() => workspace.value?.indicators.filter((rule) => rule.active) ?? [])
const missingCount = computed(() => workspace.value?.results.filter((result) => result.missing.length).length ?? 0)
let sequence = 0

async function load(): Promise<void> {
  const token = ++sequence
  loading.value = true
  error.value = null
  workspace.value = null
  sourceDetail.value = null
  historyDetail.value = null
  try {
    if (!filters.org) return
    const value = await assessmentApi.workspace(filters.org, filters.year)
    if (token !== sequence) return
    workspace.value = value
    planDraft.value = value.plan?.content ?? ''
    Object.assign(policy, value.policy)
  } catch (err) {
    if (token === sequence) error.value = err
  } finally {
    if (token === sequence) loading.value = false
  }
}

onMounted(async () => {
  try {
    orgs.value = await assessmentApi.organizations()
    filters.org = orgs.value.find((org) => org.id === session.state.user?.org_unit_id)?.id ?? orgs.value[0]?.id ?? ''
    await load()
    if (filters.org) await assessmentApi.sync(filters.org, filters.year).then(load)
  } catch (err) { error.value = err; loading.value = false }
})

async function act(operation: () => Promise<unknown>, message: string, after?: () => void): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  success.value = ''
  try {
    await operation()
    after?.()
    success.value = message
    await load()
  } catch (err) {
    actionError.value = err instanceof ApiError || err instanceof Error ? err.message : '操作失败，请重试'
  } finally { busy.value = false }
}

const ruleOpen = ref(false)
const rule = reactive<IndicatorInput>({ org_unit_id: '', year: filters.year, code: '', name: '', requirement: '', source: 'organizations',
  formula: 'count', source_options: { measure: 'count', stages: [], org_types: [], required_materials: [], document_ids: [] },
  target: 1, comparison: 'gte', unit: '项', period_start: '', period_end: '', required_evidence: [], confirmed: false, confirmation_note: '', expected_version: 0 })
const evidenceNames = ref('')
const stages = ref('')
const documentIds = ref('')
const effective = ref('')
const lines = (text: string) => [...new Set(text.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean))]
function editRule(existing?: AssessmentIndicator): void {
  Object.assign(rule, { org_unit_id: filters.org, year: filters.year, code: '', name: '', requirement: '', source: 'organizations', formula: 'count',
    source_options: { measure: 'count', stages: [], org_types: [], required_materials: [], document_ids: [] }, target: 1, comparison: 'gte', unit: '项',
    period_start: `${filters.year}-01-01`, period_end: `${filters.year}-12-31`, required_evidence: [], confirmed: false, confirmation_note: '', expected_version: 0, effective_from: undefined })
  if (existing) {
    Object.assign(rule, structuredClone(toRaw(existing)), { org_unit_id: filters.org,
      expected_version: Math.max(...(workspace.value?.indicators.filter((item) => item.code === existing.code).map((item) => item.version) ?? [existing.version])) })
  }
  evidenceNames.value = rule.required_evidence.join('\n')
  stages.value = rule.source_options.stages.join(',')
  documentIds.value = rule.source_options.document_ids.join('\n')
  effective.value = ''
  ruleOpen.value = true
}
function sourceChanged(): void {
  rule.source_options.measure = rule.source === 'manual' ? 'sum' : rule.source === 'member_materials' ? 'material_rate' : 'count'
}
function saveRule(): void {
  const measure = rule.source_options.measure
  const body: IndicatorInput = {
    org_unit_id: filters.org, year: filters.year, code: rule.code, name: rule.name, requirement: rule.requirement,
    source: rule.source, formula: measure === 'sum' ? 'sum' : measure === 'count' ? 'count' : 'percentage',
    source_options: { ...rule.source_options, stages: lines(stages.value), document_ids: lines(documentIds.value) },
    target: rule.target, comparison: rule.comparison, unit: rule.unit, period_start: rule.period_start, period_end: rule.period_end,
    required_evidence: lines(evidenceNames.value), confirmed: rule.confirmed, confirmation_note: rule.confirmation_note,
    expected_version: rule.expected_version, ...(effective.value ? { effective_from: new Date(effective.value).toISOString() } : {}),
  }
  void act(() => assessmentApi.indicator(body), '指标新版本已保存，请重新归集。', () => { ruleOpen.value = false })
}

const taskOpen = ref(false)
const editingTask = ref<AssessmentTask | null>(null)
const task = reactive<TaskInput>({ org_unit_id: '', year: filters.year, indicator_code: '', title: '', owner_id: '', due_date: '', declared_progress: 0, manual_value: null, completed_on: null, basis: '' })
const taskManual = computed(() => activeRules.value.find((item) => item.code === task.indicator_code)?.source === 'manual')
async function editTask(existing?: AssessmentTask): Promise<void> {
  if (existing && existing.org_unit_id !== filters.org) { filters.org = existing.org_unit_id; await load() }
  editingTask.value = existing ?? null
  Object.assign(task, { org_unit_id: filters.org, year: filters.year, indicator_code: activeRules.value[0]?.code ?? '', title: '',
    owner_id: workspace.value?.owners[0]?.id ?? '', due_date: `${filters.year}-12-31`, declared_progress: 0, manual_value: null, completed_on: null, basis: '' })
  if (existing) {
    for (const key of Object.keys(task) as (keyof TaskInput)[]) Object.assign(task, { [key]: existing[key] })
  }
  taskOpen.value = true
}
function saveTask(): void {
  const body: TaskInput = { ...task, manual_value: taskManual.value ? task.manual_value : null, completed_on: task.completed_on || null }
  void act(() => assessmentApi.task(body, editingTask.value?.id, editingTask.value?.revision), '任务已保存，数值及完成情况仍须核验。', () => { taskOpen.value = false })
}

const link = reactive({ indicator_code: '', requirement_key: '', doc_id: '' })
const linkRule = computed(() => activeRules.value.find((item) => item.code === link.indicator_code))
function addEvidence(): void {
  void act(() => assessmentApi.evidence({ ...link, org_unit_id: filters.org, year: filters.year }), '已绑定真实材料版本，须由另一位授权人员审核。', () => { link.doc_id = '' })
}
const opinions = reactive<Record<string, string>>({})
function review(kind: string, item: { id: string; revision: number }, status: 'approved' | 'returned'): void {
  const opinion = opinions[item.id]?.trim()
  if (!opinion) { actionError.value = '请先填写审核意见。'; return }
  void act(() => assessmentApi.review(kind, item.id, item.revision, status, opinion), '人工审核结果已保存。')
}
function reviewable(item: { created_by?: string }): boolean { return canReview.value && item.created_by !== session.state.user?.id }

const planDraft = ref('')
function createPlan(edited = false): void {
  if (!currentRun.value) return
  void act(() => assessmentApi.plan(currentRun.value!.id, workspace.value?.plan?.version ?? 0, edited ? planDraft.value : undefined), '已保存待人工研究与审核的计划新版本。')
}
const policy = reactive({ version: 0, archive_version: 0, archive_enabled: false, reminder_advance_days: 14, confirmation_note: '' })
const handling = reactive<Record<string, string>>({})
function handleReminder(id: string): void {
  if (!handling[id]?.trim()) { actionError.value = '请填写提醒处理结果。'; return }
  void act(() => assessmentApi.handle(id, handling[id]!), '处理记录已保存，任务完成状态仍以归集为准。')
}
const sourceDetail = ref<SourceReference | null>(null)
const historyDetail = ref<AssessmentRunDetail | null>(null)
function recalculate(): void { void act(() => assessmentApi.recalculate(filters.org, filters.year), '归集已保存，同一输入不会重复计数。') }
function archiveEvidence(): void { if (currentRun.value) void act(() => assessmentApi.archive(currentRun.value!.id), '已归档审核后的佐证目录与学校确认版本。') }
function scanReminders(): void { void act(() => assessmentApi.sync(filters.org, filters.year), '已扫描到期与缺项事项，重复扫描不会重复生成提醒。') }
function savePolicy(): void { void act(() => assessmentApi.policy({ ...policy, org_unit_id: filters.org }), '提醒配置与学校电子记录确认已保存。') }
async function showSource(reference: SourceReference): Promise<void> {
  actionError.value = ''
  try { sourceDetail.value = await assessmentApi.source(reference, filters.org, filters.year) }
  catch (err) { actionError.value = err instanceof Error ? err.message : '来源读取失败' }
}
async function showHistory(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  try { historyDetail.value = await assessmentApi.run(id) }
  catch (err) { actionError.value = err instanceof Error ? err.message : '历史归集读取失败' }
  finally { busy.value = false }
}
async function download(): Promise<void> {
  if (!currentRun.value || busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    const blob = await assessmentApi.export(currentRun.value.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `党建考核-${filters.year}-${filters.org}.zip`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    success.value = '已导出授权指标表、任务统计及佐证目录，审核与缺项状态保留在材料中。'
  } catch (err) { actionError.value = err instanceof Error ? err.message : '导出失败' }
  finally { busy.value = false }
}
function evidenceReview(item: AssessmentEvidence, status: 'approved' | 'returned'): void { review('evidence', item, status) }
</script>

<template>
  <div class="assessment">
    <PageHeader title="党建考核与年度规划" description="按年度和组织归集一次登记的业务数据，核查缺项与佐证，形成可人工修订的计划草案。" />
    <div class="notice">真实学校指标与人工台账对照待验收。统计与计划供组织人员研究；正式评价须经人工审核。</div>
    <div class="toolbar">
      <label>年度 <input v-model.number="filters.year" aria-label="考核年度" type="number" min="2000" max="2100" :disabled="busy" @change="load" /></label>
      <label>组织 <select v-model="filters.org" aria-label="考核组织" :disabled="busy" @change="load"><option v-for="org in orgs" :key="org.id" :value="org.id">{{ org.name }}</option></select></label>
      <button class="btn btn--ghost" :disabled="busy || loading || !filters.org" @click="load">刷新状态</button>
      <button v-if="canManage" class="btn btn--primary" :disabled="busy || loading || !activeRules.length" @click="recalculate">重新归集</button>
      <button v-if="session.can('assessment.export')" class="btn btn--ghost" :disabled="busy || !currentRun" @click="download">导出材料目录</button>
    </div>
    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <p v-if="success" class="success" role="status">{{ success }}</p>
    <LoadingBlock v-if="loading" label="加载考核台账…" />
    <ErrorState v-else-if="error" :error="error" @retry="load" />
    <EmptyState v-else-if="!filters.org" title="暂无可管理组织" description="请先绑定有效学校、院系或支部组织。" />
    <template v-else-if="workspace">
      <div class="summary"><span>{{ workspace.year }} · {{ workspace.org_name }}</span><span>截至 {{ workspace.as_of }}</span><span>{{ workspace.results.length }} 项指标 · {{ missingCount }} 项有缺项</span><span class="badge">{{ workspace.needs_recalculation ? '规则或数据已变化，需重新归集' : '归集与当前数据一致' }}</span></div>
      <div class="tabs" role="tablist" aria-label="考核工作台"><button v-for="item in tabs" :key="item.id" role="tab" :aria-selected="tab === item.id" :class="{ selected: tab === item.id }" @click="tab = item.id">{{ item.label }}</button></div>
      <section v-if="tab === 'indicators'" class="panel">
        <div class="panel-head"><h2>指标与可复核归集</h2><button v-if="canConfigure" class="btn btn--ghost" :disabled="busy" @click="editRule()">新增指标</button></div>
        <p v-if="session.can('assessment.configure') && !canConfigure" class="muted">选择学校组织后可维护学校指标版本。</p>
        <p v-if="!workspace.results.length" class="muted">本年度暂无已生效指标；尚未导入或确认真实学校指标。</p>
        <article v-for="result in workspace.results" :key="result.code" class="record">
          <div class="record-head"><h3>{{ result.code }} · {{ result.name }}</h3><span class="badge">规则 v{{ result.rule_version }}</span><span class="badge" :class="result.satisfied === true ? 'badge--ok' : ''">{{ result.satisfied === null ? '待核验' : result.satisfied ? '满足配置规则' : '未满足配置规则' }}</span></div>
          <p>{{ result.requirement }}</p><p class="metric">实际：{{ result.actual === null ? '待补' : `${result.actual} ${result.unit}` }}　目标：{{ result.target }} {{ result.unit }}</p>
          <p class="muted">{{ labels[result.source] }} · {{ result.period_start }} 至 {{ result.period_end }}</p>
          <ul v-if="result.missing.length" class="missing"><li v-for="message in result.missing" :key="message">{{ message }}</li></ul>
          <details><summary>来源记录（{{ result.sources.length }}）</summary><button v-for="reference in result.sources" :key="reference.record_id" class="source" @click="showSource(reference)">{{ reference.occurred_on }} · {{ reference.record_id }} · 查看授权来源</button><p v-if="!result.sources.length" class="muted">暂无可核查的授权来源，未默认为完成。</p></details>
        </article>
        <details v-if="workspace.indicators.length"><summary>指标规则与生效版本</summary><div v-for="item in workspace.indicators" :key="item.id" class="version"><span>{{ item.code }} v{{ item.version }} · {{ item.active ? '当前生效' : '历史或待生效' }} · {{ item.effective_from }} · {{ item.confirmed ? '人工确认口径' : '口径待确认' }}</span><button v-if="canConfigure" class="btn btn--quiet" :disabled="busy" @click="editRule(item)">修订版本</button></div></details>
        <details v-if="workspace.runs.length"><summary>历史归集与计算版本</summary><div v-for="item in workspace.runs" :key="item.id" class="version"><span>{{ item.created_at }} · {{ item.engine_version }} · {{ reviewLabels[item.review_status] }} · {{ item.stale ? '历史快照' : '当前输入' }}</span><button class="btn btn--quiet" :disabled="busy" @click="showHistory(item.id)">核查归集版本</button></div></details>
        <form v-if="ruleOpen && canConfigure" class="form" @submit.prevent="saveRule">
          <h3>{{ rule.expected_version ? '追加指标版本' : '新增学校指标' }}</h3>
          <div class="grid"><label>指标编码<input v-model="rule.code" required maxlength="64" :readonly="!!rule.expected_version" /></label><label>指标名称<input v-model="rule.name" required maxlength="200" /></label></div>
          <label>考核要求<textarea v-model="rule.requirement" required maxlength="4000" /></label>
          <div class="grid"><label>数据源<select v-model="rule.source" @change="sourceChanged"><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label><label>统计口径<select v-model="rule.source_options.measure"><option v-if="rule.source !== 'manual' && rule.source !== 'member_materials'" value="count">去重记录次数/人数</option><option v-if="['meetings', 'studies'].includes(rule.source)" value="attendance_rate">实到 / 应到 × 100</option><option v-if="['member_materials', 'meetings', 'studies'].includes(rule.source)" value="material_rate">完整材料 / 记录数 × 100</option><option v-if="rule.source === 'manual'" value="sum">已审核人工值求和</option></select></label></div>
          <div class="grid"><label>目标值<input v-model.number="rule.target" type="number" min="0" max="1000000000000" step="any" required /></label><label>判定条件<select v-model="rule.comparison"><option value="gte">实际值 ≥ 目标</option><option value="lte">实际值 ≤ 目标</option><option value="eq">实际值 = 目标</option></select></label><label>单位<input v-model="rule.unit" required maxlength="20" /></label></div>
          <div class="grid"><label>统计开始<input v-model="rule.period_start" type="date" required /></label><label>统计结束<input v-model="rule.period_end" type="date" required /></label><label>生效时间（留空立即生效）<input v-model="effective" type="datetime-local" /></label></div>
          <label v-if="['members', 'member_materials'].includes(rule.source)">阶段筛选（applicant / activist / candidate / probationary / formal，逗号分隔）<input v-model="stages" /></label>
          <label v-if="rule.source === 'organizations'">组织类别<select v-model="rule.source_options.org_types" multiple><option value="school">学校</option><option value="department">院系</option><option value="branch">支部</option></select></label>
          <label v-if="rule.source === 'documents'">制度文件编号（留空使用授权有效制度；每行一项）<textarea v-model="documentIds" /></label>
          <label>佐证清单（每行一个材料类别）<textarea v-model="evidenceNames" /></label>
          <label class="check"><input v-model="rule.confirmed" type="checkbox" />已取得学校指标口径确认</label><label>指标确认依据<textarea v-model="rule.confirmation_note" :required="rule.confirmed" maxlength="2000" /></label>
          <div class="actions"><button class="btn btn--primary" :disabled="busy">保存指标版本</button><button type="button" class="btn btn--quiet" @click="ruleOpen = false">取消</button></div>
        </form>
        <div v-if="currentRun" class="review"><h3>本次归集：{{ reviewLabels[currentRun.review_status] }}</h3><p>{{ currentRun.review_opinion }}</p><template v-if="reviewable(currentRun)"><label>归集审核意见<textarea v-model="opinions[currentRun.id]" maxlength="2000" /></label><div class="actions"><button class="btn btn--ghost" :disabled="busy || !!missingCount" @click="review('runs', currentRun, 'approved')">确认已核查归集</button><button class="btn btn--quiet" :disabled="busy" @click="review('runs', currentRun, 'returned')">退回补充</button></div></template></div>
      </section>
      <section v-else-if="tab === 'tasks'" class="panel">
        <div class="panel-head"><h2>年度任务与完成进度</h2><button v-if="canManage" class="btn btn--ghost" :disabled="busy || !activeRules.length" @click="editTask()">新增年度任务</button></div>
        <p v-if="!workspace.tasks.length" class="muted">暂无任务，先选择已生效指标、责任用户与期限。</p>
        <article v-for="item in workspace.tasks" :key="item.id" class="record"><div class="record-head"><h3>{{ item.title }}</h3><span class="badge">{{ item.complete ? '完成' : item.overdue ? '逾期' : item.due_soon ? '临近期限' : '进行中' }}</span><span class="badge">{{ reviewLabels[item.review_status] }}</span></div><p>{{ item.indicator_code }} · 期限 {{ item.due_date }} · 责任用户 {{ item.owner_id }}</p><p>可核查进度 {{ item.progress }}%<span v-if="item.declared_progress !== item.progress">（人工填报 {{ item.declared_progress }}%）</span></p><progress :value="item.progress" max="100" :aria-label="`${item.title}进度`" /><ul class="missing"><li v-for="message in item.missing" :key="message">{{ message }}</li></ul><p v-if="item.basis">录入依据：{{ item.basis }}</p><p v-if="item.review_opinion">审核意见：{{ item.review_opinion }}</p><button v-if="canManage" class="btn btn--quiet" :disabled="busy" @click="editTask(item)">修订任务</button><div v-if="reviewable(item)" class="review"><label>任务审核意见<textarea v-model="opinions[item.id]" maxlength="2000" /></label><div class="actions"><button class="btn btn--ghost" :disabled="busy" @click="review('tasks', item, 'approved')">审核通过</button><button class="btn btn--quiet" :disabled="busy" @click="review('tasks', item, 'returned')">退回补充</button></div></div></article>
        <form v-if="taskOpen" class="form" @submit.prevent="saveTask"><h3>{{ editingTask ? '修订任务' : '新增年度任务' }}</h3><label>任务名称<input v-model="task.title" required maxlength="200" /></label><label>关联指标<select v-model="task.indicator_code" :disabled="!!editingTask" required><option v-for="item in activeRules" :key="item.id" :value="item.code">{{ item.code }} · {{ item.name }}</option></select></label><div class="grid"><label>责任用户<select v-model="task.owner_id" required><option v-for="owner in workspace.owners" :key="owner.id" :value="owner.id">{{ owner.name }}</option></select></label><label>任务期限<input v-model="task.due_date" type="date" required :min="`${filters.year}-01-01`" :max="`${filters.year}-12-31`" /></label></div><label>人工填报进度<input v-model.number="task.declared_progress" type="number" min="0" max="100" required /></label><p class="muted">填报100%仍需来源和佐证核验；自动归集指标按业务数据计算。</p><div v-if="taskManual" class="grid"><label>人工特色项实际值<input v-model.number="task.manual_value" type="number" min="0" step="any" required /></label><label>实际完成日期<input v-model="task.completed_on" type="date" required /></label></div><label>录入或修订依据<textarea v-model="task.basis" maxlength="4000" :required="taskManual" /></label><div class="actions"><button class="btn btn--primary" :disabled="busy || !workspace.owners.length">保存任务</button><button type="button" class="btn btn--quiet" @click="taskOpen = false">取消</button></div></form>
      </section>
      <section v-else-if="tab === 'evidence'" class="panel">
        <h2>缺项与佐证版本</h2><p class="muted">只能关联现有且有权查看的知识文件；原材料修订后须重新绑定及审核。</p>
        <article v-for="result in workspace.results" :key="result.code" class="record"><h3>{{ result.code }} · {{ result.name }}</h3><ul class="missing"><li v-for="message in result.missing" :key="message">{{ message }}</li></ul><p v-if="!result.missing.length">本次归集未发现缺项，仍须人工核查。</p></article>
        <article v-for="item in workspace.evidence" :key="item.id" class="record"><h3>{{ item.requirement_key }} · {{ item.title ?? '无权限或材料已删除' }}</h3><p>{{ item.indicator_code }} · {{ item.status }}<span v-if="item.content_revision"> · 文件版本 {{ item.content_revision }}</span></p><p v-if="item.doc_id" class="muted">原文件编号：{{ item.doc_id }}；版本摘要：{{ item.source_version }}</p><p>{{ item.review_opinion }}</p><div v-if="reviewable(item) && item.doc_id" class="review"><label>材料审核意见<textarea v-model="opinions[item.id]" maxlength="2000" /></label><div class="actions"><button class="btn btn--ghost" :disabled="busy" @click="evidenceReview(item, 'approved')">确认佐证版本</button><button class="btn btn--quiet" :disabled="busy" @click="evidenceReview(item, 'returned')">退回补充</button></div></div></article>
        <form v-if="canManage" class="form" @submit.prevent="addEvidence"><h3>关联真实佐证</h3><label>佐证指标<select v-model="link.indicator_code" required @change="link.requirement_key = ''"><option value="" disabled>选择指标</option><option v-for="item in activeRules" :key="item.id" :value="item.code">{{ item.code }} · {{ item.name }}</option></select></label><label>材料类别<select v-model="link.requirement_key" required><option value="" disabled>选择佐证类别</option><option v-for="key in linkRule?.required_evidence ?? []" :key="key" :value="key">{{ key }}</option></select></label><label>已有文件编号<input v-model="link.doc_id" required maxlength="100" placeholder="知识库中的文档编号" /></label><button class="btn btn--primary" :disabled="busy">绑定材料版本</button></form>
        <button v-if="canManage" class="btn btn--ghost" :disabled="busy || !currentRun || currentRun.review_status !== 'approved' || !workspace.policy.archive_enabled || !!missingCount" @click="archiveEvidence">归档审核后佐证目录</button><p class="muted">{{ workspace.policy.archive_enabled ? '学校已确认电子归档，仍须人工审核和完整佐证。' : '学校尚未确认电子记录效力，归档关闭。' }}</p>
      </section>
      <section v-else-if="tab === 'plan'" class="panel"><div class="panel-head"><h2>年度工作计划参考</h2><button v-if="canManage" class="btn btn--ghost" :disabled="busy || !currentRun" @click="createPlan()">生成计划草案</button></div><p v-if="!workspace.plan" class="muted">先归集指标，再生成包含重点、任务、责任人与期限的参考草案。</p><template v-else><p>计划 v{{ workspace.plan.version }} · {{ reviewLabels[workspace.plan.review_status] }}</p><p v-if="workspace.plan.stale" class="missing">规则、资料或权限已变化；请重新归集并生成草案，旧版本内容需重新核验。</p><template v-else><label>计划内容（供组织人员研究确定）<textarea v-model="planDraft" class="plan-text" :readonly="!canManage" maxlength="30000" /></label><button v-if="canManage" class="btn btn--ghost" :disabled="busy || !currentRun || !planDraft.trim()" @click="createPlan(true)">保存计划修订版本</button><div v-if="reviewable(workspace.plan)" class="review"><label>计划审核意见<textarea v-model="opinions[workspace.plan.id]" maxlength="2000" /></label><div class="actions"><button class="btn btn--ghost" :disabled="busy" @click="review('plans', workspace.plan, 'approved')">人工确认计划</button><button class="btn btn--quiet" :disabled="busy" @click="review('plans', workspace.plan, 'returned')">退回修订</button></div></div></template><p>{{ workspace.plan.review_opinion }}</p></template></section>
      <section v-else class="panel"><div class="panel-head"><h2>我的责任事项提醒</h2><button class="btn btn--ghost" :disabled="busy" @click="scanReminders">扫描提醒</button></div><p v-if="!workspace.reminders.length" class="muted">当前用户暂无提醒；只有责任人可以登记处理结果。</p><article v-for="item in workspace.reminders" :key="item.id" class="record"><h3>{{ reminderLabels[item.kind] ?? item.kind }}</h3><p>任务 {{ item.task_id }} · {{ reminderStates[item.status] }}</p><p>{{ item.handling_note }}</p><template v-if="item.status === 'open'"><label>提醒处理结果<textarea v-model="handling[item.id]" maxlength="2000" /></label><button class="btn btn--ghost" :disabled="busy" @click="handleReminder(item.id)">登记处理结果</button></template></article><form v-if="canConfigure" class="form" @submit.prevent="savePolicy"><h3>学校提醒与统一归档确认</h3><label>提前提醒天数<input v-model.number="policy.reminder_advance_days" type="number" min="0" max="90" required /></label><label class="check"><input v-model="policy.archive_enabled" type="checkbox" />学校组织部门已确认电子记录效力，启用统一电子归档</label><label>学校确认依据或撤销说明<textarea v-model="policy.confirmation_note" :required="policy.archive_enabled" maxlength="2000" /></label><p class="muted">此确认由组织生活、学习和考核共用；撤销后停止电子归档。</p><button class="btn btn--primary" :disabled="busy">保存学校确认</button></form></section>
      <section v-if="historyDetail" class="panel" aria-label="历史归集详情"><div class="panel-head"><h2>历史归集核查</h2><button class="btn btn--quiet" @click="historyDetail = null">关闭历史详情</button></div><p>{{ historyDetail.created_at }} · {{ historyDetail.engine_version }} · {{ reviewLabels[historyDetail.review_status] }}</p><p class="muted">{{ historyDetail.notice }}</p><p v-if="historyDetail.stale" class="missing">此版本与当前规则或数据有差异。</p><article v-for="result in historyDetail.results" :key="result.code" class="record"><h3>{{ result.code }} · {{ result.name }} · 规则 v{{ result.rule_version }}</h3><p>{{ result.requirement }}</p><p>历史实际：{{ result.actual === null ? '待核验' : `${result.actual} ${result.unit}` }} · 目标 {{ result.target }} {{ result.unit }}</p><ul class="missing"><li v-for="message in result.missing" :key="message">{{ message }}</li></ul><button v-for="reference in result.sources" :key="reference.record_id" class="source" @click="showSource(reference)">{{ reference.record_id }} · 查看当前授权来源</button></article><p v-if="historyDetail.review_opinion">审核意见：{{ historyDetail.review_opinion }}</p></section>
      <section v-if="sourceDetail" class="panel" aria-label="授权来源详情"><div class="panel-head"><h2>来源记录核查</h2><button class="btn btn--quiet" @click="sourceDetail = null">关闭来源详情</button></div><p>{{ labels[sourceDetail.source] }} · {{ sourceDetail.record_id }} · {{ sourceDetail.occurred_on }}</p><p class="muted">来源版本 {{ sourceDetail.version }}</p><dl><template v-for="(value, key) in sourceDetail.facts" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl></section>
    </template>
  </div>
</template>

<style scoped>
.assessment { display: grid; gap: var(--space-5); padding: var(--space-6); }
.notice { padding: var(--space-3) var(--space-4); border: var(--border); background: var(--accent-wash); color: var(--accent-deep); }
.toolbar, .actions, .summary, .record-head, .panel-head, .version { display: flex; gap: var(--space-3); align-items: center; flex-wrap: wrap; }
.toolbar label { display: flex; align-items: center; gap: var(--space-2); white-space: nowrap; }
.toolbar input { width: 100px; }
.toolbar select { max-width: 300px; }
.summary { color: var(--ink-muted); font-size: var(--text-sm); }
.tabs { display: flex; border-bottom: var(--border); gap: var(--space-2); overflow-x: auto; }
.tabs button { padding: var(--space-3) var(--space-4); white-space: nowrap; color: var(--ink-muted); border-bottom: 2px solid transparent; }
.tabs .selected { border-color: var(--accent); color: var(--accent-deep); }
.panel { border: var(--border); background: var(--paper-raised); padding: var(--space-5); display: grid; gap: var(--space-4); min-width: 0; }
.panel-head { justify-content: space-between; }
h2 { font-size: var(--text-lg); } h3 { font-size: var(--text-md); }
.record { display: grid; gap: var(--space-2); padding-bottom: var(--space-4); border-bottom: var(--border); }
.metric { font-weight: 600; }
.muted, .version { color: var(--ink-muted); font-size: var(--text-sm); }
.missing, .error { color: var(--bad-ink); } .success { color: var(--ok-ink); }
.missing li { margin-top: var(--space-1); }
.form, .review { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--paper-dim); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-4); }
label { display: grid; gap: var(--space-2); font-size: var(--text-sm); }
input, select, textarea { padding: var(--space-2) var(--space-3); border: 1px solid var(--rule-strong); border-radius: var(--radius-sm); background: var(--paper-raised); width: 100%; min-width: 0; }
textarea { min-height: 75px; resize: vertical; } .plan-text { min-height: 360px; line-height: var(--leading-normal); }
.check { display: flex; align-items: center; } .check input { width: auto; }
.source { display: block; color: var(--accent-deep); text-align: left; padding: var(--space-2); overflow-wrap: anywhere; }
p, dd { overflow-wrap: anywhere; } summary { cursor: pointer; padding: var(--space-2) 0; }
progress { width: 100%; height: 8px; accent-color: var(--accent); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: var(--space-2); } dt { color: var(--ink-muted); }
@media (max-width: 720px) { .assessment { padding: var(--space-4); } .panel { padding: var(--space-3); } .toolbar { align-items: stretch; } .toolbar label { width: 100%; } .toolbar select { flex: 1; max-width: none; } }
</style>
