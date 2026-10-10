<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { EXECUTION_LABELS, REVIEW_LABELS, studyApi, type ArchivePolicy, type EvidenceNote, type Minutes, type Participant, type StudyActivity, type StudyItem, type StudyMetrics, type StudyOrganization, type StudyPlan, type StudyRevision, type StudySource } from '@/api/study'
import { PERM } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

const tab = ref<'plans' | 'history' | 'metrics'>('plans')
const filters = reactive({ year: new Date().getFullYear(), org: '', start: '', end: '', topic: '' })
const organizations = ref<StudyOrganization[]>([])
const plans = ref<StudyPlan[]>([])
const selected = ref<StudyPlan | null>(null)
const itemId = ref('')
const activity = ref<StudyActivity | null>(null)
const archives = ref<StudyActivity[]>([])
const metrics = ref<StudyMetrics | null>(null)
const policy = ref<ArchivePolicy>({ enabled: false, revision: 0 })
const policyEvidence = ref('')
const policyEnabled = ref(false)
const total = ref(0)
const page = ref(1)
const busy = ref(false)
const loading = ref(false)
const error = ref<unknown>(null)
const success = ref('')
const reason = ref('')
const showCreate = ref(false)
const showNewItem = ref(false)
const recommendations = ref<StudySource[]>([])
const recommendationMissing = ref<string[]>([])
const materialQuery = ref('')
const revisions = ref<StudyRevision[]>([])
const revisionKind = ref<'plans' | 'activities'>('plans')
const transcriptEl = ref<HTMLTextAreaElement | null>(null)
const excerptSelection = ref({ start: 0, end: 0, quote: '' })
const createForm = reactive({ org_unit_id: '', year: filters.year, title: '', priorities: '', responsible: '', source_ids: '' })
const planForm = reactive({ title: '', priorities: '', responsible: '', source_ids: '' })
const itemForm = reactive({ topic: '', scheduled_on: '', responsible: '', source_ids: [] as string[], agenda: '', outline: '' })
const newItem = reactive({ topic: '', scheduled_on: '', responsible: '', source_ids: '' })
const activityForm = reactive({ held_on: '', host: '', participants: [] as Participant[], transcript: '', minutes: { learning_points: [], consensus: [], requirements: [] } as Minutes })
const canManage = computed(() => session.can(PERM.STUDY_MANAGE))
const canReview = computed(() => session.can(PERM.STUDY_REVIEW))
const canConfirm = computed(() => session.can(PERM.ARCHIVE_CONFIRM))
const planDirty = computed(() => selected.value !== null && (planForm.title !== selected.value.title || planForm.priorities !== selected.value.priorities.join('\n') || planForm.responsible !== selected.value.responsible || planForm.source_ids !== selected.value.source_doc_ids.join('\n')))
const itemDirty = computed(() => activeItem.value !== null && (itemForm.topic !== activeItem.value.topic || itemForm.scheduled_on !== activeItem.value.scheduled_on || itemForm.responsible !== activeItem.value.responsible || JSON.stringify(itemForm.source_ids) !== JSON.stringify(activeItem.value.source_doc_ids) || itemForm.agenda !== activeItem.value.agenda || itemForm.outline !== activeItem.value.outline))
const activeItem = computed(() => selected.value?.items.find((item) => item.id === itemId.value) ?? null)
const canChangeActivity = computed(() => canManage.value && !!activity.value && !activity.value.archived_at && !activity.value.restricted)
const activityDirty = computed(() => activity.value !== null && JSON.stringify(activityPayload()) !== JSON.stringify({ held_on: activity.value.held_on, host: activity.value.host, participants: activity.value.participants, transcript: activity.value.transcript, minutes: normalizeMinutes(activity.value.minutes) }))
const minuteLabels = { learning_points: '学习要点', consensus: '讨论共识', requirements: '工作要求' } as const
type MinuteKey = keyof typeof minuteLabels
let loadSequence = 0
let activitySequence = 0

function lines(text: string): string[] { return [...new Set(text.split('\n').map((line) => line.trim()).filter(Boolean))] }
function normalizeMinutes(value: Partial<Minutes>): Minutes { return { learning_points: (value.learning_points ?? []).map((note) => ({ ...note })), consensus: (value.consensus ?? []).map((note) => ({ ...note })), requirements: (value.requirements ?? []).map((note) => ({ ...note })) } }
function percentage(value: number | null): string { return value === null ? '待补' : `${Math.round(value * 100)}%` }
function organizationName(id: string): string { return organizations.value.find((org) => org.id === id)?.name ?? '组织待配置' }
function sourceScope(value: string): string { return ({ public: '公开资料', school: '校内', department: '所属院系', branch: '所属支部', central: '中央', provincial: '省级' } as Record<string, string>)[value] ?? value }
function displayTime(value: string | null | undefined): string {
  if (!value) return '待补'
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z')
  if (Number.isNaN(date.getTime())) return '时间待核验'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

async function run(action: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null
  success.value = ''
  try { await action() } catch (caught) { error.value = caught } finally { busy.value = false }
}

function revisionPayload(revision: number) {
  if (!reason.value.trim()) throw new Error('请填写操作依据、修订理由或审核意见。')
  return { expected_revision: revision, reason: reason.value.trim() }
}

function clearActivity(): void {
  ++activitySequence
  activity.value = null
  revisions.value = []
  excerptSelection.value = { start: 0, end: 0, quote: '' }
}

function selectItem(item: StudyItem): void {
  itemId.value = item.id
  Object.assign(itemForm, { topic: item.topic, scheduled_on: item.scheduled_on, responsible: item.responsible, source_ids: [...item.source_doc_ids], agenda: item.agenda, outline: item.outline })
  recommendations.value = []
  recommendationMissing.value = []
  materialQuery.value = ''
  clearActivity()
}

function selectPlan(plan: StudyPlan): void {
  selected.value = plan
  Object.assign(planForm, { title: plan.title, priorities: plan.priorities.join('\n'), responsible: plan.responsible, source_ids: plan.source_doc_ids.join('\n') })
  if (plan.items.length) selectItem(plan.items[0]!)
  else { itemId.value = ''; clearActivity() }
  showNewItem.value = false
}

function replacePlan(plan: StudyPlan): void {
  const rememberedItem = itemId.value
  const index = plans.value.findIndex((row) => row.id === plan.id)
  if (index >= 0) plans.value[index] = plan
  else { plans.value.unshift(plan); total.value += 1 }
  selectPlan(plan)
  const item = plan.items.find((entry) => entry.id === rememberedItem)
  if (item) selectItem(item)
}

function setActivity(record: StudyActivity): void {
  activity.value = record
  Object.assign(activityForm, { held_on: record.held_on ?? '', host: record.host, participants: record.participants.map((person) => ({ ...person })), transcript: record.transcript, minutes: normalizeMinutes(record.minutes) })
  excerptSelection.value = { start: 0, end: 0, quote: '' }
  const entry = selected.value?.items.find((item) => item.id === record.context.item_id)
  if (entry) {
    entry.meeting_record_id = record.id
    entry.execution_status = record.archived_at ? 'archived' : record.review_status === 'approved' ? 'completed' : record.review_status === 'pending' ? 'pending' : record.held_on ? 'held' : 'planned'
  }
}

async function load(): Promise<void> {
  const sequence = ++loadSequence
  loading.value = true
  error.value = null
  selected.value = null
  clearActivity()
  try {
    const params = { year: filters.year, org_unit_id: filters.org || undefined, page: page.value, page_size: 20 }
    if (tab.value === 'plans') {
      const result = await studyApi.plans({ ...params, start: filters.start || undefined, end: filters.end || undefined })
      if (sequence !== loadSequence) return
      plans.value = result.items
      total.value = result.total
    } else if (tab.value === 'history') {
      archives.value = []
      const result = await studyApi.history({ ...params, topic: filters.topic || undefined })
      if (sequence !== loadSequence) return
      archives.value = result.items
      total.value = result.total
    } else {
      metrics.value = null
      const result = await studyApi.metrics(params)
      if (sequence !== loadSequence) return
      metrics.value = result
    }
  } catch (caught) { if (sequence === loadSequence) error.value = caught }
  finally { if (sequence === loadSequence) loading.value = false }
}

function changeTab(next: typeof tab.value): void { tab.value = next; page.value = 1; void load() }
function turnPage(delta: number): void { page.value += delta; void load() }

onMounted(() => {
  void run(async () => {
    const [orgs, currentPolicy] = await Promise.all([studyApi.organizations(), studyApi.policy()])
    organizations.value = orgs.items
    policy.value = currentPolicy
    policyEnabled.value = currentPolicy.enabled
    createForm.org_unit_id = orgs.items.some((org) => org.id === session.state.user?.org_unit_id) ? session.state.user!.org_unit_id! : ''
    await load()
  })
})

function createPlan(): void {
  void run(async () => {
    const payload = revisionPayload(1)
    const plan = await studyApi.createPlan({ org_unit_id: createForm.org_unit_id, year: createForm.year, title: createForm.title, priorities: lines(createForm.priorities), responsible: createForm.responsible, source_doc_ids: lines(createForm.source_ids), reason: payload.reason })
    filters.year = createForm.year
    filters.org = createForm.org_unit_id
    filters.start = filters.end = ''
    tab.value = 'plans'
    page.value = 1
    await load()
    replacePlan(plan)
    showCreate.value = false
    success.value = '年度学习草案已保存，请核对每期安排与材料后送审。'
  })
}

function savePlan(): void {
  if (!selected.value) return
  const plan = selected.value
  void run(async () => {
    replacePlan(await studyApi.updatePlan(plan.id, { ...revisionPayload(plan.revision), title: planForm.title, priorities: lines(planForm.priorities), responsible: planForm.responsible, source_doc_ids: lines(planForm.source_ids) }))
    success.value = '年度重点已修订；原有审核失效，未召开安排的提纲需重新核对。'
  })
}

function saveItem(): void {
  if (!selected.value || !activeItem.value) return
  const plan = selected.value, item = activeItem.value
  void run(async () => {
    replacePlan(await studyApi.updateItem(plan.id, item.id, { ...revisionPayload(plan.revision), topic: itemForm.topic, scheduled_on: itemForm.scheduled_on, responsible: itemForm.responsible, source_doc_ids: [...itemForm.source_ids], agenda: itemForm.agenda, outline: itemForm.outline }))
    success.value = '每期安排与议程提纲已保存，请重新送审年度计划。'
  })
}

function addItem(): void {
  if (!selected.value) return
  const plan = selected.value
  void run(async () => {
    replacePlan(await studyApi.addItem(plan.id, { ...revisionPayload(plan.revision), topic: newItem.topic, scheduled_on: newItem.scheduled_on, responsible: newItem.responsible, source_doc_ids: lines(newItem.source_ids) }))
    showNewItem.value = false
    success.value = '学习安排已增加，年度计划需重新审核。'
  })
}

function recommend(): void {
  if (!selected.value || !activeItem.value) return
  const plan = selected.value, item = activeItem.value
  void run(async () => {
    const result = await studyApi.recommend(plan.id, item.id, materialQuery.value)
    recommendations.value = result.sources
    recommendationMissing.value = result.missing
  })
}

function toggleSource(source: StudySource): void {
  const index = itemForm.source_ids.indexOf(source.doc_id)
  if (index >= 0) itemForm.source_ids.splice(index, 1)
  else itemForm.source_ids.push(source.doc_id)
}

function useAnnualSource(source: StudySource): void {
  planForm.source_ids = [...new Set([...lines(planForm.source_ids), source.doc_id])].join('\n')
  success.value = '已加入年度依据选择，请保存年度重点以完成登记。'
}

function generateDrafts(): void {
  if (!selected.value || !activeItem.value) return
  const plan = selected.value, item = activeItem.value
  void run(async () => { replacePlan(await studyApi.drafts(plan.id, item.id, revisionPayload(plan.revision))); success.value = '议程和发言提纲草案已生成，政策摘录保留来源与版本。' })
}

function planAction(action: 'submit' | 'review', decision?: string): void {
  if (!selected.value) return
  const plan = selected.value
  void run(async () => { replacePlan(await studyApi.planAction(plan.id, action, { ...revisionPayload(plan.revision), decision })); success.value = action === 'submit' ? '已提交年度计划，等待另一位组织人员审核。' : '人工审核结果已保存。' })
}

function openActivity(id?: string): void {
  const plan = selected.value, item = activeItem.value
  void run(async () => {
    const sequence = ++activitySequence
    const record = id ? await studyApi.activity(id) : (plan && item ? await studyApi.start(plan.id, item.id, revisionPayload(plan.revision)) : null)
    if (record && sequence === activitySequence) {
      setActivity(record)
      if (item && !id) item.meeting_record_id = record.id
    }
  })
}

function activityPayload() {
  return { held_on: activityForm.held_on || null, host: activityForm.host, participants: activityForm.participants.map((person) => ({ ...person })), transcript: activityForm.transcript, minutes: normalizeMinutes(activityForm.minutes) }
}

function addParticipant(): void {
  activityForm.participants.push({ participant_id: crypto.randomUUID(), name: '', attended: true })
}

function saveActivity(): void {
  if (!activity.value) return
  const record = activity.value
  void run(async () => { setActivity(await studyApi.updateActivity(record.id, { ...revisionPayload(record.revision), ...activityPayload() })); success.value = '参学与原始文本已保存，纪要须重新审核。' })
}

function activityAction(action: 'generate-minutes' | 'submit' | 'review' | 'archive', decision?: string): void {
  if (!activity.value) return
  const record = activity.value
  void run(async () => {
    setActivity(await studyApi.activityAction(record.id, action, { ...revisionPayload(record.revision), decision }))
    success.value = action === 'archive' ? '已保存审核版本及电子效力确认证据。' : '纪要状态已更新；原文与人工意见可在修订记录中核查。'
  })
}

function captureSelection(): void {
  const element = transcriptEl.value
  if (!element) return
  excerptSelection.value = { start: element.selectionStart, end: element.selectionEnd, quote: activityForm.transcript.slice(element.selectionStart, element.selectionEnd) }
}

function addEvidence(key: MinuteKey): void {
  const selectedQuote = excerptSelection.value
  if (!selectedQuote.quote.trim()) return
  activityForm.minutes[key].push({ ...selectedQuote, text: selectedQuote.quote })
}

function locate(note: EvidenceNote): void {
  transcriptEl.value?.focus()
  transcriptEl.value?.setSelectionRange(note.start, note.end)
  excerptSelection.value = { start: note.start, end: note.end, quote: note.quote }
}

function showRevisions(kind: 'plans' | 'activities', id: string): void {
  void run(async () => { revisions.value = (await studyApi.revisions(kind, id)).items; revisionKind.value = kind })
}

function confirmPolicy(): void {
  void run(async () => {
    if (!policyEvidence.value.trim()) throw new Error('请填写学校组织部门确认电子记录效力的依据，或撤销理由。')
    policy.value = await studyApi.confirmPolicy({ enabled: policyEnabled.value, expected_revision: policy.value.revision, evidence: policyEvidence.value.trim() })
    success.value = policy.value.enabled ? '已保存学校电子记录效力确认。' : '已撤销归档确认，历史归档查询和导出将停止。'
  })
}

function exportActivity(record: StudyActivity): void {
  void run(async () => {
    const data = await studyApi.export(record.id)
    const body = [data.notice, data.record.title, `学习日期：${data.record.held_on ?? '待补'}`, `主持人：${data.record.host}`, `审核人：${data.record.reviewed_by}；审核时间：${data.record.reviewed_at}`, `审核意见：${data.record.review_comment}`, `电子归档确认：${data.archive_confirmation.evidence}`, `确认人：${data.archive_confirmation.confirmed_by}；确认版本：${data.archive_confirmation.revision}`, '', '年度计划与来源', `${data.plan_version.year} ${data.plan_version.title}`, data.plan_version.priorities.join('\n'), '', '参学记录', ...data.record.participants.map((person) => `${person.name}：${person.attended ? '参学' : '缺席'}（${person.participant_id}）`), '', '原始文本', data.record.transcript, '', ...Object.entries(minuteLabels).flatMap(([key, label]) => [label, ...(data.record.minutes[key as MinuteKey] ?? []).map((note) => `${note.text}\n原文位置 ${note.start}—${note.end}：${note.quote}`)]), '', '学习材料摘录与来源（原文件请从知识库核查）', ...data.record.sources.map((source) => `${source.title}\n文件 ${source.doc_id}；版本 ${source.content_revision}；生效 ${source.effective_date}；适用范围 ${source.visibility}\n${source.excerpt}`), '', '修订与审核证据', ...data.revisions.map((version) => `版本 ${version.revision}；${version.action}；操作人 ${version.actor_id}；${version.created_at}\n${version.reason}`), '', `活动编号：${record.id}；导出时间：${data.exported_at}`].join('\n')
    const blob = new Blob(['\uFEFF', body], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `中心组学习-${record.scheduled_on}-${record.id}.txt`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    success.value = '学习资料和审核记录已导出，来源与版本信息随材料保留。'
  })
}
</script>

<template>
  <div class="study-page">
    <PageHeader title="中心组学习" description="从年度重点到学习材料、人工审核纪要与历史归档。所有安排、议程和发言提纲供党委研究确定。">
      <template #actions><button v-if="canManage" class="btn btn--primary" :disabled="busy" @click="showCreate = !showCreate">新建年度计划</button></template>
    </PageHeader>
    <p v-if="success" class="notice" role="status">{{ success }}</p>
    <ErrorState v-if="error" :error="error"><button class="btn btn--ghost" :disabled="busy" @click="load">重新查询</button><p v-if="error instanceof Error">{{ error.message }}</p></ErrorState>
    <div class="filters">
      <label class="field">计划年度<input v-model.number="filters.year" type="number" min="2000" max="2100" /></label>
      <label class="field">党委范围<select v-model="filters.org" aria-label="党委范围"><option value="">全部授权党委</option><option v-for="org in organizations" :key="org.id" :value="org.id">{{ org.name }}</option></select></label>
      <template v-if="tab === 'plans'"><label class="field">安排起始日期<input v-model="filters.start" type="date" /></label><label class="field">安排结束日期<input v-model="filters.end" type="date" /></label></template>
      <label v-if="tab === 'history'" class="field">历史主题<input v-model="filters.topic" maxlength="300" /></label>
      <button class="btn btn--ghost" :disabled="busy || loading" @click="page = 1; load()">查询</button>
    </div>
    <nav class="tabs" aria-label="学习工作台">
      <button v-for="entry in [{ id: 'plans', label: '年度计划与每期学习' }, { id: 'history', label: '历史归档' }, { id: 'metrics', label: '考核复用' }] as const" :key="entry.id" :aria-current="tab === entry.id ? 'page' : undefined" :disabled="busy" @click="changeTab(entry.id)">{{ entry.label }}</button>
    </nav>
    <label v-if="canManage" class="field reason">操作依据 / 修订理由 / 审核意见<input v-model="reason" maxlength="2000" placeholder="所有保存、送审、审核和归档操作都会保留此依据" /></label>

    <form v-if="showCreate && canManage" class="u-card panel" @submit.prevent="createPlan">
      <h2 class="u-title-section">新建年度学习草案</h2>
      <div class="form-grid">
        <label class="field">所属党委<select v-model="createForm.org_unit_id" required aria-label="所属党委"><option value="" disabled>请选择有效党委</option><option v-for="org in organizations" :key="org.id" :value="org.id">{{ org.name }}</option></select></label>
        <label class="field">新计划年度<input v-model.number="createForm.year" required type="number" min="2000" max="2100" /></label>
        <label class="field">计划名称<input v-model="createForm.title" required maxlength="300" /></label>
        <label class="field">计划负责人<input v-model="createForm.responsible" required maxlength="100" /></label>
      </div>
      <label class="field">年度重点（每行一项）<textarea v-model="createForm.priorities" required rows="4" /></label>
      <label class="field">年度依据文件编号（每行一项，可在材料推荐后补齐）<textarea v-model="createForm.source_ids" rows="2" /></label>
      <p class="u-meta">先按年度重点形成学习安排草案，日期可逐项修订。资料不足时保留待补状态。</p>
      <button class="btn btn--primary" :disabled="busy || !reason.trim() || !organizations.length">保存年度草案</button>
    </form>

    <p v-if="loading" role="status">正在查询学习记录…</p>
    <template v-else-if="tab === 'plans'">
      <EmptyState v-if="!plans.length" title="暂无年度学习计划" description="请选择年度和党委范围，或登记新的年度重点。" />
      <div v-else class="plan-list">
        <button v-for="plan in plans" :key="plan.id" class="u-card plan-row" :aria-pressed="selected?.id === plan.id" :disabled="busy" @click="selectPlan(plan)"><span><strong>{{ plan.title }}</strong><small>{{ plan.year }} · {{ organizationName(plan.org_unit_id) }} · {{ plan.items.length }} 项安排</small></span><span class="badge">{{ REVIEW_LABELS[plan.review_status] }} · 版本 {{ plan.revision }}</span></button>
      </div>
      <section v-if="selected" class="u-card panel" aria-label="年度计划详情">
        <div class="section-heading"><h2 class="u-title-section">年度重点与审核</h2><span class="badge">{{ REVIEW_LABELS[selected.review_status] }}</span></div>
        <ul v-if="selected.missing.length" class="missing"><li v-for="warning in selected.missing" :key="warning">{{ warning }}</li></ul>
        <p v-if="selected.review_comment" class="notice">人工意见：{{ selected.review_comment }}；审核人：{{ selected.reviewed_by }}；{{ displayTime(selected.reviewed_at) }}（北京时间）</p>
        <div class="form-grid">
          <label class="field">年度计划名称<input v-model="planForm.title" maxlength="300" :disabled="busy || !canManage || selected.restricted" /></label>
          <label class="field">年度负责人<input v-model="planForm.responsible" maxlength="100" :disabled="busy || !canManage || selected.restricted" /></label>
        </div>
        <label class="field">年度学习重点<textarea v-model="planForm.priorities" rows="3" :disabled="busy || !canManage || selected.restricted" /></label>
        <label class="field">年度依据文件编号<textarea v-model="planForm.source_ids" rows="2" :disabled="busy || !canManage || selected.restricted" /></label>
        <div class="actions">
          <button v-if="canManage" class="btn btn--ghost" :disabled="busy || selected.restricted" @click="savePlan">保存年度重点</button>
          <button v-if="canManage && ['draft', 'rejected'].includes(selected.review_status)" class="btn btn--primary" :disabled="busy || selected.restricted || planDirty || itemDirty" @click="planAction('submit')">提交计划审核</button>
          <template v-if="canReview && selected.review_status === 'pending'"><button class="btn btn--primary" :disabled="busy || selected.submitted_by === session.state.user?.id" @click="planAction('review', 'approved')">通过计划审核</button><button class="btn btn--danger" :disabled="busy || selected.submitted_by === session.state.user?.id" @click="planAction('review', 'rejected')">退回计划</button></template>
          <button class="btn btn--quiet" :disabled="busy" @click="showRevisions('plans', selected.id)">查看计划修订记录</button>
        </div>
        <h3 class="u-title-sub">每期学习安排</h3>
        <p v-if="planDirty || itemDirty" class="missing">年度重点或本期安排有未保存的修改，请保存后再送审。</p>
        <div class="item-list"><button v-for="item in selected.items" :key="item.id" class="item-button" :aria-pressed="itemId === item.id" :disabled="busy" @click="selectItem(item)"><strong>{{ item.topic }}</strong><span>{{ item.scheduled_on }} · {{ item.responsible }} · {{ EXECUTION_LABELS[item.execution_status] ?? item.execution_status }}</span></button></div>
        <button v-if="canManage" class="btn btn--quiet" :disabled="busy || selected.restricted" @click="showNewItem = !showNewItem">增加学习安排</button>
        <form v-if="showNewItem" class="panel inset" @submit.prevent="addItem"><label class="field">新增主题<input v-model="newItem.topic" required maxlength="300" /></label><label class="field">新增安排日期<input v-model="newItem.scheduled_on" required type="date" /></label><label class="field">新增负责人<input v-model="newItem.responsible" required maxlength="100" /></label><label class="field">新增依据编号（每行一项）<textarea v-model="newItem.source_ids" rows="2" /></label><button class="btn btn--primary" :disabled="busy">保存新安排</button></form>
      </section>

      <section v-if="selected && activeItem" class="u-card panel" aria-label="每期主题与材料">
        <h2 class="u-title-section">主题材料、议程与发言提纲</h2>
        <p class="u-meta">{{ selected.notice }}。已登记活动的主题、日期和负责人保留原记录，后续安排请另行新增。</p>
        <ul class="missing"><li v-for="warning in activeItem.missing" :key="warning">{{ warning }}</li></ul>
        <div class="form-grid"><label class="field">学习主题<input v-model="itemForm.topic" :disabled="busy || !canManage || !!activeItem.meeting_record_id || selected.restricted" maxlength="300" /></label><label class="field">学习安排日期<input v-model="itemForm.scheduled_on" type="date" :disabled="busy || !canManage || !!activeItem.meeting_record_id || selected.restricted" /></label><label class="field">本期负责人<input v-model="itemForm.responsible" :disabled="busy || !canManage || !!activeItem.meeting_record_id || selected.restricted" maxlength="100" /></label></div>
        <div class="filters"><label class="field grow">资料检索词（留空使用年度重点及本期主题）<input v-model="materialQuery" maxlength="300" /></label><button class="btn btn--ghost" :disabled="busy || selected.restricted" @click="recommend">推荐学习材料</button></div>
        <ul v-if="recommendationMissing.length" class="missing"><li v-for="warning in recommendationMissing" :key="warning">{{ warning }}</li></ul>
        <p v-if="!recommendations.length && activeItem.sources.length" class="u-meta">已登记材料：{{ activeItem.sources.map((source) => source.title).join('；') }}</p>
        <article v-for="source in recommendations.length ? recommendations : activeItem.sources" :key="source.doc_id" class="source-card">
          <label><input type="checkbox" :checked="itemForm.source_ids.includes(source.doc_id)" :disabled="busy || !canManage || selected.restricted" @change="toggleSource(source)" /> <strong>{{ source.title }}</strong></label>
          <p class="u-meta">{{ source.issuer }} · {{ source.doc_id }} · 文件版本 {{ source.content_revision }} · 生效 {{ source.effective_date }} · 失效 {{ source.expiration_date ?? '长期有效' }} · 适用 {{ sourceScope(source.visibility) }} / {{ sourceScope(source.level) }}</p>
          <p v-if="source.summary">{{ source.summary }}</p><blockquote>{{ source.excerpt || '原文摘录待补' }}</blockquote>
          <button v-if="canManage" class="btn btn--quiet" :disabled="busy" @click="useAnnualSource(source)">加入年度依据选择</button>
        </article>
        <p class="u-meta">选中的本期资料：{{ itemForm.source_ids.join('；') || '待补' }}</p>
        <div class="form-grid"><label class="field">学习议程（人工可编辑）<textarea v-model="itemForm.agenda" rows="10" :disabled="busy || !canManage || selected.restricted" /></label><label class="field">发言提纲（人工可编辑）<textarea v-model="itemForm.outline" rows="10" :disabled="busy || !canManage || selected.restricted" /></label></div>
        <p class="u-meta">模板版本：{{ activeItem.template_version ?? '尚未生成' }} · {{ selected.notice }}</p>
        <div class="actions"><button v-if="canManage" class="btn btn--ghost" :disabled="busy || selected.restricted" @click="saveItem">保存本期安排与提纲</button><button v-if="canManage" class="btn btn--ghost" :disabled="busy || !!activeItem.meeting_record_id || selected.restricted" @click="generateDrafts">从已保存材料生成议程提纲</button><button v-if="activeItem.meeting_record_id" class="btn btn--primary" :disabled="busy" @click="openActivity(activeItem.meeting_record_id)">查看学习活动与纪要</button><button v-else-if="canManage" class="btn btn--primary" :disabled="busy || selected.review_status !== 'approved' || selected.restricted" @click="openActivity()">登记学习活动</button></div>
      </section>
    </template>

    <section v-else-if="tab === 'history'" class="u-card panel">
      <h2 class="u-title-section">审核后历史归档</h2>
      <p v-if="!policy.enabled" class="missing">学校组织部门尚未确认电子记录效力，历史归档查询与导出暂不可用。</p>
      <EmptyState v-else-if="!archives.length && !error" title="暂无匹配归档" description="仅显示人工审核并经合规确认归档的学习记录。" />
      <article v-for="record in archives" :key="record.id" class="source-card"><strong>{{ record.title }}</strong><p>{{ record.scheduled_on }} · 实际学习 {{ record.held_on }} · {{ organizationName(record.org_unit_id) }}</p><p class="u-meta">审核人 {{ record.reviewed_by }} · 版本 {{ record.revision }}</p><div class="actions"><button class="btn btn--ghost" :disabled="busy" @click="openActivity(record.id)">查看归档详情</button><button class="btn btn--ghost" :disabled="busy || record.restricted" @click="exportActivity(record)">导出学习材料</button></div></article>
    </section>

    <section v-else-if="metrics" class="u-card panel">
      <h2 class="u-title-section">考核复用与佐证</h2>
      <p class="u-meta">{{ metrics.calculation_rule }}</p>
      <dl class="metric-grid"><div><dt>计划完成率</dt><dd>{{ percentage(metrics.plan_completion_rate.value) }}</dd><small>{{ metrics.plan_completion_rate.numerator }} / {{ metrics.plan_completion_rate.denominator }} 项</small></div><div><dt>已审核学习次数</dt><dd>{{ metrics.learning_count.value ?? '待补' }}</dd></div><div><dt>参学率</dt><dd>{{ percentage(metrics.attendance_rate.value) }}</dd><small>{{ metrics.attendance_rate.numerator }} / {{ metrics.attendance_rate.denominator }} 人次</small></div><div><dt>纪要完整度</dt><dd>{{ percentage(metrics.minutes_completeness.value) }}</dd></div></dl>
      <ul class="missing"><li v-for="warning in metrics.missing" :key="warning">{{ warning }}</li></ul>
      <article v-for="evidence in metrics.evidence" :key="evidence.activity_id" class="source-card"><button class="btn btn--quiet" :disabled="busy" @click="openActivity(evidence.activity_id)">查看 {{ evidence.held_on }} 学习佐证</button><p>记录 {{ evidence.activity_id }} · 版本 {{ evidence.revision }} · 审核人 {{ evidence.reviewed_by }}</p><p v-for="person in evidence.participants" :key="person.source_id">{{ person.name }} · {{ person.attended ? '参学' : '缺席' }} · 来源 {{ person.source_id }}</p></article>
    </section>
    <div v-if="!loading && tab !== 'metrics' && total > 20" class="actions pagination"><button class="btn btn--ghost" :disabled="busy || page === 1" @click="turnPage(-1)">上一页</button><span>共 {{ total }} 条 · 第 {{ page }} 页</span><button class="btn btn--ghost" :disabled="busy || page * 20 >= total" @click="turnPage(1)">下一页</button></div>

    <section v-if="activity" class="u-card panel" aria-label="学习活动与纪要">
      <div class="section-heading"><h2 class="u-title-section">{{ activity.title }} · 学习记录</h2><button class="btn btn--quiet" :disabled="busy" @click="clearActivity">关闭学习记录</button></div>
      <p><span class="badge">{{ REVIEW_LABELS[activity.review_status] }}</span> <span v-if="activity.archived_at" class="badge badge--ok">已归档</span> · 版本 {{ activity.revision }} · {{ activity.notice }}</p>
      <ul class="missing"><li v-for="warning in activity.missing" :key="warning">{{ warning }}</li></ul>
      <p v-if="activity.review_comment" class="notice">人工意见：{{ activity.review_comment }}；审核人 {{ activity.reviewed_by }}；{{ displayTime(activity.reviewed_at) }}（北京时间）</p>
      <div class="form-grid"><label class="field">实际学习日期<input v-model="activityForm.held_on" type="date" :disabled="busy || !canChangeActivity" /></label><label class="field">学习主持人<input v-model="activityForm.host" maxlength="100" :disabled="busy || !canChangeActivity" /></label></div>
      <h3 class="u-title-sub">参学与缺席</h3>
      <div v-for="(person, index) in activityForm.participants" :key="person.participant_id" class="participant-row"><label class="field">参学人员 {{ index + 1 }}<input v-model="person.name" maxlength="100" :disabled="busy || !canChangeActivity" /></label><label><input v-model="person.attended" type="checkbox" :disabled="busy || !canChangeActivity" /> 实际参学</label><button v-if="canChangeActivity" class="btn btn--quiet" :disabled="busy" @click="activityForm.participants.splice(index, 1)">移除此参学登记</button></div>
      <button v-if="canChangeActivity" class="btn btn--quiet" :disabled="busy" @click="addParticipant">增加参学人员</button>
      <label class="field">原始学习文本<textarea ref="transcriptEl" v-model="activityForm.transcript" rows="9" :disabled="busy || !canChangeActivity" @select="captureSelection" @mouseup="captureSelection" @keyup="captureSelection" @input="activityForm.minutes = normalizeMinutes({})" /></label>
      <p class="u-meta">自动整理只摘录“学习要点：”“讨论共识：”“工作要求：”标明的原文。其他文本可选中后人工定位，未明确内容保留待补。</p>
      <div v-if="canChangeActivity" class="actions"><button v-for="(label, key) in minuteLabels" :key="key" class="btn btn--quiet" :disabled="busy || !excerptSelection.quote.trim()" @click="addEvidence(key)">选中原文加入{{ label }}</button></div>
      <section v-for="(label, key) in minuteLabels" :key="key" class="minute-section"><h3 class="u-title-sub">{{ label }}</h3><p v-if="!activityForm.minutes[key].length" class="missing">{{ label }}待补</p><article v-for="(note, index) in activityForm.minutes[key]" :key="index" class="source-card"><label class="field">{{ label }}表述<textarea v-model="note.text" rows="2" :disabled="busy || !canChangeActivity" /></label><blockquote>{{ note.quote }}</blockquote><button class="btn btn--quiet" :disabled="busy" @click="locate(note)">定位原文 {{ note.start }}—{{ note.end }}</button><button v-if="canChangeActivity" class="btn btn--quiet" :disabled="busy" @click="activityForm.minutes[key].splice(index, 1)">移除此摘录</button></article></section>
      <div class="actions"><button v-if="canChangeActivity" class="btn btn--ghost" :disabled="busy" @click="saveActivity">保存学习记录与纪要</button><button v-if="canChangeActivity" class="btn btn--ghost" :disabled="busy || activityDirty" @click="activityAction('generate-minutes')">从已保存原文生成纪要</button><button v-if="canChangeActivity && ['draft', 'rejected'].includes(activity.review_status)" class="btn btn--primary" :disabled="busy || activityDirty" @click="activityAction('submit')">提交纪要审核</button><template v-if="canReview && activity.review_status === 'pending'"><button class="btn btn--primary" :disabled="busy || activityDirty || activity.submitted_by === session.state.user?.id" @click="activityAction('review', 'approved')">通过纪要审核</button><button class="btn btn--danger" :disabled="busy || activity.submitted_by === session.state.user?.id" @click="activityAction('review', 'rejected')">退回纪要</button></template><button v-if="canManage && activity.review_status === 'approved' && !activity.archived_at" class="btn btn--primary" :disabled="busy || activityDirty || !policy.enabled" @click="activityAction('archive')">归档已审核记录</button><button v-if="activity.archived_at" class="btn btn--ghost" :disabled="busy || activity.restricted || !policy.enabled" @click="exportActivity(activity)">导出学习材料</button><button class="btn btn--quiet" :disabled="busy" @click="showRevisions('activities', activity.id)">查看纪要修订记录</button></div>
      <p v-if="activityDirty" class="missing">当前修改尚未保存，请保存后再生成纪要、送审或归档。</p>
    </section>

    <section v-if="revisions.length" class="u-card panel"><h2 class="u-title-section">{{ revisionKind === 'plans' ? '计划' : '纪要' }}修订与审核记录</h2><article v-for="version in revisions" :key="version.revision" class="source-card"><strong>版本 {{ version.revision }}</strong><p>{{ version.created_at }} · 操作人 {{ version.actor_id }}</p><p>{{ version.reason }}</p><details v-if="version.snapshot"><summary>查看这一版本的内容</summary><p>{{ version.snapshot.title }} · {{ version.snapshot.review_status ? REVIEW_LABELS[version.snapshot.review_status] : '' }}</p><p v-if="version.snapshot.review_comment">人工意见：{{ version.snapshot.review_comment }}</p><p v-if="version.snapshot.priorities">{{ version.snapshot.priorities.join('；') }}</p><pre v-if="version.snapshot.transcript">{{ version.snapshot.transcript }}</pre><article v-for="item in version.snapshot.items ?? []" :key="item.id"><p>{{ item.scheduled_on }} · {{ item.topic }}</p><pre>{{ item.agenda }}{{ item.outline }}</pre></article></details></article></section>

    <details class="u-card panel"><summary>电子归档确认与状态</summary><p>{{ policy.enabled ? '学校已确认电子记录效力，授权人员可归档审核记录。' : '尚未确认电子记录效力，归档、历史查询与导出默认关闭。' }}</p><p v-if="policy.evidence">确认依据：{{ policy.evidence }}；确认人 {{ policy.confirmed_by }}；{{ policy.confirmed_at }}</p><form v-if="canConfirm" class="panel inset" @submit.prevent="confirmPolicy"><label><input v-model="policyEnabled" type="checkbox" :disabled="busy" /> 学校组织部门已确认电子记录效力</label><label class="field">学校效力确认依据 / 撤销理由<textarea v-model="policyEvidence" required rows="3" maxlength="2000" :disabled="busy" /></label><button class="btn btn--ghost" :disabled="busy">保存学校归档确认</button></form></details>
  </div>
</template>

<style scoped>
.study-page { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6); max-width: 1360px; width: 100%; margin: 0 auto; }
.panel { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5); min-width: 0; }
.filters, .actions, .section-heading, .participant-row { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }
.filters { align-items: flex-end; }
.section-heading { justify-content: space-between; }
.filters .field { min-width: 150px; }
.grow { flex: 1; }
.reason { max-width: 900px; }
.form-grid, .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.metric-grid > div { padding: var(--space-4); border: var(--border); border-radius: var(--radius-sm); }
.metric-grid dd { font-size: var(--text-2xl); font-weight: 600; margin-top: var(--space-2); }
.metric-grid small, .plan-row small { color: var(--ink-muted); }
.tabs { display: flex; flex-wrap: wrap; gap: var(--space-2); border-bottom: var(--border); }
.tabs button { padding: var(--space-3) var(--space-4); border-bottom: 2px solid transparent; }
.tabs button[aria-current="page"] { color: var(--accent-deep); border-bottom-color: var(--accent); }
.plan-list, .item-list { display: grid; gap: var(--space-3); }
.plan-row { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-3); text-align: left; padding: var(--space-4); }
.plan-row span:first-child { display: flex; flex-direction: column; gap: var(--space-2); }
.plan-row[aria-pressed="true"], .item-button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-wash); }
.item-button { display: flex; flex-wrap: wrap; gap: var(--space-3); justify-content: space-between; text-align: left; border: var(--border); padding: var(--space-3); border-radius: var(--radius-sm); }
.source-card { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-4); border: var(--border); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
.source-card blockquote { border-left: 2px solid var(--rule-strong); padding-left: var(--space-3); white-space: pre-wrap; color: var(--ink-soft); }
.minute-section { display: flex; flex-direction: column; gap: var(--space-3); }
.notice { padding: var(--space-3); background: var(--ok-wash); color: var(--ok-ink); border-radius: var(--radius-sm); }
.missing { color: var(--warn-ink); font-size: var(--text-sm); line-height: var(--leading-normal); }
.inset { padding: var(--space-4); background: var(--paper-dim); border: var(--border); border-radius: var(--radius-sm); }
.pagination { justify-content: center; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
input:not([type="checkbox"]), select, textarea { width: 100%; min-width: 0; padding: var(--space-2) var(--space-3); border: 1px solid var(--rule-strong); border-radius: var(--radius-sm); background: var(--paper-raised); }
textarea { resize: vertical; line-height: var(--leading-normal); }
details > summary { cursor: pointer; font-weight: 600; }
@media (max-width: 760px) { .study-page { padding: var(--space-4); } .panel { padding: var(--space-4); } .form-grid { grid-template-columns: 1fr; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .filters .field { flex: 1 1 150px; } }
</style>
