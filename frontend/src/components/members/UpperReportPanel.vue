<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { listMembers } from '@/api/member'
import {
  upperReportApi as api,
  type UpperItemCatalog,
  type UpperItemKey,
  type UpperReportRecord,
  type UpperReportSummary,
  type UpperResult,
} from '@/api/upper-report'
import { ApiError } from '@/api/http'
import { STAGE_ORDER, type MemberRosterItem } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { session } from '@/stores/session'
import { downloadBlob, todayISO } from '@/utils/files'

/**
 * 上级党组织审批 / 备案报送（T-MEM-11）。
 *
 * 这一屏最容易被做成"反人类"的事只有一件：**让系统或支部自己把上级的决定点出来**。
 * 系统里没有上级党组织的登录身份，所以这里没有"审批通过"按钮，只有两件事：
 *   1. 登记报送——把"材料已报出去"这一事实记下来，状态停在「已报送待批复」；
 *   2. 回填批复——把**上级的结论**登记进来（同意 / 不同意 / 需补充材料），而且没有文号的
 *      "同意"填不进去（无法对账的结论不是批复）。
 * 回填批复不改动党员阶段：入党与转正是组织结论，阶段仍由授权人员在人工流转里按程序办理。
 * 备案类事项细则未统一规定时限，界面如实写"按上级党委规定"，不编一个期限出来。
 */

const emit = defineEmits<{ busy: [value: boolean] }>()

const canManage = computed(() => session.can('member.stage_transition'))
const loading = ref(true)
const busy = ref(false)
const error = ref<unknown>(null)
const message = ref('')

const itemFilter = ref<'' | UpperItemKey>('')
const kindFilter = ref<'' | 'record' | 'approval'>('')
const statusFilter = ref<'' | 'submitted' | 'settled' | 'revoked'>('')
const overdueOnly = ref(false)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const records = ref<UpperReportRecord[]>([])
const summary = ref<UpperReportSummary | null>(null)
const catalog = ref<UpperItemCatalog[]>([])
const notice = ref('')
const historyOpen = ref<string | null>(null)

const candidates = ref<MemberRosterItem[]>([])

const createOpen = ref(false)
const settling = ref<UpperReportRecord | null>(null)
const revoking = ref<UpperReportRecord | null>(null)

const createForm = reactive({
  item: '' as '' | UpperItemKey,
  profile_id: '',
  upper_org: '',
  letter_no: '',
  submitted_on: todayISO(),
  note: '',
  reason: '',
})
const settleForm = reactive({
  result: 'agreed' as UpperResult,
  decided_on: todayISO(),
  reply_no: '',
  decide_note: '',
  reason: '',
})
const revokeForm = reactive({ reason: '' })

const RESULT_LABELS: Record<UpperResult, string> = {
  agreed: '同意 / 批准',
  rejected: '不同意',
  supplement: '需补充材料',
}

/** 当前选中的事项：依据、报给谁与随报材料都由后端目录给出，界面不另写一套。 */
const activeItem = computed(
  () => catalog.value.find((entry) => entry.item === createForm.item) ?? null,
)

function stageRank(stage: string): number {
  return STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number])
}

/** 阶段已到（或已过）该事项目标阶段才可报送：支部大会 / 支委会先作出决定。 */
const eligibleProfiles = computed(() => {
  const item = activeItem.value
  if (!item) return []
  const target = stageRank(item.stage)
  return candidates.value.filter((row) => stageRank(row.stage) >= target)
})

const createValid = computed(
  () =>
    createForm.item !== '' &&
    createForm.profile_id !== '' &&
    createForm.upper_org.trim() !== '' &&
    createForm.submitted_on !== '' &&
    createForm.reason.trim() !== '',
)
/** 没有文号的"同意 / 不同意"不是批复；"需补充材料"必须写清缺什么。 */
const settleValid = computed(() => {
  if (settleForm.reason.trim() === '') return false
  if (settleForm.result === 'supplement') return settleForm.decide_note.trim() !== ''
  return settleForm.reply_no.trim() !== ''
})

function statusTone(row: UpperReportRecord): string {
  if (row.status === 'revoked') return ''
  if (row.status === 'submitted') return 'badge--warn'
  if (row.result === 'agreed') return 'badge--ok'
  if (row.result === 'rejected') return 'badge--bad'
  return 'badge--accent'
}

function resultText(row: UpperReportRecord): string {
  if (row.status === 'submitted') return '等待上级批复'
  return row.result_label || '—'
}

/** 后端时间为 UTC，展示按北京时间，避免"刚操作完显示 8 小时前"。 */
function formatStamp(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(new Date(value.endsWith('Z') ? value : `${value}Z`))
}

let sequence = 0
let alive = true

async function mutate(fn: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = true
  emit('busy', true)
  error.value = null
  message.value = ''
  try {
    await fn()
  } catch (err) {
    error.value = err
  } finally {
    busy.value = false
    emit('busy', false)
  }
}

async function loadCandidates(): Promise<void> {
  try {
    const data = await listMembers({ page: 1, page_size: 100, include_transferred: true })
    if (!alive) return
    candidates.value = data.items
  } catch (err) {
    if (alive) error.value = err
  }
}

async function load(): Promise<void> {
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const data = await api.list({
      item: itemFilter.value || undefined,
      kind: kindFilter.value || undefined,
      status: statusFilter.value || undefined,
      overdue: overdueOnly.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    if (current !== sequence || !alive) return
    records.value = data.items
    total.value = data.total
    summary.value = data.summary
    catalog.value = data.items_catalog
    notice.value = data.notice
    historyOpen.value = null
  } catch (err) {
    if (current === sequence && alive) error.value = err
  } finally {
    if (current === sequence && alive) loading.value = false
  }
}

function reload(): void {
  page.value = 1
  void load()
}

function turnPage(delta: number): void {
  page.value += delta
  void load()
}

function openCreate(): void {
  error.value = null
  Object.assign(createForm, {
    item: catalog.value[0]?.item ?? '',
    profile_id: '',
    upper_org: '',
    letter_no: '',
    submitted_on: todayISO(),
    note: '',
    reason: '',
  })
  void loadCandidates()
  createOpen.value = true
}

async function createReport(): Promise<void> {
  await mutate(async () => {
    const created = await api.create({
      profile_id: createForm.profile_id,
      item: createForm.item as UpperItemKey,
      upper_org: createForm.upper_org.trim(),
      ...(createForm.letter_no.trim() ? { letter_no: createForm.letter_no.trim() } : {}),
      submitted_on: createForm.submitted_on,
      note: createForm.note.trim(),
      reason: createForm.reason.trim(),
    })
    createOpen.value = false
    await load()
    message.value = `已登记报送：${created.item_label} · ${created.member_name}。${created.notice ?? ''}`
  })
}

function openSettle(row: UpperReportRecord): void {
  error.value = null
  Object.assign(settleForm, {
    result: 'agreed' as UpperResult,
    decided_on: todayISO(),
    reply_no: '',
    decide_note: '',
    reason: '',
  })
  settling.value = row
}

async function settle(): Promise<void> {
  const target = settling.value
  if (!target) return
  await mutate(async () => {
    const done = await api.settle(target.id, {
      result: settleForm.result,
      decided_on: settleForm.decided_on,
      reply_no: settleForm.reply_no.trim(),
      decide_note: settleForm.decide_note.trim(),
      reason: settleForm.reason.trim(),
    })
    settling.value = null
    await load()
    message.value = done.notice ?? '已回填上级批复。'
  })
}

function openRevoke(row: UpperReportRecord): void {
  error.value = null
  revokeForm.reason = ''
  revoking.value = row
}

async function revoke(): Promise<void> {
  const target = revoking.value
  if (!target) return
  await mutate(async () => {
    const done = await api.revoke(target.id, { reason: revokeForm.reason.trim() })
    revoking.value = null
    await load()
    message.value = done.notice ?? '本次报送已作废。'
  })
}

function openHistory(row: UpperReportRecord): void {
  historyOpen.value = historyOpen.value === row.id ? null : row.id
  if (historyOpen.value !== row.id || row.history) return
  void mutate(async () => {
    const detail = await api.detail(row.id)
    const index = records.value.findIndex((entry) => entry.id === row.id)
    if (index >= 0) records.value[index] = { ...records.value[index]!, history: detail.history ?? [] }
  })
}

async function exportLedger(): Promise<void> {
  await mutate(async () => {
    try {
      downloadBlob(await api.downloadLedger(), `上级审批备案报送台账-${todayISO()}.xlsx`)
      message.value = '已导出台账：只含报送要素与随报材料清单，不含材料原件与政治审查材料内容。'
    } catch (err) {
      throw err instanceof ApiError ? err : new Error('导出失败，请重试')
    }
  })
}

const overdueRows = computed(() => records.value.filter((row) => row.overdue))

onMounted(() => {
  void loadCandidates()
  void load()
})
onBeforeUnmount(() => {
  alive = false
  sequence += 1
})
</script>

<template>
  <section class="wb wb-stack" :aria-busy="busy || loading">
    <p class="wb-note">
      上级审批 / 备案只登记两件事：<strong>支部已把材料报送出去</strong>、<strong>上级的批复结果是什么</strong>。
      系统不代替上级党组织审批——这里没有"审批通过"按钮；回填批复也不改动党员的阶段，入党与转正仍由组织按程序决定，
      阶段变更走人工流转。回填「同意 / 不同意」必须填上级批复文号（没有文号的结论无法对账），「需补充材料」要写清缺什么。
      审批类事项按细则"三个月内审批"倒计时、临近时限提前提示，<strong>备案类时限按上级党委规定</strong>，系统不另设期限。
    </p>

    <div v-if="summary" class="up-summary">
      <span class="up-summary__item"><b>{{ summary.pending }}</b> 已报送待批复</span>
      <span class="up-summary__item">其中审批类 <b>{{ summary.pending_approval }}</b></span>
      <span class="up-summary__item" :class="{ 'is-alert': summary.overdue > 0 }"><b>{{ summary.overdue }}</b> 已超过审批时限</span>
      <span class="up-summary__item"><b>{{ summary.supplement }}</b> 需补充材料</span>
      <span class="up-summary__item"><b>{{ summary.settled }}</b> 已回填批复</span>
      <span class="up-summary__item"><b>{{ summary.this_year }}</b> 本年度报送</span>
    </div>

    <div class="wb-toolbar">
      <div class="wb-actions">
        <label class="wb-field"><span>事项</span>
          <select v-model="itemFilter" class="select" :disabled="loading || busy" @change="reload">
            <option value="">全部</option>
            <option v-for="entry in catalog" :key="entry.item" :value="entry.item">{{ entry.label }}</option>
          </select>
        </label>
        <label class="wb-field"><span>类别</span>
          <select v-model="kindFilter" class="select" :disabled="loading || busy" @change="reload">
            <option value="">全部</option>
            <option value="record">备案</option>
            <option value="approval">审批</option>
          </select>
        </label>
        <label class="wb-field"><span>状态</span>
          <select v-model="statusFilter" class="select" :disabled="loading || busy" @change="reload">
            <option value="">全部</option>
            <option value="submitted">已报送待批复</option>
            <option value="settled">已回填批复</option>
            <option value="revoked">已作废</option>
          </select>
        </label>
        <label class="wb-check"><input v-model="overdueOnly" type="checkbox" :disabled="loading || busy" @change="reload" /><span>只看已超过审批时限</span></label>
      </div>
      <template v-if="canManage">
        <button class="btn btn--primary" type="button" :disabled="busy || !catalog.length" @click="openCreate">登记报送</button>
      </template>
      <button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="exportLedger">导出台账</button>
      <button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="reload">刷新</button>
    </div>

    <ErrorState v-if="error && !createOpen && !settling && !revoking" :error="error" />
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>

    <!-- 已按"只看超期"筛选时不再重复一块提示区，避免同一批记录出现两遍 -->
    <section v-if="overdueRows.length && !overdueOnly" class="wb-section up-alert">
      <h3>需向上级核实审批进度（{{ overdueRows.length }}）</h3>
      <ul>
        <li v-for="row in overdueRows" :key="row.id">{{ row.member_name }}：{{ row.overdue_notice }}</li>
      </ul>
      <p class="u-meta">以上仅为提示，审批结果以上级党组织的批复为准；系统不判定审批失效、也不改动党员阶段。</p>
    </section>

    <LoadingBlock v-if="loading" variant="table" :rows="4" />
    <div v-else-if="records.length" class="wb-table-wrap">
      <table class="wb-table">
        <thead>
          <tr>
            <th>事项</th><th>党员</th><th>上级组织</th><th>报送</th><th>状态与批复</th><th>时限</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in records" :key="row.id">
            <tr>
              <td>
                {{ row.item_label }}
                <p class="u-meta">{{ row.kind_label }} · 报 {{ row.report_to }}</p>
              </td>
              <td>{{ row.member_name }}<p class="u-meta">{{ row.stage_label || '—' }} · {{ row.org_name }}</p></td>
              <td>{{ row.upper_org }}<p v-if="row.letter_no" class="u-meta">报送文号 {{ row.letter_no }}</p></td>
              <td>{{ row.submitted_on }}<p class="u-meta">随报 {{ row.material_count }} 项</p></td>
              <td>
                <span class="badge" :class="statusTone(row)">{{ row.status_label }}</span>
                <p class="u-meta">{{ resultText(row) }}<template v-if="row.reply_no"> · {{ row.reply_no }}</template></p>
                <p v-if="row.decided_on" class="u-meta">批复日期 {{ row.decided_on }}</p>
                <p v-if="row.decide_note" class="u-meta">{{ row.decide_note }}</p>
              </td>
              <td>
                <template v-if="row.kind === 'approval'">
                  <span v-if="row.overdue" class="field__error">已超过审批时限 {{ -row.days_left! }} 天</span>
                  <span v-else-if="row.status === 'submitted' && row.due_soon" class="up-due">剩余 {{ row.days_left }} 天，临近审批时限</span>
                  <span v-else-if="row.status === 'submitted'" class="u-meta">剩余 {{ row.days_left }} 天</span>
                  <span v-else class="u-meta">—</span>
                </template>
                <span v-else class="u-meta">按上级党委规定</span>
              </td>
              <td>
                <button v-if="canManage && row.status === 'submitted'" class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="openSettle(row)">回填批复</button>
                <button v-if="canManage && row.status !== 'revoked'" class="btn btn--quiet btn--sm" type="button" :disabled="busy" @click="openRevoke(row)">作废</button>
                <button class="btn btn--quiet btn--sm" type="button" :disabled="busy" @click="openHistory(row)">
                  {{ historyOpen === row.id ? '收起留痕' : '留痕' }}
                </button>
              </td>
            </tr>
            <tr v-if="historyOpen === row.id" class="up-history">
              <td colspan="7">
                <p v-if="!row.history" class="u-meta">读取留痕中…</p>
                <ul v-else>
                  <li v-for="item in row.history" :key="`${row.id}-${item.revision}`">
                    第 {{ item.revision }} 版 · {{ formatStamp(item.created_at) }} · 操作人 {{ item.actor_id }} · {{ item.action }}
                    <p class="u-meta">{{ item.reason || '未填写理由' }}</p>
                  </li>
                </ul>
                <p class="u-meta">依据：{{ row.basis }}</p>
                <p v-if="row.materials.length" class="u-meta">随报材料：{{ row.materials.join('、') }}</p>
                <p v-if="row.revoked_on" class="u-meta">作废于 {{ row.revoked_on }}：{{ row.revoke_reason }}</p>
                <p v-if="row.note" class="u-meta">备注：{{ row.note }}</p>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <p v-else-if="!error" class="wb-empty">当前筛选下没有报送记录。报送从"支委会 / 支部大会作出决定"之后开始登记。</p>

    <p v-if="notice" class="u-meta">{{ notice }}</p>

    <div v-if="!loading && total > pageSize" class="wb-pager">
      <button class="btn btn--ghost" type="button" :disabled="page <= 1 || busy" @click="turnPage(-1)">上一页</button>
      <span>第 {{ page }} 页，共 {{ total }} 条</span>
      <button class="btn btn--ghost" type="button" :disabled="page * pageSize >= total || busy" @click="turnPage(1)">下一页</button>
    </div>

    <!-- ---------------------------- 登记报送 ---------------------------- -->
    <ActionDialog :open="createOpen" title="登记向上级党组织报送" :busy="busy" wide @close="createOpen = false">
      <form class="wb-stack" @submit.prevent="createReport">
        <p class="wb-note">登记后状态为「已报送待批复」：这表示材料已报出，<strong>不代表上级已经同意</strong>。收到批复后回到本台账回填结果；此操作不改动党员的阶段。</p>
        <label class="wb-field"><span>报送事项</span>
          <select v-model="createForm.item" class="select" required @change="createForm.profile_id = ''">
            <option value="">请选择事项</option>
            <option v-for="entry in catalog" :key="entry.item" :value="entry.item">{{ entry.label }}（{{ entry.kind_label }}）</option>
          </select>
        </label>
        <template v-if="activeItem">
          <p class="wb-note">依据：{{ activeItem.basis }}<br />报送给：{{ activeItem.report_to }}。随报材料（与阶段材料要求同一来源）：{{ activeItem.materials.join('、') || '无' }}。</p>
        </template>
        <label class="wb-field"><span>报送党员（阶段已到该事项环节）</span>
          <select v-model="createForm.profile_id" class="select" required>
            <option value="">请选择党员</option>
            <option v-for="row in eligibleProfiles" :key="row.id" :value="row.id">{{ row.name }}（{{ row.org_name }}）</option>
          </select>
        </label>
        <p v-if="createForm.item && !eligibleProfiles.length" class="u-meta">当前范围内没有阶段已到该环节的党员。建议先完成阶段流转，再登记报送。</p>
        <div class="wb-grid">
          <label class="wb-field"><span>上级组织名称（受理备案 / 审批的党委、工委）</span><input v-model="createForm.upper_org" class="input" maxlength="200" required /></label>
          <label class="wb-field"><span>报送日期</span><input v-model="createForm.submitted_on" class="input" type="date" required /></label>
          <label class="wb-field"><span>报送文号（有则填，便于对账）</span><input v-model="createForm.letter_no" class="input" maxlength="64" /></label>
        </div>
        <label class="wb-field"><span>备注（可留空）</span><textarea v-model="createForm.note" class="textarea" rows="2" maxlength="2000" /></label>
        <label class="wb-field"><span>办理依据 / 说明</span><textarea v-model="createForm.reason" class="textarea" rows="2" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !createValid">{{ busy ? '保存中' : '登记为已报送待批复' }}</button>
      </form>
    </ActionDialog>

    <!-- ---------------------------- 回填批复 ---------------------------- -->
    <ActionDialog :open="settling !== null" title="回填上级批复结果" :busy="busy" @close="settling = null">
      <form v-if="settling" class="wb-stack" @submit.prevent="settle">
        <p>{{ settling.item_label }} · {{ settling.member_name }} · {{ settling.submitted_on }} 报 {{ settling.upper_org }}</p>
        <p class="wb-note">这里登记的是<strong>上级党组织的结论</strong>，不是系统的结论。回填不会改动党员阶段：批复「同意」后请按程序人工办理阶段流转并把批复件归入档案；批复「不同意」时系统不自动回退阶段、也不把人移出名册。</p>
        <div class="wb-actions">
          <label class="wb-check"><input v-model="settleForm.result" type="radio" value="agreed" /><span>同意 / 批准</span></label>
          <label class="wb-check"><input v-model="settleForm.result" type="radio" value="rejected" /><span>不同意</span></label>
          <label class="wb-check"><input v-model="settleForm.result" type="radio" value="supplement" /><span>需补充材料</span></label>
        </div>
        <div class="wb-grid">
          <label class="wb-field"><span>批复日期</span><input v-model="settleForm.decided_on" class="input" type="date" /></label>
          <label class="wb-field"><span>批复文号（同意 / 不同意必填）</span><input v-model="settleForm.reply_no" class="input" maxlength="64" :required="settleForm.result !== 'supplement'" /></label>
        </div>
        <label class="wb-field">
          <span>{{ settleForm.result === 'supplement' ? '还缺什么材料（必填）' : '批复说明（可留空）' }}</span>
          <textarea v-model="settleForm.decide_note" class="textarea" rows="2" maxlength="2000" />
        </label>
        <label class="wb-field"><span>办理依据 / 说明</span><textarea v-model="settleForm.reason" class="textarea" rows="2" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !settleValid">{{ busy ? '保存中' : `回填「${RESULT_LABELS[settleForm.result]}」` }}</button>
      </form>
    </ActionDialog>

    <!-- ---------------------------- 作废 ---------------------------- -->
    <ActionDialog :open="revoking !== null" title="作废本次报送" :busy="busy" @close="revoking = null">
      <form v-if="revoking" class="wb-stack" @submit.prevent="revoke">
        <p>{{ revoking.item_label }} · {{ revoking.member_name }} · {{ revoking.submitted_on }} 报 {{ revoking.upper_org }}</p>
        <p class="wb-note">作废用于事项报错或重复报送。作废后该次报送视同未发生，需要时按新记录重新登记；原记录保留可查，不会消失。</p>
        <label class="wb-field"><span>作废理由</span><textarea v-model="revokeForm.reason" class="textarea" rows="3" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || revokeForm.reason.trim() === ''">{{ busy ? '保存中' : '确认作废' }}</button>
      </form>
    </ActionDialog>
  </section>
</template>

<style scoped>
.up-summary { display: flex; flex-wrap: wrap; gap: var(--space-4); padding: var(--space-3) var(--space-4); border: var(--border); }
.up-summary__item { color: var(--ink-muted); }
.up-summary__item b { color: var(--ink); }
.up-summary__item.is-alert b { color: var(--bad-ink); }
.up-alert ul, .up-history ul { margin: 0; padding: 0 0 0 var(--space-4); display: flex; flex-direction: column; gap: var(--space-1); }
.up-history ul { list-style: none; padding-left: 0; }
.up-due { color: var(--warn-ink); font-size: var(--text-xs); }
</style>
