<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  ACTIVITY_TYPE_LABELS,
  EXECUTION_LABELS,
  REVIEW_LABELS,
  meetingApi,
  type ActivityType,
  type MeetingRecord,
  type MeetingStats,
  type MeetingTask,
} from '@/api/meeting'
import { session } from '@/stores/session'

const orgs = ref<{ id: string; name: string; org_type: string }[]>([])
const records = ref<MeetingRecord[]>([])
const total = ref(0)
const current = ref<MeetingRecord | null>(null)
const stats = ref<MeetingStats | null>(null)
const tips = ref('')
const busy = ref(false)

const filters = reactive({ year: '', activity_type: '', execution_status: '', page: 1 })
const pageSize = 20

const canManage = computed(() => session.can('meeting.manage'))
const canReview = computed(() => session.can('meeting.review'))

const blank = () => ({
  org_unit_id: '',
  activity_type: 'branch_member_meeting' as ActivityType,
  title: '',
  scheduled_on: '',
  host: '',
  source_doc_ids: '',
  reason: '',
})

const form = reactive(blank())

async function loadOrgs(): Promise<void> {
  orgs.value = (await meetingApi.organizations()).items
  if (!form.org_unit_id && orgs.value.length) form.org_unit_id = orgs.value[0].id
}

async function loadRecords(): Promise<void> {
  const data = await meetingApi.records({
    page: filters.page,
    page_size: pageSize,
    year: filters.year || undefined,
    activity_type: filters.activity_type || undefined,
    execution_status: filters.execution_status || undefined,
  })
  records.value = data.items
  total.value = data.total
}

async function loadStats(): Promise<void> {
  const year = Number(filters.year || new Date().getFullYear())
  stats.value = await meetingApi.stats({ year })
}

async function authAction<T extends () => Promise<unknown>>(fn: T): Promise<boolean> {
  busy.value = true
  try {
    await (fn as () => Promise<unknown>)()
    return true
  } catch (error) {
    tips.value = error instanceof Error ? error.message : String(error)
    return false
  } finally {
    busy.value = false
  }
}

async function onCreate(): Promise<void> {
  const source_doc_ids = form.source_doc_ids
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  if (await authAction(() => meetingApi.create({
    org_unit_id: form.org_unit_id,
    activity_type: form.activity_type,
    title: form.title,
    scheduled_on: form.scheduled_on,
    host: form.host,
    source_doc_ids,
    reason: form.reason,
  }))) {
    Object.assign(form, blank())
    void loadRecords()
  }
}

async function openRecord(id: string): Promise<void> {
  tips.value = ''
  if (await authAction(async () => {
    current.value = await meetingApi.record(id)
  })) {
    void loadStats()
  }
}

function revisionBody(extra: Record<string, unknown> = {}) {
  return { expected_revision: current.value?.revision ?? 1, reason: '组织人员操作', ...extra }
}

async function recordAction(action: string, body: Record<string, unknown> = {}): Promise<void> {
  if (!current.value) return
  if (await authAction(async () => {
    current.value = await meetingApi.action(current.value!.id, action as never, revisionBody(body) as never)
  })) {
    void loadRecords()
    void loadStats()
  }
}

async function saveTranscript(text: string): Promise<void> {
  if (!current.value) return
  if (await authAction(async () => {
    current.value = await meetingApi.update(current.value!.id, revisionBody({ transcript: text }))
  })) {
    void loadRecords()
  }
}

async function review(decision: 'approved' | 'rejected'): Promise<void> {
  if (!current.value) return
  const comment = window.prompt(`审核意见（${decision === 'approved' ? '通过' : '退回'}）`, '核对原文与参会后审核')
  if (comment === null) return
  await recordAction('review', { decision, reason: comment })
}

// —— 任务操作 ——
const newTask = reactive({ task_text: '', owner_name: '', due_on: '', source_start: 0 })

function useExcerpt(): void {
  if (!current.value) return
  const line = current.value.transcript.split('\n').find((part) => part.trim().includes('工作要求')) ?? ''
  const position = current.value.transcript.indexOf(line)
  newTask.task_text = line.trim()
  newTask.source_start = position
}

async function onCreateTask(): Promise<void> {
  if (!current.value) return
  const len = newTask.task_text.length
  if (await authAction(() => meetingApi.createTask(current.value!.id, {
    task_text: newTask.task_text,
    source_start: newTask.source_start,
    source_end: newTask.source_start + len,
    owner_name: newTask.owner_name,
    due_on: newTask.due_on || null,
    reason: '从会议原文摘录任务',
  }))) {
    Object.assign(newTask, { task_text: '', owner_name: '', due_on: '', source_start: 0 })
    void openRecord(current.value.id)
  }
}

async function confirmTask(task: MeetingTask): Promise<void> {
  const owner = window.prompt('确认责任人（原文未明确时人工补齐）', task.owner_name)
  if (!owner) return
  if (await authAction(() => meetingApi.confirmTask(task.id, { owner_name: owner, reason: '人工确认责任人后进入台账' }))) {
    void openRecord(current.value!.id)
  }
}

async function handleTask(task: MeetingTask): Promise<void> {
  if (await authAction(() => meetingApi.handleTask(task.id, { status: 'done', handle_note: '已落实', reason: '任务完成' }))) {
    void openRecord(current.value!.id)
  }
}

async function requestArchive(): Promise<void> {
  await recordAction('archive')
}

onMounted(() => {
  void loadOrgs()
  void loadRecords()
})
</script>

<template>
  <div class="meeting">
    <header class="meeting__head">
      <div>
        <h1>组织生活（三会一课）</h1>
        <p class="meeting__sub">一次录入即可复用的支部活动全过程记录；生成内容均为草稿，组织认定由支部人工完成。</p>
      </div>
      <div class="meeting__filters">
        <select v-model="filters.year" @change="filters.page = 1; loadRecords(); loadStats()">
          <option value="">全部年度</option>
          <option v-for="y in [2026, 2025, 2024]" :key="y" :value="String(y)">{{ y }}</option>
        </select>
        <select v-model="filters.activity_type" @change="filters.page = 1; loadRecords()">
          <option value="">全部类型</option>
          <option v-for="(label, key) in ACTIVITY_TYPE_LABELS" :key="key" :value="key">{{ label }}</option>
        </select>
        <select v-model="filters.execution_status" @change="filters.page = 1; loadRecords()">
          <option value="">全部状态</option>
          <option v-for="(label, key) in EXECUTION_LABELS" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>
    </header>

    <p v-if="tips" class="meeting__tip" role="alert">{{ tips }}</p>

    <section class="meeting__grid">
      <aside class="meeting__side">
        <form v-if="canManage" class="panel" @submit.prevent="onCreate">
          <h2 class="panel__title">登记活动计划</h2>
          <label>组织
            <select v-model="form.org_unit_id" required>
              <option v-for="org in orgs" :key="org.id" :value="org.id">{{ org.name }}（{{ org.org_type }}）</option>
            </select>
          </label>
          <label>类型
            <select v-model="form.activity_type">
              <option v-for="(label, key) in ACTIVITY_TYPE_LABELS" :key="key" :value="key">{{ label }}</option>
            </select>
          </label>
          <label>议题/标题 <input v-model="form.title" required maxlength="300" placeholder="例：2026年第一季度支部大会" /></label>
          <label>计划日期 <input v-model="form.scheduled_on" type="date" required /></label>
          <label>主持人 <input v-model="form.host" maxlength="100" /></label>
          <label>依据资料编号（逗号分隔） <input v-model="form.source_doc_ids" placeholder="可选，如 DOC-001" /></label>
          <label>登记依据 <input v-model="form.reason" required maxlength="2000" placeholder="登记/修改说明" /></label>
          <button class="btn btn--primary" type="submit" :disabled="busy">登记计划</button>
        </form>

        <div class="panel">
          <h2 class="panel__title">年度统计（仅审核通过记录计入）</h2>
          <p v-if="!stats" class="muted">选择年度后显示。</p>
          <template v-else>
            <dl class="meeting__dl">
              <dt>已审核通过</dt>
              <dd>{{ stats.counts?.completed ?? 0 }}</dd>
              <dt>已归档</dt>
              <dd>{{ stats.counts?.archived ?? 0 }}</dd>
              <dt>参学率</dt>
              <dd>{{ stats.attendance_rate?.value ?? '待补' }}</dd>
            </dl>
            <p
              v-for="(label, key) in ACTIVITY_TYPE_LABELS"
              :key="key"
              class="meeting__req"
            >
              {{ label }}：规定 {{ stats.by_type?.[key]?.required ?? '-' }} 次 /
              已审核 {{ stats.by_type?.[key]?.performed ?? 0 }} 次（仅提示）
            </p>
          </template>
        </div>
      </aside>

      <div class="meeting__main">
        <div class="panel">
          <h2 class="panel__title">活动记录（{{ total }}）</h2>
          <ul class="meeting__list">
            <li v-for="record in records" :key="record.id">
              <button class="meeting__row" type="button" @click="openRecord(record.id)">
                <span class="meeting__row-title">
                  {{ ACTIVITY_TYPE_LABELS[record.activity_type] }} · {{ record.title }}
                </span>
                <span class="meeting__row-meta">
                  {{ record.scheduled_on }} · {{ EXECUTION_LABELS[record.execution_status] }}
                  <span v-if="record.missing.length" class="badge badge--warn">缺项 {{ record.missing.length }}</span>
                </span>
              </button>
            </li>
          </ul>
          <div v-if="total > pageSize" class="meeting__pager">
            <button class="btn" :disabled="filters.page <= 1" type="button" @click="filters.page -= 1; loadRecords()">上一页</button>
            <span>{{ filters.page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
            <button class="btn" :disabled="filters.page * pageSize >= total" type="button" @click="filters.page += 1; loadRecords()">下一页</button>
          </div>
        </div>

        <div v-if="current" class="panel">
          <h2 class="panel__title">
            {{ ACTIVITY_TYPE_LABELS[current.activity_type] }} · {{ current.title }}
            <span class="badge">{{ EXECUTION_LABELS[current.execution_status] }}</span>
          </h2>
          <p class="muted">版本 {{ current.revision }} · {{ REVIEW_LABELS[current.review_status] }}{{ current.reviewed_at ? ' · 审核时间 ' + current.reviewed_at : '' }}</p>
          <p v-for="item in current.missing" :key="item" class="meeting__missing">{{ item }}</p>

          <div v-if="canManage" class="meeting__actions">
            <button class="btn" type="button" @click="recordAction('generate-agenda')">生成议程/通知草稿</button>
            <button class="btn" type="button" @click="recordAction('generate-minutes')">逐项提取纪要</button>
            <button
              v-if="current.review_status === 'draft' || current.review_status === 'rejected'"
              class="btn btn--primary"
              type="button"
              @click="recordAction('submit')"
            >提交审核</button>
            <button v-if="canReview" class="btn" type="button" @click="review('approved')">审核通过</button>
            <button v-if="canReview" class="btn btn--danger" type="button" @click="review('rejected')">退回</button>
            <button
              v-if="current.execution_status === 'completed'"
              class="btn"
              type="button"
              :disabled="!canManage"
              @click="requestArchive"
            >申请归档</button>
          </div>

          <div v-if="current.context?.agenda" class="meeting__block">
            <h3>议程草稿</h3>
            <pre class="meeting__pre">{{ current.context.agenda }}</pre>
          </div>
          <div v-if="current.context?.notice" class="meeting__block">
            <h3>通知草稿</h3>
            <pre class="meeting__pre">{{ current.context.notice }}</pre>
          </div>

          <div class="meeting__block">
            <h3>会议文本与纪要</h3>
            <label v-if="canManage">计划日期 <input v-model="current.scheduled_on" type="date" /></label>
            <label v-if="canManage">实际召开日期 <input v-if="current.held_on" v-model="current.held_on" type="date" /></label>
            <textarea
              v-if="canManage"
              v-model="current.transcript"
              rows="6"
              placeholder="粘贴会议原始文本（学习要点/讨论共识/工作要求 各占一行，以“：”标注）"
              @change="saveTranscript(current.transcript)"
            />
            <pre v-else class="meeting__pre">{{ current.transcript || '（原文待补）' }}</pre>
            <p class="muted" v-if="current.minutes?.learning_points?.length">学习要点 {{ current.minutes.learning_points.length }} 条 · 共识 {{ current.minutes.consensus?.length ?? 0 }} 条 · 要求 {{ current.minutes.requirements?.length ?? 0 }} 条</p>
          </div>

          <div class="meeting__block">
            <h3>任务台账（{{ current.tasks.length }}）</h3>
            <ul v-if="current.tasks.length" class="meeting__list">
              <li v-for="task in current.tasks" :key="task.id" class="meeting__task">
                <span>{{ task.task_text }}</span>
                <span class="meeting__row-meta">
                  责任人：{{ task.owner_name || '待补齐' }} · {{ task.status }}
                  <button v-if="task.status === 'pending'" class="btn btn--sm" type="button" @click="confirmTask(task)">确认</button>
                  <button v-if="task.status === 'active'" class="btn btn--sm" type="button" @click="handleTask(task)">完成</button>
                </span>
              </li>
            </ul>
            <div v-if="canManage && current.transcript" class="meeting__task-form">
              <button class="btn btn--sm" type="button" @click="useExcerpt">摘取“工作要求”原文</button>
              <input v-model="newTask.task_text" placeholder="任务文本（须与原文一致）" />
              <input v-model="newTask.owner_name" placeholder="责任人（可待人工补齐）" />
              <input v-model="newTask.due_on" type="date" />
              <button class="btn btn--sm btn--primary" type="button" @click="onCreateTask">登记任务</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.meeting { display: flex; flex-direction: column; gap: 16px; padding: 20px; }
.meeting__head { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: flex-start; }
.meeting__head h1 { font-family: var(--font-serif); font-size: 22px; color: var(--ink); }
.meeting__sub { font-size: 13px; color: var(--ink-muted); margin-top: 4px; }
.meeting__filters { display: flex; gap: 8px; flex-wrap: wrap; }
.meeting__grid { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
.meeting__side { display: flex; flex-direction: column; gap: 16px; }
.meeting__main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.panel { background: var(--paper); border: var(--border); border-radius: var(--radius-md); padding: 16px; }
.panel__title { font-size: 15px; font-weight: 600; color: var(--ink); margin-bottom: 12px; }
.meeting__actions { display: flex; gap: 8px; flex-wrap: wrap; padding: 8px 0; }
.meeting__list { display: flex; flex-direction: column; gap: 6px; list-style: none; }
.meeting__row { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 10px 12px; border: 1px solid var(--rule); border-radius: var(--radius-sm); background: var(--paper-dim); }
.meeting__row:hover { border-color: var(--accent-edge); }
.meeting__row-title { font-weight: 600; color: var(--ink); }
.meeting__row-meta { font-size: 12px; color: var(--ink-faint); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.meeting__missing { font-size: 12px; color: var(--accent); }
.meeting__dl { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; font-size: 13px; }
.meeting__dl dd { font-weight: 600; color: var(--ink); }
.meeting__req { font-size: 12px; color: var(--ink-muted); }
.meeting__block { border-top: 1px solid var(--rule); padding: 12px 0; }
.meeting__block h3 { font-size: 13px; color: var(--ink-soft); margin-bottom: 8px; }
.meeting__pre { white-space: pre-wrap; font-size: 13px; line-height: 1.6; color: var(--ink-soft); background: var(--paper-dim); border: 1px solid var(--rule); border-radius: var(--radius-sm); padding: 10px; }
.meeting__task, .meeting__task-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.meeting__task-form { border-top: 1px dashed var(--rule); margin-top: 8px; padding-top: 8px; }
.meeting__pager { display: flex; gap: 8px; align-items: center; margin-top: 12px; font-size: 13px; }
.meeting__tip { color: var(--accent-deep); font-size: 13px; }
.muted { color: var(--ink-faint); font-size: 12px; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); margin-bottom: 8px; }
input, select, textarea { border: 1px solid var(--rule); border-radius: var(--radius-sm); padding: 6px 8px; font-size: 13px; background: var(--paper); color: var(--ink); }
textarea { width: 100%; font-family: inherit; }
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: var(--radius-full); background: var(--paper-dim); border: 1px solid var(--rule); color: var(--ink-soft); }
.badge--warn { color: var(--accent-deep); border-color: var(--accent-edge); background: var(--accent-wash); }
@media (max-width: 900px) { .meeting__grid { grid-template-columns: 1fr; } }
</style>