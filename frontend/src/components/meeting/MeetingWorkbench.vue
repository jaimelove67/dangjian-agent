<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { ApiError } from '@/api/http'
import {
  ACTIVITY_TYPE_LABELS,
  EXECUTION_LABELS,
  REVIEW_LABELS,
  meetingApi,
  minutesSectionsFor,
  type ActivityType,
  type MeetingFrequency,
  type MeetingRecord,
  type MeetingRevision,
  type MeetingStats,
  type MeetingTask,
  type Minutes,
  type Organization,
  type Participant,
} from '@/api/meeting'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import MeetingFrequencyPanel from './MeetingFrequencyPanel.vue'
import MemberReviewPanel from './MemberReviewPanel.vue'
import ParticipantEditor from './ParticipantEditor.vue'
import SourcePicker from './SourcePicker.vue'
import { session } from '@/stores/session'
import { downloadBlob, todayISO } from '@/utils/files'

const orgs = ref<Organization[]>([])
const records = ref<MeetingRecord[]>([])
const total = ref(0)
const current = ref<MeetingRecord | null>(null)
const stats = ref<MeetingStats | null>(null)
const frequency = ref<MeetingFrequency | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const statsLoading = ref(false)
const busy = ref(false)
const pageError = ref<unknown>(null)
const orgError = ref<unknown>(null)
const actionError = ref<unknown>(null)
const statsError = ref<unknown>(null)
const frequencyError = ref<unknown>(null)
const message = ref('')
const workspace = ref('records')
const detailTab = ref('details')
const filters = reactive({
  year: '',
  org_unit_id: '',
  activity_type: '',
  execution_status: '',
  task_status: '',
  page: 1,
})
const tasks = ref<(Partial<MeetingTask> & { id: string; restricted?: boolean })[]>([])
const revisions = ref<MeetingRevision[]>([])
const revisionsLoading = ref(false)
const revisionError = ref<unknown>(null)
const canManage = computed(() => session.can('meeting.manage'))
const canReview = computed(() => session.can('meeting.review'))
const canArchive = computed(() => session.can('meeting.archive'))
const canEdit = computed(
  () =>
    canManage.value && !!current.value && !current.value.archived_at && !current.value.restricted,
)
const isSelfReview = computed(() => current.value?.submitted_by === session.state.user?.id)
const workspaces = [
  { key: 'records', label: '活动工作台' },
  { key: 'tasks', label: '任务台账' },
  { key: 'history', label: '历史归档' },
  { key: 'stats', label: '年度统计' },
  { key: 'member-reviews', label: '民主评议党员' },
]
const detailTabs = [
  { key: 'details', label: '活动资料' },
  { key: 'minutes', label: '议程与纪要' },
  { key: 'tasks', label: '活动任务' },
  { key: 'history', label: '版本与归档' },
]
const taskLabels = { pending: '待人工确认', active: '落实中', done: '已完成', cancelled: '已取消' }
// 组织生活会的纪要栏目与三会一课不同：按当前活动类型选栏目，不把"批评意见"塞进"讨论共识"。
const minuteSections = computed(() => minutesSectionsFor(current.value?.activity_type))
const reviewYear = computed(() => Number(filters.year || new Date().getFullYear()))
const memberPanel = ref<InstanceType<typeof MemberReviewPanel> | null>(null)
const revisionLabels: Record<string, string> = {
  create: '登记',
  revise: '修订',
  generate_agenda: '生成议程',
  generate_minutes: '提取纪要',
  submit: '提交审核',
  review: '人工审核',
  archive: '归档',
}
const blankCreate = () => ({
  org_unit_id: '',
  activity_type: 'branch_member_meeting' as ActivityType,
  title: '',
  scheduled_on: todayISO(),
  host: '',
  participants: [] as Participant[],
  source_doc_ids: [] as string[],
  reason: '',
})
const form = reactive(blankCreate())
const createOpen = ref(false)
const edit = reactive({
  scheduled_on: '',
  held_on: '',
  host: '',
  participants: [] as Participant[],
  source_doc_ids: [] as string[],
  transcript: '',
  agenda: '',
  notice: '',
  minutes: {} as Minutes,
  reason: '',
})
const baseline = ref('')
const dirty = computed(() => !!current.value && JSON.stringify(editPayload()) !== baseline.value)
const validParticipants = (people: Participant[]) =>
  people.length <= 500 &&
  people.every((person) => person.name.trim() && person.participant_id.trim()) &&
  new Set(people.map((person) => person.participant_id.trim())).size === people.length
const actionOpen = ref(false)
type RecordAction = 'generate-agenda' | 'generate-minutes' | 'submit' | 'review' | 'archive'
const pendingAction = ref<RecordAction>('submit')
const actionInput = reactive({
  reason: '',
  decision: 'approved' as 'approved' | 'rejected',
  confirmed: false,
})
const actionTitles: Record<RecordAction, string> = {
  'generate-agenda': '生成议程与通知草稿',
  'generate-minutes': '从原文提取纪要',
  submit: '提交当前纪要审核',
  review: '登记人工纪要审核',
  archive: '归档当前纪要',
}
const taskDialog = ref<'create' | 'confirm' | 'handle' | ''>('')
const taskEditing = ref<MeetingTask | null>(null)
const taskForm = reactive({
  task_text: '',
  owner_name: '',
  due_on: '',
  source_start: 0,
  source_end: 0,
  status: 'done' as 'done' | 'cancelled',
  handle_note: '',
  reason: '',
})
const discardOpen = ref(false)
const pendingRecord = ref('')
let listSequence = 0
let detailSequence = 0
let statsSequence = 0
let frequencySequence = 0
let historySequence = 0
let alive = true

function editPayload() {
  return {
    scheduled_on: edit.scheduled_on,
    held_on: edit.held_on || null,
    host: edit.host.trim(),
    participants: edit.participants,
    source_doc_ids: edit.source_doc_ids,
    transcript: edit.transcript,
    agenda: edit.agenda,
    notice: edit.notice,
    minutes: edit.minutes,
  }
}
function receive(record: MeetingRecord): void {
  current.value = record
  Object.assign(edit, {
    scheduled_on: record.scheduled_on,
    held_on: record.held_on || '',
    host: record.host,
    participants: JSON.parse(JSON.stringify(record.participants)),
    source_doc_ids: [...record.source_doc_ids],
    transcript: record.transcript,
    agenda: record.context?.agenda || '',
    notice: record.context?.notice || '',
    minutes: JSON.parse(JSON.stringify(record.minutes)),
    reason: '',
  })
  baseline.value = JSON.stringify(editPayload())
}

async function loadOrgs(): Promise<void> {
  try {
    orgs.value = (await meetingApi.organizations()).items
  } catch (err) {
    orgError.value = err
  }
}
async function loadRecords(): Promise<void> {
  if (workspace.value === 'member-reviews') {
    // 民主评议党员有自己的年度/组织筛选与分页口径，不借用活动列表的接口
    records.value = []
    tasks.value = []
    total.value = 0
    pageError.value = null
    loading.value = false
    return
  }
  const sequence = ++listSequence
  loading.value = true
  pageError.value = null
  try {
    const params = {
      page: filters.page,
      page_size: 20,
      year: filters.year ? Number(filters.year) : undefined,
      org_unit_id: filters.org_unit_id || undefined,
    }
    if (workspace.value === 'tasks') {
      const result = await meetingApi.tasks({ ...params, status: filters.task_status || undefined })
      if (sequence !== listSequence || !alive) return
      tasks.value = result.items
      total.value = result.total
    } else {
      const result =
        workspace.value === 'history'
          ? await meetingApi.history(params)
          : await meetingApi.records({
              ...params,
              activity_type: filters.activity_type || undefined,
              execution_status: filters.execution_status || undefined,
            })
      if (sequence !== listSequence || !alive) return
      records.value = result.items
      total.value = result.total
    }
  } catch (err) {
    if (sequence === listSequence && alive) pageError.value = err
  } finally {
    if (sequence === listSequence && alive) loading.value = false
  }
}
async function loadStats(): Promise<void> {
  const sequence = ++statsSequence
  statsLoading.value = true
  statsError.value = null
  try {
    const result = await meetingApi.stats({
      year: Number(filters.year || new Date().getFullYear()),
      org_unit_id: filters.org_unit_id || undefined,
    })
    if (sequence === statsSequence && alive) stats.value = result
  } catch (err) {
    if (sequence === statsSequence && alive) statsError.value = err
  } finally {
    if (sequence === statsSequence && alive) statsLoading.value = false
  }
}
async function loadFrequency(): Promise<void> {
  // 频次按支部的当前周期计算，与年度统计同一个筛选，但不受「年度」输入影响
  const sequence = ++frequencySequence
  frequencyError.value = null
  // 三会一课是支部制度：选了院系/学校节点时按该范围内全部支部给结论，
  // 而不是拿非支部组织去问后端换回一个 422
  const chosen = orgs.value.find((org) => org.id === filters.org_unit_id)
  const orgUnitId =
    chosen && chosen.org_type !== 'branch' ? undefined : filters.org_unit_id || undefined
  try {
    const result = await meetingApi.frequency({ org_unit_id: orgUnitId })
    if (sequence === frequencySequence && alive) frequency.value = result
  } catch (err) {
    if (sequence === frequencySequence && alive) frequencyError.value = err
  }
}
function reload(): void {
  filters.page = 1
  void loadRecords()
  if (workspace.value === 'stats') {
    void loadStats()
    void loadFrequency()
  }
  if (workspace.value === 'member-reviews') {
    void memberPanel.value?.reload()
  }
}
function changeWorkspace(value: string): void {
  workspace.value = value
  reload()
}
function changePage(delta: number): void {
  filters.page += delta
  void loadRecords()
}
async function openRecord(id: string, force = false): Promise<void> {
  if (dirty.value && !force) {
    pendingRecord.value = id
    discardOpen.value = true
    return
  }
  const sequence = ++detailSequence
  current.value = null
  revisions.value = []
  actionError.value = null
  message.value = ''
  detailLoading.value = true
  try {
    const record = await meetingApi.record(id)
    if (sequence === detailSequence && alive) {
      receive(record)
      detailTab.value = 'details'
    }
  } catch (err) {
    if (sequence === detailSequence && alive) actionError.value = err
  } finally {
    if (sequence === detailSequence && alive) detailLoading.value = false
  }
}
async function perform(fn: () => Promise<void>): Promise<boolean> {
  if (busy.value) return false
  busy.value = true
  actionError.value = null
  message.value = ''
  try {
    await fn()
    return true
  } catch (err) {
    actionError.value = err
    return false
  } finally {
    busy.value = false
  }
}
function startCreate(): void {
  if (dirty.value) return
  form.org_unit_id = orgs.value[0]?.id ?? ''
  actionError.value = null
  createOpen.value = true
}
async function create(): Promise<void> {
  if (!validParticipants(form.participants)) {
    actionError.value = new ApiError('请补齐参会人员的姓名及唯一编号。', 42201)
    return
  }
  await perform(async () => {
    const record = await meetingApi.create({
      ...form,
      title: form.title.trim(),
      host: form.host.trim(),
      reason: form.reason.trim(),
    })
    createOpen.value = false
    Object.assign(form, blankCreate())
    receive(record)
    detailTab.value = 'details'
    workspace.value = 'records'
    await loadRecords()
    message.value = '活动计划已登记。召开后补齐实际日期、参会情况和会议原文。'
  })
}
async function saveRecord(): Promise<boolean> {
  if (
    !current.value ||
    !canEdit.value ||
    !edit.reason.trim() ||
    !validParticipants(edit.participants)
  )
    return false
  const id = current.value.id
  const payload: Partial<ReturnType<typeof editPayload>> = editPayload()
  if (edit.transcript !== current.value.transcript) delete payload.minutes
  return perform(async () => {
    const record = await meetingApi.update(id, {
      ...payload,
      expected_revision: current.value!.revision,
      reason: edit.reason.trim(),
    })
    receive(record)
    await loadRecords()
    message.value = '活动资料已保存。修改原文后的纪要需重新提取并审核。'
  })
}
function startAction(action: RecordAction, decision: 'approved' | 'rejected' = 'approved'): void {
  if (!current.value) return
  if (dirty.value) {
    actionError.value = new ApiError('请先保存活动资料，再处理当前版本。', 40901)
    return
  }
  actionError.value = null
  pendingAction.value = action
  Object.assign(actionInput, { reason: '', decision, confirmed: false })
  actionOpen.value = true
}
async function runAction(): Promise<void> {
  if (!current.value || !actionInput.reason.trim() || !actionInput.confirmed) return
  await perform(async () => {
    const record = await meetingApi.action(current.value!.id, pendingAction.value, {
      expected_revision: current.value!.revision,
      reason: actionInput.reason.trim(),
      ...(pendingAction.value === 'review' ? { decision: actionInput.decision } : {}),
    })
    actionOpen.value = false
    receive(record)
    await loadRecords()
    void loadStats()
    message.value = `${actionTitles[pendingAction.value]}已完成，当前版本为 ${record.revision}。`
  })
}
async function loadRevisions(): Promise<void> {
  if (!current.value) return
  const sequence = ++historySequence
  const id = current.value.id
  revisionsLoading.value = true
  revisionError.value = null
  try {
    const response = await meetingApi.revisions(id)
    if (sequence === historySequence && current.value?.id === id && alive)
      revisions.value = response.items
  } catch (err) {
    if (sequence === historySequence && alive) revisionError.value = err
  } finally {
    if (sequence === historySequence && alive) revisionsLoading.value = false
  }
}
function changeDetail(value: string): void {
  detailTab.value = value
  if (value === 'history') void loadRevisions()
}
function revisionContent(snapshot: Record<string, unknown>): string {
  const value = (key: string) =>
    typeof snapshot[key] === 'string' ? (snapshot[key] as string) : '未记录'
  return [
    `主题：${value('title')}`,
    `计划日期：${value('scheduled_on')}`,
    `实际日期：${value('held_on')}`,
    `主持人：${value('host')}`,
    '',
    '会议原文：',
    value('transcript'),
  ].join('\n')
}
async function exportArchive(): Promise<void> {
  if (!current.value?.archived_at) return
  await perform(async () => {
    const result = await meetingApi.export(current.value!.id)
    downloadBlob(
      new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }),
      `${current.value!.title}-归档.json`,
    )
    message.value = '归档记录、来源与审核版本已导出。'
  })
}

function startTask(task: MeetingTask, action: 'confirm' | 'handle'): void {
  taskEditing.value = task
  Object.assign(taskForm, {
    owner_name: task.owner_name,
    due_on: task.due_on || '',
    handle_note: '',
    status: 'done',
    reason: '',
  })
  actionError.value = null
  taskDialog.value = action
}
function startCreateTask(): void {
  if (dirty.value) {
    actionError.value = new ApiError('请先保存会议原文，再从已保存文本摘取任务。', 40901)
    return
  }
  Object.assign(taskForm, {
    task_text: '',
    owner_name: '',
    due_on: '',
    source_start: 0,
    source_end: 0,
    reason: '',
  })
  taskDialog.value = 'create'
  actionError.value = null
}
function selectExcerpt(event: Event): void {
  const element = event.target as HTMLTextAreaElement
  taskForm.task_text = element.value.slice(element.selectionStart, element.selectionEnd)
  taskForm.source_start = Array.from(element.value.slice(0, element.selectionStart)).length
  taskForm.source_end = Array.from(element.value.slice(0, element.selectionEnd)).length
}
function useRequirement(): void {
  const text = current.value?.transcript ?? ''
  const match = text.split('\n').find((line) => line.includes('工作要求'))
  if (!match) {
    actionError.value = new ApiError('原文没有标注工作要求，请在原文中选中任务摘录。', 42201)
    return
  }
  const start = text.indexOf(match)
  taskForm.task_text = match
  taskForm.source_start = Array.from(text.slice(0, start)).length
  taskForm.source_end = taskForm.source_start + Array.from(match).length
}
async function saveTask(): Promise<void> {
  await perform(async () => {
    if (taskDialog.value === 'create') {
      await meetingApi.createTask(current.value!.id, {
        task_text: taskForm.task_text,
        source_start: taskForm.source_start,
        source_end: taskForm.source_end,
        owner_name: taskForm.owner_name.trim(),
        due_on: taskForm.due_on || null,
        reason: taskForm.reason.trim(),
      })
    } else if (taskDialog.value === 'confirm') {
      await meetingApi.confirmTask(taskEditing.value!.id, {
        owner_name: taskForm.owner_name.trim(),
        due_on: taskForm.due_on || null,
        reason: taskForm.reason.trim(),
      })
    } else {
      await meetingApi.handleTask(taskEditing.value!.id, {
        status: taskForm.status,
        handle_note: taskForm.handle_note.trim(),
        reason: taskForm.reason.trim(),
      })
    }
    taskDialog.value = ''
    if (current.value && !dirty.value) receive(await meetingApi.record(current.value.id))
    await loadRecords()
    message.value = '任务记录已保存。'
  })
}
async function discard(): Promise<void> {
  discardOpen.value = false
  if (pendingRecord.value) await openRecord(pendingRecord.value, true)
  else current.value = null
}
async function saveAndOpen(): Promise<void> {
  if (await saveRecord()) await discard()
}
function closeDetail(): void {
  if (dirty.value) {
    pendingRecord.value = ''
    discardOpen.value = true
  } else current.value = null
}
onMounted(() => {
  void loadOrgs()
  void loadRecords()
})
onBeforeUnmount(() => {
  alive = false
  listSequence += 1
  detailSequence += 1
  statsSequence += 1
  frequencySequence += 1
  historySequence += 1
})
</script>

<template>
  <div class="meeting wb-stack">
    <PageHeader
      title="组织生活"
      description="三会一课与组织生活会从活动安排到参会、纪要、任务和归档；民主评议党员按年度记录程序与等次。生成内容保留原文依据，组织结论由人工形成。"
    >
      <template #actions
        ><button
          v-if="canManage"
          class="btn btn--primary"
          type="button"
          :disabled="busy || dirty"
          @click="startCreate"
        >
          登记活动计划</button
        ><button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="reload">
          刷新
        </button></template
      >
    </PageHeader>
    <WorkspaceTabs
      :model-value="workspace"
      :items="workspaces"
      label="组织生活工作区"
      :disabled="busy"
      @update:model-value="changeWorkspace"
    >
      <form class="wb-actions" @submit.prevent="reload">
        <label class="wb-field"
          ><span>年度</span
          ><input
            v-model="filters.year"
            class="input"
            type="number"
            min="2000"
            max="2100"
            :placeholder="
              workspace === 'stats' || workspace === 'member-reviews'
                ? String(new Date().getFullYear())
                : '全部年度'
            "
        /></label>
        <label class="wb-field"
          ><span>所属组织</span
          ><select v-model="filters.org_unit_id" class="select">
            <option value="">全部可访问组织</option>
            <option v-for="org in orgs" :key="org.id" :value="org.id">{{ org.name }}</option>
          </select></label
        >
        <label v-if="workspace === 'records'" class="wb-field"
          ><span>活动类型</span
          ><select v-model="filters.activity_type" class="select">
            <option value="">全部类型</option>
            <option v-for="(label, key) in ACTIVITY_TYPE_LABELS" :key="key" :value="key">
              {{ label }}
            </option>
          </select></label
        >
        <label v-if="workspace === 'records'" class="wb-field"
          ><span>办理状态</span
          ><select v-model="filters.execution_status" class="select">
            <option value="">全部状态</option>
            <option v-for="(label, key) in EXECUTION_LABELS" :key="key" :value="key">
              {{ label }}
            </option>
          </select></label
        >
        <label v-if="workspace === 'tasks'" class="wb-field"
          ><span>任务状态</span
          ><select v-model="filters.task_status" class="select">
            <option value="">全部状态</option>
            <option v-for="(label, key) in taskLabels" :key="key" :value="key">{{ label }}</option>
          </select></label
        >
        <button class="btn btn--ghost" type="submit" :disabled="loading || busy">查询</button>
      </form>
      <p v-if="message" class="wb-success" role="status">{{ message }}</p>
      <ErrorState v-if="pageError" :error="pageError"
        ><button class="btn btn--ghost" type="button" @click="loadRecords">
          重新加载
        </button></ErrorState
      >
      <ErrorState v-if="orgError" :error="orgError" />
      <template v-if="workspace === 'member-reviews'">
        <MemberReviewPanel
          ref="memberPanel"
          :year="reviewYear"
          :org-unit-id="filters.org_unit_id"
          :orgs="orgs"
          :can-manage="canManage"
        />
      </template>
      <template v-else-if="workspace === 'stats'">
        <LoadingBlock v-if="statsLoading" variant="table" :rows="3" /><ErrorState
          v-else-if="statsError"
          :error="statsError"
        />
        <section v-else-if="stats" class="wb-section wb-stack">
          <h2>{{ stats.year }}年度组织生活统计</h2>
          <p class="wb-note">{{ stats.calculation_rule }}</p>
          <dl class="wb-facts">
            <div>
              <dt>实际召开活动</dt>
              <dd>{{ stats.counts.total }}</dd>
            </div>
            <div>
              <dt>参会率</dt>
              <dd>
                {{
                  stats.attendance_rate.value === null
                    ? '缺少统计依据'
                    : `${(stats.attendance_rate.value * 100).toFixed(1)}%`
                }}
              </dd>
              <span class="u-meta"
                >{{ stats.attendance_rate.numerator }} /
                {{ stats.attendance_rate.denominator }}</span
              >
            </div>
            <div>
              <dt>纪要完整率</dt>
              <dd>
                {{
                  stats.minutes_completeness.value === null
                    ? '缺少统计依据'
                    : `${(stats.minutes_completeness.value * 100).toFixed(1)}%`
                }}
              </dd>
              <span class="u-meta"
                >{{ stats.minutes_completeness.numerator }} /
                {{ stats.minutes_completeness.denominator }}</span
              >
            </div>
          </dl>
          <div class="wb-table-wrap">
            <table class="wb-table">
              <thead>
                <tr>
                  <th>活动类型</th>
                  <th>周期要求</th>
                  <th>年度要求</th>
                  <th>已审核次数</th>
                  <th>实际登记</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, key) in stats.by_type" :key="key">
                  <td>{{ item.label }}</td>
                  <td>{{ item.period_text }}</td>
                  <td>{{ item.required }}</td>
                  <td>{{ item.performed }}</td>
                  <td>{{ item.total_registered }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-for="item in stats.missing" :key="item" class="field__error">{{ item }}</p>
          <details class="wb-disclosure">
            <summary>查看统计证据（{{ stats.evidence.length }}）</summary>
            <article v-for="item in stats.evidence" :key="item.activity_id" class="wb-log">
              <p>
                {{ ACTIVITY_TYPE_LABELS[item.activity_type as ActivityType] }} /
                {{ item.held_on }} / 版本 {{ item.revision }}
              </p>
              <p>
                {{ item.participants.filter((person) => person.attended).length }} 人参会，共登记
                {{ item.participants.length }} 人
              </p>
              <button
                class="btn btn--quiet btn--sm"
                type="button"
                @click="openRecord(item.activity_id)"
              >
                查看依据活动
              </button>
            </article>
          </details>
        </section>
        <ErrorState v-if="frequencyError" :error="frequencyError" />
        <MeetingFrequencyPanel v-else :frequency="frequency" />
      </template>
      <template v-else>
        <LoadingBlock v-if="loading" variant="table" :rows="4" />
        <div v-else-if="workspace === 'tasks' && tasks.length" class="wb-table-wrap meeting__list">
          <table class="wb-table">
            <thead>
              <tr>
                <th>任务原文</th>
                <th>责任人</th>
                <th>期限</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in tasks" :key="task.id">
                <td v-if="task.restricted" colspan="5">
                  关联资料权限变更，此任务的正文暂不可查看。
                </td>
                <template v-else
                  ><td>{{ task.task_text }}</td>
                  <td>{{ task.owner_name || '待补齐' }}</td>
                  <td>{{ task.due_on || '待补齐' }}</td>
                  <td>{{ task.status ? taskLabels[task.status] : '待核验' }}</td>
                  <td>
                    <button
                      class="btn btn--quiet btn--sm"
                      type="button"
                      :disabled="busy"
                      @click="openRecord(task.record_id!)"
                    >
                      查看活动</button
                    ><button
                      v-if="canManage && task.status === 'pending'"
                      class="btn btn--ghost btn--sm"
                      type="button"
                      :disabled="busy"
                      @click="startTask(task as MeetingTask, 'confirm')"
                    >
                      确认责任与期限</button
                    ><button
                      v-if="canManage && task.status === 'active'"
                      class="btn btn--ghost btn--sm"
                      type="button"
                      :disabled="busy"
                      @click="startTask(task as MeetingTask, 'handle')"
                    >
                      登记落实
                    </button>
                  </td></template
                >
              </tr>
            </tbody>
          </table>
        </div>
        <div
          v-else-if="workspace !== 'tasks' && records.length"
          class="wb-table-wrap meeting__list"
        >
          <table class="wb-table">
            <thead>
              <tr>
                <th>活动与类型</th>
                <th>计划日期</th>
                <th>实际日期</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="record in records"
                :key="record.id"
                :class="{ meeting__selected: current?.id === record.id }"
              >
                <td>
                  <strong>{{ record.title }}</strong>
                  <p class="u-meta">{{ ACTIVITY_TYPE_LABELS[record.activity_type] }}</p>
                </td>
                <td>{{ record.scheduled_on }}</td>
                <td>{{ record.held_on || '待召开' }}</td>
                <td>
                  <span class="badge">{{ EXECUTION_LABELS[record.execution_status] }}</span>
                </td>
                <td>
                  <button
                    class="btn btn--ghost btn--sm"
                    type="button"
                    :disabled="busy || detailLoading"
                    @click="openRecord(record.id)"
                  >
                    打开活动
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="!pageError && !loading" class="wb-empty">
          {{
            workspace === 'tasks'
              ? '没有匹配的任务记录。'
              : workspace === 'history'
                ? '没有可访问的历史归档。'
                : '没有匹配的活动，可调整筛选或登记活动计划。'
          }}
        </p>
        <div v-if="!loading && !pageError && total > 20" class="wb-pager">
          <button
            class="btn btn--ghost"
            type="button"
            :disabled="filters.page <= 1 || busy"
            @click="changePage(-1)"
          >
            上一页</button
          ><span>第 {{ filters.page }} 页，共 {{ total }} 项</span
          ><button
            class="btn btn--ghost"
            type="button"
            :disabled="filters.page * 20 >= total || busy"
            @click="changePage(1)"
          >
            下一页
          </button>
        </div>
      </template>
    </WorkspaceTabs>

    <LoadingBlock v-if="detailLoading" variant="list" :rows="3" />
    <ErrorState
      v-if="actionError && !createOpen && !actionOpen && !taskDialog && !discardOpen"
      :error="actionError"
      ><button
        v-if="current && actionError instanceof ApiError && actionError.httpStatus === 409"
        class="btn btn--ghost"
        type="button"
        @click="openRecord(current.id)"
      >
        重新载入最新版本
      </button></ErrorState
    >
    <section v-if="current" class="wb-section wb-stack meeting__detail" :aria-busy="busy">
      <div class="wb-toolbar">
        <div>
          <h2>{{ current.title }}</h2>
          <p class="u-meta">
            {{ ACTIVITY_TYPE_LABELS[current.activity_type] }} / 版本 {{ current.revision }} /
            {{ REVIEW_LABELS[current.review_status] }}
          </p>
        </div>
        <button class="btn btn--quiet" type="button" :disabled="busy" @click="closeDetail">
          关闭活动
        </button>
      </div>
      <p v-if="current.restricted" class="wb-note">
        关联资料权限变更，正文、参会明细和衍生内容暂不可访问，请联系有权限的组织人员复核。
      </p>
      <template v-else>
        <div class="wb-actions">
          <button
            v-if="canEdit"
            class="btn btn--ghost"
            type="button"
            :disabled="busy || dirty || !current.source_doc_ids.length"
            @click="startAction('generate-agenda')"
          >
            生成议程与通知草稿
          </button>
          <button
            v-if="canEdit"
            class="btn btn--ghost"
            type="button"
            :disabled="busy || dirty || !current.transcript"
            @click="startAction('generate-minutes')"
          >
            从原文提取纪要
          </button>
          <button
            v-if="canEdit && ['draft', 'rejected'].includes(current.review_status)"
            class="btn btn--primary"
            type="button"
            :disabled="busy || dirty || !!current.missing.length"
            @click="startAction('submit')"
          >
            提交纪要审核
          </button>
          <button
            v-if="canReview && current.review_status === 'pending'"
            class="btn btn--primary"
            type="button"
            :disabled="busy || dirty || isSelfReview"
            @click="startAction('review')"
          >
            人工审核纪要
          </button>
          <button
            v-if="canReview && current.review_status === 'pending'"
            class="btn btn--ghost"
            type="button"
            :disabled="busy || dirty || isSelfReview"
            @click="startAction('review', 'rejected')"
          >
            退回补正
          </button>
          <button
            v-if="canArchive && current.review_status === 'approved' && !current.archived_at"
            class="btn btn--ghost"
            type="button"
            :disabled="busy || dirty || !!current.missing.length"
            @click="startAction('archive')"
          >
            归档已审核纪要
          </button>
          <button
            v-if="current.archived_at"
            class="btn btn--ghost"
            type="button"
            :disabled="busy"
            @click="exportArchive"
          >
            导出归档记录
          </button>
          <span v-if="dirty" class="badge badge--warn">有未保存修改</span>
        </div>
        <p v-if="current.review_status === 'pending' && isSelfReview" class="u-meta">
          本纪要由当前账号提交，须由另一位有审核权限的人员审核。
        </p>
        <details v-if="current.missing.length" class="wb-disclosure" open>
          <summary>审核前待补项（{{ current.missing.length }}）</summary>
          <p v-for="item in current.missing" :key="item" class="field__error">{{ item }}</p>
        </details>
        <WorkspaceTabs
          :model-value="detailTab"
          :items="detailTabs"
          label="活动办理内容"
          :disabled="busy"
          @update:model-value="changeDetail"
        >
          <div v-if="detailTab === 'details'" class="wb-stack">
            <div class="wb-grid">
              <label class="wb-field"
                ><span>计划日期</span
                ><input
                  v-model="edit.scheduled_on"
                  class="input"
                  type="date"
                  :disabled="!canEdit || busy" /></label
              ><label class="wb-field"
                ><span>实际召开日期</span
                ><input
                  v-model="edit.held_on"
                  class="input"
                  type="date"
                  :max="todayISO()"
                  :disabled="!canEdit || busy" /></label
              ><label class="wb-field"
                ><span>主持人</span
                ><input
                  v-model="edit.host"
                  class="input"
                  maxlength="100"
                  :disabled="!canEdit || busy"
              /></label>
            </div>
            <ParticipantEditor v-model="edit.participants" :readonly="!canEdit || busy" />
            <p v-if="!validParticipants(edit.participants)" class="field__error">
              请填写每位人员的姓名和唯一编号。
            </p>
            <SourcePicker
              v-model="edit.source_doc_ids"
              :sources="current.sources"
              :readonly="!canEdit || busy"
            />
            <details v-if="current.sources.length" class="wb-disclosure">
              <summary>资料来源与版本依据</summary>
              <article
                v-for="source in current.sources"
                :key="`${source.doc_id}:${source.content_revision}`"
                class="wb-log"
              >
                <p>
                  <strong>{{ source.title }}</strong>
                </p>
                <p>
                  {{ source.issuer }} / 版本 {{ source.content_revision }} /
                  {{ source.effective_date }}
                </p>
                <p>{{ source.excerpt }}</p>
              </article>
            </details>
          </div>
          <div v-else-if="detailTab === 'minutes'" class="wb-stack">
            <details class="wb-disclosure">
              <summary>议程与通知草稿</summary>
              <div class="wb-grid">
                <label class="wb-field"
                  ><span>议程草稿</span
                  ><textarea
                    v-model="edit.agenda"
                    class="textarea"
                    rows="5"
                    maxlength="20000"
                    :disabled="!canEdit || busy"
                  /></label
                ><label class="wb-field"
                  ><span>通知草稿</span
                  ><textarea
                    v-model="edit.notice"
                    class="textarea"
                    rows="5"
                    maxlength="20000"
                    :disabled="!canEdit || busy"
                  />
                </label>
              </div>
              <p class="u-meta">此处保存通知草稿，由组织人员核对后按现有通知渠道发送。</p>
            </details>
            <label class="wb-field"
              ><span>会议原始文本</span
              ><textarea
                v-model="edit.transcript"
                class="textarea"
                rows="8"
                maxlength="200000"
                :disabled="!canEdit || busy"
                :placeholder="`填写实际会议文本。${minuteSections
                  .map((section) => section.label)
                  .join('、')}可各占一行并用冒号标注。`"
              />
            </label>
            <p v-if="edit.transcript !== current.transcript" class="u-meta">
              保存修改后的原文会重新核验纪要。请保存后重新提取，不沿用旧纪要。
            </p>
            <section
              v-for="section in minuteSections"
              :key="section.key"
              class="wb-section wb-stack"
            >
              <h3>{{ section.label }}</h3>
              <p v-if="!edit.minutes[section.key]?.length" class="u-meta">
                原文尚未提取此项；请补充实际内容并重新提取。
              </p>
              <article
                v-for="(note, index) in edit.minutes[section.key]"
                :key="index"
                class="wb-stack"
              >
                <label class="wb-field"
                  ><span>纪要条目 {{ index + 1 }}</span
                  ><textarea
                    v-model="note.text"
                    class="textarea"
                    rows="2"
                    maxlength="5000"
                    :disabled="!canEdit || busy"
                  />
                </label>
                <blockquote class="wb-pre">原文依据：{{ note.quote }}</blockquote>
              </article>
            </section>
          </div>
          <div v-else-if="detailTab === 'tasks'" class="wb-stack">
            <div class="wb-toolbar">
              <h3>活动任务（{{ current.tasks.length }}）</h3>
              <button
                v-if="canManage && !current.archived_at"
                class="btn btn--ghost"
                type="button"
                :disabled="busy || dirty || !current.transcript"
                @click="startCreateTask"
              >
                从原文登记任务
              </button>
            </div>
            <p v-if="!current.tasks.length" class="wb-empty">
              尚未登记任务。原文未明确责任人和期限时，由组织人员补齐并确认。
            </p>
            <article v-for="task in current.tasks" :key="task.id" class="wb-section wb-stack">
              <div class="wb-toolbar">
                <strong>{{ task.task_text }}</strong
                ><span class="badge">{{ taskLabels[task.status] }}</span>
              </div>
              <p class="u-meta">
                责任人：{{ task.owner_name || '待补齐' }} / 期限：{{ task.due_on || '待补齐' }}
              </p>
              <p v-if="task.handle_note">落实说明：{{ task.handle_note }}</p>
              <div class="wb-actions">
                <button
                  v-if="canManage && task.status === 'pending'"
                  class="btn btn--ghost"
                  type="button"
                  :disabled="busy"
                  @click="startTask(task, 'confirm')"
                >
                  确认责任与期限</button
                ><button
                  v-if="canManage && task.status === 'active'"
                  class="btn btn--ghost"
                  type="button"
                  :disabled="busy"
                  @click="startTask(task, 'handle')"
                >
                  登记落实结果
                </button>
              </div>
            </article>
          </div>
          <div v-else class="wb-stack">
            <dl class="wb-facts wb-facts--small">
              <div>
                <dt>审核时间</dt>
                <dd>{{ current.reviewed_at || '待审核' }}</dd>
              </div>
              <div>
                <dt>归档时间</dt>
                <dd>{{ current.archived_at || '待归档' }}</dd>
              </div>
              <div>
                <dt>电子效力确认版本</dt>
                <dd>{{ current.archive_policy_version ?? '待学校确认' }}</dd>
              </div>
            </dl>
            <p v-if="current.review_comment">审核意见：{{ current.review_comment }}</p>
            <p class="wb-note">
              归档须经学校确认电子效力。系统保留当前版本、来源与审核记录，未完成确认时会明确提示。
            </p>
            <LoadingBlock v-if="revisionsLoading" variant="list" :rows="2" /><ErrorState
              v-if="revisionError"
              :error="revisionError"
            />
            <p v-if="!revisionsLoading && !revisions.length" class="wb-empty">
              没有可访问的版本记录。
            </p>
            <article v-for="entry in revisions" :key="entry.revision" class="wb-section wb-stack">
              <p>
                <strong>版本 {{ entry.revision }}</strong> / {{ entry.created_at }}
              </p>
              <p>操作：{{ revisionLabels[entry.action] || entry.action }}</p>
              <p>操作人：{{ entry.actor_id }}</p>
              <p>理由：{{ entry.reason }}</p>
              <p v-if="entry.restricted" class="u-meta">关联资料当前不可访问，该版本正文已隐藏。</p>
              <details v-else-if="entry.snapshot" class="wb-disclosure">
                <summary>查看版本正文</summary>
                <pre class="wb-pre">{{ revisionContent(entry.snapshot) }}</pre>
              </details>
            </article>
          </div>
        </WorkspaceTabs>
        <form v-if="canEdit" class="wb-actions meeting__save" @submit.prevent="saveRecord">
          <label class="wb-field"
            ><span>本次修改理由</span
            ><input
              v-model="edit.reason"
              class="input"
              maxlength="2000"
              required
              :disabled="busy" /></label
          ><button
            class="btn btn--primary"
            type="submit"
            :disabled="
              busy || !dirty || !edit.reason.trim() || !validParticipants(edit.participants)
            "
          >
            {{ busy ? '保存中…' : '保存活动资料' }}</button
          ><span class="u-meta">保存不会自动审核或归档。</span>
        </form>
      </template>
    </section>

    <ActionDialog
      :open="createOpen"
      title="登记组织生活计划"
      :busy="busy"
      wide
      @close="createOpen = false"
      ><form class="wb-stack" @submit.prevent="create">
        <div class="wb-grid">
          <label class="wb-field"
            ><span>所属组织</span
            ><select v-model="form.org_unit_id" class="select" required>
              <option value="">请选择有效组织</option>
              <option v-for="org in orgs" :key="org.id" :value="org.id">{{ org.name }}</option>
            </select></label
          ><label class="wb-field"
            ><span>活动类型</span
            ><select v-model="form.activity_type" class="select">
              <option v-for="(label, key) in ACTIVITY_TYPE_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          ><label class="wb-field"
            ><span>活动主题</span
            ><input v-model="form.title" class="input" maxlength="300" required /></label
          ><label class="wb-field"
            ><span>计划日期</span
            ><input v-model="form.scheduled_on" class="input" type="date" required /></label
          ><label class="wb-field"
            ><span>主持人</span><input v-model="form.host" class="input" maxlength="100"
          /></label>
        </div>
        <ParticipantEditor v-model="form.participants" /><SourcePicker
          v-model="form.source_doc_ids"
        /><label class="wb-field"
          ><span>登记理由</span
          ><textarea
            v-model="form.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
          /></label
        ><ErrorState v-if="orgError" :error="orgError" /><ErrorState
          v-if="actionError"
          :error="actionError"
        />
        <div class="wb-actions">
          <button
            class="btn btn--primary"
            type="submit"
            :disabled="
              busy ||
              !form.org_unit_id ||
              !form.reason.trim() ||
              !validParticipants(form.participants)
            "
          >
            保存活动计划
          </button>
          <p class="u-meta">计划日期可以晚于今天；实际召开日期在活动详情中登记。</p>
        </div>
      </form></ActionDialog
    >
    <ActionDialog
      :open="actionOpen"
      :title="actionTitles[pendingAction]"
      :busy="busy"
      @close="actionOpen = false"
      ><form class="wb-stack" @submit.prevent="runAction">
        <p>当前版本：{{ current?.revision }} / {{ current?.title }}</p>
        <p
          v-if="pendingAction === 'generate-agenda' || pendingAction === 'generate-minutes'"
          class="wb-note"
        >
          生成内容为草稿，保留原文依据，须人工核对。
        </p>
        <p v-if="pendingAction === 'archive'" class="wb-note">
          仅归档人工审核通过且学校已确认电子效力的版本。
        </p>
        <label v-if="pendingAction === 'review'" class="wb-field"
          ><span>人工审核结果</span
          ><select v-model="actionInput.decision" class="select">
            <option value="approved">人工审核通过</option>
            <option value="rejected">退回补正</option>
          </select></label
        ><label class="wb-field"
          ><span>{{ pendingAction === 'review' ? '审核意见与依据' : '操作理由' }}</span
          ><textarea
            v-model="actionInput.reason"
            class="textarea"
            rows="3"
            maxlength="2000"
            required
          /></label
        ><label class="wb-check"
          ><input
            v-model="actionInput.confirmed"
            type="checkbox"
            required
          />我已核对当前版本及操作内容。</label
        ><ErrorState v-if="actionError" :error="actionError" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !actionInput.reason.trim() || !actionInput.confirmed"
        >
          确认{{ actionTitles[pendingAction] }}
        </button>
      </form></ActionDialog
    >
    <ActionDialog
      :open="!!taskDialog"
      :title="
        taskDialog === 'create'
          ? '从会议原文登记任务'
          : taskDialog === 'confirm'
            ? '确认任务责任与期限'
            : '登记任务落实结果'
      "
      :busy="busy"
      wide
      @close="taskDialog = ''"
      ><form class="wb-stack" @submit.prevent="saveTask">
        <template v-if="taskDialog === 'create'"
          ><label class="wb-field"
            ><span>在已保存原文中选中任务文本</span
            ><textarea
              class="textarea"
              :value="current?.transcript"
              rows="6"
              readonly
              @select="selectExcerpt"
            /></label
          ><button class="btn btn--ghost" type="button" @click="useRequirement">
            摘取工作要求原文</button
          ><label class="wb-field"
            ><span>选中的任务摘录（保持原文）</span
            ><textarea
              v-model="taskForm.task_text"
              class="textarea"
              rows="3"
              readonly
              required
            /></label
        ></template>
        <p v-else>{{ taskEditing?.task_text }}</p>
        <div v-if="taskDialog !== 'handle'" class="wb-grid">
          <label class="wb-field"
            ><span>责任人{{ taskDialog === 'create' ? '（可待确认时补齐）' : '' }}</span
            ><input
              v-model="taskForm.owner_name"
              class="input"
              maxlength="100"
              :required="taskDialog === 'confirm'" /></label
          ><label class="wb-field"
            ><span>办理期限</span
            ><input
              v-model="taskForm.due_on"
              class="input"
              type="date"
              :required="taskDialog === 'confirm'"
          /></label>
        </div>
        <template v-else
          ><label class="wb-field"
            ><span>落实状态</span
            ><select v-model="taskForm.status" class="select">
              <option value="done">已完成</option>
              <option value="cancelled">依规取消</option>
            </select></label
          ><label class="wb-field"
            ><span>落实说明与依据</span
            ><textarea
              v-model="taskForm.handle_note"
              class="textarea"
              rows="3"
              maxlength="2000"
              required
            /></label></template
        ><label class="wb-field"
          ><span>操作理由</span
          ><input v-model="taskForm.reason" class="input" maxlength="2000" required /></label
        ><ErrorState v-if="actionError" :error="actionError" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="
            busy ||
            !taskForm.reason.trim() ||
            (taskDialog === 'create' &&
              (!taskForm.task_text || Array.from(taskForm.task_text).length > 2000))
          "
        >
          保存任务记录
        </button>
      </form></ActionDialog
    >
    <ActionDialog
      :open="discardOpen"
      title="处理未保存的活动修改"
      :busy="busy"
      @close="discardOpen = false"
      ><div class="wb-stack">
        <p>活动资料有未保存的修改。请先保存，或明确放弃这些修改再切换。</p>
        <label class="wb-field"
          ><span>保存修改的理由</span
          ><input v-model="edit.reason" class="input" maxlength="2000" /></label
        ><ErrorState v-if="actionError" :error="actionError" />
        <div class="wb-actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="busy || !edit.reason.trim()"
            @click="saveAndOpen"
          >
            保存后继续</button
          ><button class="btn btn--ghost" type="button" :disabled="busy" @click="discard">
            放弃修改后继续
          </button>
        </div>
      </div></ActionDialog
    >
  </div>
</template>

<style scoped>
.meeting {
  width: 100%;
  padding: var(--space-6);
  max-width: 1400px;
  margin-inline: auto;
}
.meeting .wb-tabs__body > form {
  margin-bottom: var(--space-4);
}
.meeting__list {
  margin-top: var(--space-4);
}
.meeting__list .wb-table {
  min-width: 680px;
}
.meeting__selected {
  background: var(--accent-wash);
}
.meeting__detail {
  border-top: 3px solid var(--accent);
}
.meeting__save {
  padding-top: var(--space-5);
  border-top: var(--border);
}
.meeting__save .wb-field {
  flex: 1;
  min-width: min(100%, 220px);
}
.meeting__detail > .wb-toolbar h2 {
  line-height: var(--leading-normal);
}
@media (max-width: 767px) {
  .meeting {
    padding: var(--space-4);
  }
  .meeting__save {
    align-items: stretch;
  }
}
</style>
