<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { listMembers } from '@/api/member'
import {
  memberTransferApi as api,
  type MemberTransferRecord,
  type TransferSummary,
} from '@/api/member-transfer'
import { RELATION_STATUS_LABELS, type MemberOrgOption, type MemberRosterItem, type RelationStatus } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { session } from '@/stores/session'
import { todayISO } from '@/utils/files'

/**
 * 组织关系接转（T-MEM-14）。
 *
 * 这一屏最容易被做成"反人类"的三件事，版面专门让开：
 *   1. 转出**不是删除**，也不是阶段流转——正式党员转出后仍是正式党员，所以没有"推进阶段"入口；
 *   2. 开了介绍信**不等于转出完成**：状态停在"待接收"，按钮文案与提示都写清"要等回执"，
 *      到期未回执只提示核实，不自动判定失败；
 *   3. 转入**不用重录一遍**：校内支部之间调动直接关联现有档案，只有从外单位转入才新建档案，
 *      并按阶段列出要核对的档案清单（缺项只提示，不阻断登记）。
 *
 * 已转出的档案不在名册默认名单内，但接转台账仍可查——历史不许因为"人不在了"就消失。
 */

const props = defineProps<{ organizations: MemberOrgOption[] }>()
const emit = defineEmits<{ busy: [value: boolean]; changed: [] }>()

const canManage = computed(() => session.can('member.stage_transition'))
const loading = ref(true)
const busy = ref(false)
const error = ref<unknown>(null)
const message = ref('')

const direction = ref<'' | 'in' | 'out'>('')
const status = ref<'' | 'pending' | 'settled' | 'revoked'>('')
const overdueOnly = ref(false)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const records = ref<MemberTransferRecord[]>([])
const summary = ref<TransferSummary | null>(null)
const notice = ref('')

const candidates = ref<MemberRosterItem[]>([])
const candidateTotal = ref(0)
const candidateFilter = ref('')
const historyOpen = ref<string | null>(null)

const outOpen = ref(false)
const incoming = ref<MemberTransferRecord | null>(null)
const inOpen = ref(false)
const settling = ref<MemberTransferRecord | null>(null)
const revoking = ref<MemberTransferRecord | null>(null)

const outForm = reactive({ profile_id: '', counterpart_org: '', letter_no: '', issued_on: todayISO(), valid_until: '', note: '', reason: '' })
const inForm = reactive({
  mode: 'link' as 'link' | 'new',
  profile_id: '', name: '', current_stage: 'member' as 'probationary' | 'member',
  stage_joined_on: '', org_unit_id: '',
  counterpart_org: '', letter_no: '', issued_on: todayISO(), valid_until: '', note: '', reason: '',
})
const settleForm = reactive({ settled_on: todayISO(), receipt_no: '', note: '', reason: '' })
const revokeForm = reactive({ reason: '' })

/** 只有预备党员与正式党员有"组织关系"可接转；培养对象转的是培养材料。 */
const transferable = computed(() => candidates.value.filter((item) => item.stage === 'probationary' || item.stage === 'member'))
const visibleCandidates = computed(() => {
  const keyword = candidateFilter.value.trim()
  if (!keyword) return transferable.value
  return transferable.value.filter((item) => item.name.includes(keyword))
})
/** 转出只对"在册"的人办理；已在转出途中或已转出的人应该先办回执 / 走转入。 */
const outCandidates = computed(() => visibleCandidates.value.filter((item) => (item.relation_status ?? 'in_place') === 'in_place'))
/** 转入可关联"在册"或"已转出"的档案：后者正是"关系转回本校"的常见情形。 */
const inCandidates = computed(() => visibleCandidates.value.filter((item) => (item.relation_status ?? 'in_place') !== 'out_pending'))

const outValid = computed(() => outForm.profile_id !== '' && outForm.counterpart_org.trim() !== '' && outForm.letter_no.trim() !== '' && outForm.issued_on !== '' && outForm.reason.trim() !== '')
const inValid = computed(() => {
  const letter = inForm.counterpart_org.trim() !== '' && inForm.letter_no.trim() !== '' && inForm.issued_on !== '' && inForm.reason.trim() !== ''
  if (!letter) return false
  if (inForm.mode === 'link') return inForm.profile_id !== '' && inForm.org_unit_id !== ''
  return inForm.name.trim() !== '' && inForm.stage_joined_on !== '' && inForm.org_unit_id !== ''
})

function label(status?: RelationStatus): string {
  return RELATION_STATUS_LABELS[status ?? 'in_place']
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
    candidateTotal.value = data.total
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
      direction: direction.value || undefined,
      status: status.value || undefined,
      overdue: overdueOnly.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    if (current !== sequence || !alive) return
    records.value = data.items
    total.value = data.total
    summary.value = data.summary
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

function openOut(): void {
  error.value = null
  Object.assign(outForm, { profile_id: '', counterpart_org: '', letter_no: '', issued_on: todayISO(), valid_until: '', note: '', reason: '' })
  void loadCandidates()
  outOpen.value = true
}

function openIn(): void {
  error.value = null
  incoming.value = null
  Object.assign(inForm, {
    mode: 'link', profile_id: '', name: '', current_stage: 'member', stage_joined_on: '',
    org_unit_id: props.organizations[0]?.id ?? '', counterpart_org: '', letter_no: '',
    issued_on: todayISO(), valid_until: '', note: '', reason: '',
  })
  void loadCandidates()
  inOpen.value = true
}

/** 选定要关联的档案后，默认把关系落回他原来的组织（也可以改成校内另一个组织）。 */
function pickLinkedProfile(): void {
  const item = candidates.value.find((row) => row.id === inForm.profile_id)
  if (item?.org_unit_id) inForm.org_unit_id = item.org_unit_id
}

async function createOut(): Promise<void> {
  await mutate(async () => {
    const created = await api.create({
      direction: 'out',
      profile_id: outForm.profile_id,
      counterpart_org: outForm.counterpart_org.trim(),
      letter_no: outForm.letter_no.trim(),
      issued_on: outForm.issued_on,
      ...(outForm.valid_until ? { valid_until: outForm.valid_until } : {}),
      note: outForm.note.trim(),
      reason: outForm.reason.trim(),
    })
    outOpen.value = false
    await load()
    void loadCandidates()
    // 名册按组织关系状态过滤：接转一变，名册里这条人就得跟着变，不能等用户手动刷新
    emit('changed')
    message.value = `已登记转出：介绍信 ${created.letter_no} 状态为「${created.status_label}」。${created.notice ?? ''}`
  })
}

async function createIn(): Promise<void> {
  await mutate(async () => {
    const created = await api.create({
      direction: 'in',
      ...(inForm.mode === 'link'
        ? { profile_id: inForm.profile_id }
        : { name: inForm.name.trim(), current_stage: inForm.current_stage, stage_joined_on: inForm.stage_joined_on }),
      org_unit_id: inForm.org_unit_id,
      counterpart_org: inForm.counterpart_org.trim(),
      letter_no: inForm.letter_no.trim(),
      issued_on: inForm.issued_on,
      ...(inForm.valid_until ? { valid_until: inForm.valid_until } : {}),
      note: inForm.note.trim(),
      reason: inForm.reason.trim(),
    })
    inOpen.value = false
    incoming.value = created
    await load()
    void loadCandidates()
    emit('changed')
    message.value = `已登记转入。${created.notice ?? ''}`
  })
}

function openSettle(row: MemberTransferRecord): void {
  error.value = null
  Object.assign(settleForm, { settled_on: todayISO(), receipt_no: '', note: '', reason: '' })
  settling.value = row
}

async function settle(): Promise<void> {
  const target = settling.value
  if (!target) return
  await mutate(async () => {
    const done = await api.settle(target.id, {
      settled_on: settleForm.settled_on,
      receipt_no: settleForm.receipt_no.trim(),
      note: settleForm.note.trim(),
      reason: settleForm.reason.trim(),
    })
    settling.value = null
    await load()
    void loadCandidates()
    emit('changed')
    message.value = done.notice ?? '回执已登记。'
  })
}

function openRevoke(row: MemberTransferRecord): void {
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
    void loadCandidates()
    emit('changed')
    message.value = done.notice ?? '接转已作废。'
  })
}

function openHistory(row: MemberTransferRecord): void {
  historyOpen.value = historyOpen.value === row.id ? null : row.id
  if (historyOpen.value !== row.id || row.history) return
  void mutate(async () => {
    const detail = await api.detail(row.id)
    const index = records.value.findIndex((item) => item.id === row.id)
    if (index >= 0) records.value[index] = { ...records.value[index]!, history: detail.history ?? [] }
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
      组织关系接转只登记事实——介绍信要素、对方组织与回执。<strong>转出开了介绍信不等于转出完成</strong>：本人持介绍信到新组织报到、
      收到回执后才算转出，中途一律显示"待接收"；超过介绍信有效期仍未回执只提示核实，系统不自动判定失败，也不自动把关系挂到新组织。
      转入按党员所处阶段列出要核对的档案清单，缺项只提示、可后补，不阻断登记。对方组织的联系人与电话不登记：接转只需要组织名称与介绍信要素。
    </p>

    <div v-if="summary" class="tr-summary">
      <span class="tr-summary__item"><b>{{ summary.pending_out }}</b> 转出待回执</span>
      <span class="tr-summary__item"><b>{{ summary.pending_in }}</b> 转入待核对</span>
      <span class="tr-summary__item" :class="{ 'is-alert': summary.overdue > 0 }"><b>{{ summary.overdue }}</b> 已超过有效期</span>
      <span class="tr-summary__item"><b>{{ summary.this_year_out }}</b> 本年度转出</span>
      <span class="tr-summary__item"><b>{{ summary.this_year_in }}</b> 本年度转入</span>
    </div>

    <div class="wb-toolbar">
      <div class="wb-actions">
        <label class="wb-field"><span>方向</span>
          <select v-model="direction" class="select" :disabled="loading || busy" @change="reload">
            <option value="">全部</option>
            <option value="out">转出</option>
            <option value="in">转入</option>
          </select>
        </label>
        <label class="wb-field"><span>状态</span>
          <select v-model="status" class="select" :disabled="loading || busy" @change="reload">
            <option value="">全部</option>
            <option value="pending">待接收（未回执）</option>
            <option value="settled">已接收（已回执）</option>
            <option value="revoked">已作废</option>
          </select>
        </label>
        <label class="wb-check"><input v-model="overdueOnly" type="checkbox" :disabled="loading || busy" @change="reload" /><span>只看已超过有效期</span></label>
      </div>
      <template v-if="canManage">
        <button class="btn btn--primary" type="button" :disabled="busy" @click="openOut">登记转出</button>
        <button class="btn btn--primary" type="button" :disabled="busy" @click="openIn">登记转入</button>
      </template>
      <button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="reload">刷新</button>
    </div>

    <ErrorState v-if="error && !outOpen && !inOpen && !settling && !revoking" :error="error" />
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>

    <section v-if="overdueRows.length" class="wb-section tr-alert">
      <h3>需要人工核实（{{ overdueRows.length }}）</h3>
      <ul>
        <li v-for="row in overdueRows" :key="row.id">{{ row.member_name }}：{{ row.overdue_notice }}</li>
      </ul>
      <p class="u-meta">以上仅为提示，处理结果以组织核实为准。</p>
    </section>

    <section v-if="incoming" class="wb-section wb-stack">
      <h3>转入登记结果</h3>
      <p>{{ incoming.member_name }}（{{ incoming.stage_label }}）{{ incoming.created_profile ? '已新建档案' : '已关联现有档案' }}，组织关系状态：{{ incoming.state_label }}。</p>
      <template v-if="incoming.archive">
        <p>档案清单按该党员所处阶段生成，共 {{ incoming.archive.required.length }} 项，其中尚缺 {{ incoming.archive.missing.length }} 项：</p>
        <ul v-if="incoming.archive.missing.length">
          <li v-for="item in incoming.archive.missing" :key="item">{{ item }}</li>
        </ul>
        <p v-else class="u-meta">清单内材料均已登记。</p>
        <p class="u-meta">缺项不影响本次登记，可在人员档案中逐项补齐后再回来登记回执。</p>
      </template>
    </section>

    <LoadingBlock v-if="loading" variant="table" :rows="4" />
    <div v-else-if="records.length" class="wb-table-wrap">
      <table class="wb-table">
        <thead>
          <tr>
            <th>方向</th><th>党员</th><th>阶段</th><th>对方组织</th><th>介绍信</th><th>开具日期</th><th>有效期至</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in records" :key="row.id">
            <tr>
              <td>{{ row.direction_label }}</td>
              <td>{{ row.member_name }}<p class="u-meta">{{ row.org_name }}</p></td>
              <td>{{ row.stage_label || '—' }}</td>
              <td>{{ row.counterpart_org }}</td>
              <td>{{ row.letter_no }}<p v-if="row.receipt_no" class="u-meta">回执 {{ row.receipt_no }}</p></td>
              <td>{{ row.issued_on }}</td>
              <td>
                {{ row.valid_until }}
                <p v-if="row.overdue" class="field__error">已超过有效期 {{ -row.days_left }} 天</p>
                <p v-else-if="row.status === 'pending'" class="u-meta">剩余 {{ row.days_left }} 天</p>
              </td>
              <td>
                <span class="badge" :class="row.status === 'pending' ? 'badge--warn' : row.status === 'settled' ? 'badge--ok' : ''">{{ row.status_label }}</span>
                <p class="u-meta">{{ row.issued_on.slice(0, 4) }} 年 · {{ row.state_label }}</p>
              </td>
              <td>
                <button v-if="canManage && row.status === 'pending'" class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="openSettle(row)">
                  {{ row.direction === 'out' ? '登记回执（完成转出）' : '登记回执（档案已核对）' }}
                </button>
                <button v-if="canManage && row.status !== 'revoked'" class="btn btn--quiet btn--sm" type="button" :disabled="busy" @click="openRevoke(row)">作废</button>
                <button class="btn btn--quiet btn--sm" type="button" :disabled="busy" @click="openHistory(row)">
                  {{ historyOpen === row.id ? '收起留痕' : '留痕' }}
                </button>
              </td>
            </tr>
            <tr v-if="historyOpen === row.id" class="tr-history">
              <td colspan="9">
                <p v-if="!row.history" class="u-meta">读取留痕中…</p>
                <ul v-else>
                  <li v-for="item in row.history" :key="`${row.id}-${item.revision}`">
                    第 {{ item.revision }} 版 · {{ formatStamp(item.created_at) }} · 操作人 {{ item.actor_id }} · {{ item.action }}
                    <p class="u-meta">{{ item.reason || '未填写理由' }}</p>
                  </li>
                </ul>
                <p v-if="row.revoked_on" class="u-meta">作废于 {{ row.revoked_on }}：{{ row.revoke_reason }}</p>
                <p v-if="row.note" class="u-meta">备注：{{ row.note }}</p>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <p v-else-if="!error" class="wb-empty">当前筛选下没有接转记录。已转出的人员不在名册默认名单内，但台账始终可查。</p>

    <p v-if="notice" class="u-meta">{{ notice }}</p>

    <div v-if="!loading && total > pageSize" class="wb-pager">
      <button class="btn btn--ghost" type="button" :disabled="page <= 1 || busy" @click="turnPage(-1)">上一页</button>
      <span>第 {{ page }} 页，共 {{ total }} 条</span>
      <button class="btn btn--ghost" type="button" :disabled="page * pageSize >= total || busy" @click="turnPage(1)">下一页</button>
    </div>

    <!-- ---------------------------- 登记转出 ---------------------------- -->
    <ActionDialog :open="outOpen" title="登记组织关系转出" :busy="busy" wide @close="outOpen = false">
      <form class="wb-stack" @submit.prevent="createOut">
        <p class="wb-note">登记后状态为「待接收」：本人持介绍信到对方组织报到、收到回执后才算转出完成。此操作不会改动党员的当前阶段。</p>
        <label class="wb-field"><span>姓名筛选（可留空）</span><input v-model="candidateFilter" class="input" maxlength="50" placeholder="输入姓名缩小范围" /></label>
        <label class="wb-field"><span>转出党员（预备党员 / 正式党员）</span>
          <select v-model="outForm.profile_id" class="select" required>
            <option value="">请选择在册党员</option>
            <option v-for="item in outCandidates" :key="item.id" :value="item.id">{{ item.name }}（{{ item.org_name }}）</option>
          </select>
        </label>
        <p v-if="!outCandidates.length" class="u-meta">没有可办理转出的在册党员。若此人关系已在转出途中，请先登记回执或作废；若已转出，请改走转入。</p>
        <p v-else-if="candidateTotal > candidates.length" class="u-meta">仅列出前 {{ candidates.length }} 名（共 {{ candidateTotal }} 名），可用姓名筛选。</p>
        <div class="wb-grid">
          <label class="wb-field"><span>接收组织名称（介绍信抬头）</span><input v-model="outForm.counterpart_org" class="input" maxlength="200" required /></label>
          <label class="wb-field"><span>介绍信编号</span><input v-model="outForm.letter_no" class="input" maxlength="64" required /></label>
          <label class="wb-field"><span>开具日期</span><input v-model="outForm.issued_on" class="input" type="date" required /></label>
          <label class="wb-field"><span>有效期至（留空按配置默认天数）</span><input v-model="outForm.valid_until" class="input" type="date" /></label>
        </div>
        <label class="wb-field"><span>备注（可留空）</span><textarea v-model="outForm.note" class="textarea" rows="2" maxlength="2000" /></label>
        <label class="wb-field"><span>办理依据 / 说明</span><textarea v-model="outForm.reason" class="textarea" rows="2" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !outValid">{{ busy ? '保存中' : '登记为待接收' }}</button>
      </form>
    </ActionDialog>

    <!-- ---------------------------- 登记转入 ---------------------------- -->
    <ActionDialog :open="inOpen" title="登记组织关系转入" :busy="busy" wide @close="inOpen = false">
      <form class="wb-stack" @submit.prevent="createIn">
        <p class="wb-note">校内支部之间调动请选「关联现有档案」，档案不会重复；从外单位转入才新建档案。转入后即可按档案清单核对本人档案。</p>
        <div class="wb-actions">
          <label class="wb-check"><input v-model="inForm.mode" type="radio" value="link" /><span>关联现有档案（校内支部之间调整 / 关系转回）</span></label>
          <label class="wb-check"><input v-model="inForm.mode" type="radio" value="new" /><span>新建档案（从外单位转入）</span></label>
        </div>
        <label class="wb-field"><span>姓名筛选（可留空）</span><input v-model="candidateFilter" class="input" maxlength="50" placeholder="输入姓名缩小范围" /></label>
        <template v-if="inForm.mode === 'link'">
          <label class="wb-field"><span>关联的档案（预备党员 / 正式党员）</span>
            <select v-model="inForm.profile_id" class="select" required @change="pickLinkedProfile">
              <option value="">请选择档案</option>
              <option v-for="item in inCandidates" :key="item.id" :value="item.id">
                {{ item.name }}（{{ item.org_name }} · {{ label(item.relation_status) }}）
              </option>
            </select>
          </label>
          <p v-if="!inCandidates.length" class="u-meta">没有可关联的档案。若此人关系正在转出途中，请先登记回执或作废本次转出。</p>
        </template>
        <template v-else>
          <div class="wb-grid">
            <label class="wb-field"><span>姓名</span><input v-model="inForm.name" class="input" maxlength="50" required /></label>
            <label class="wb-field"><span>当前阶段</span>
              <select v-model="inForm.current_stage" class="select">
                <option value="probationary">预备党员</option>
                <option value="member">正式党员</option>
              </select>
            </label>
            <label class="wb-field"><span>进入该阶段日期</span><input v-model="inForm.stage_joined_on" class="input" type="date" required /></label>
          </div>
        </template>
        <div class="wb-grid">
          <label class="wb-field"><span>接收组织（本组织侧）</span>
            <select v-model="inForm.org_unit_id" class="select" required>
              <option value="">请选择组织</option>
              <option v-for="org in organizations" :key="org.id" :value="org.id">{{ org.name }}</option>
            </select>
          </label>
          <label class="wb-field"><span>原组织名称（介绍信来历）</span><input v-model="inForm.counterpart_org" class="input" maxlength="200" required /></label>
          <label class="wb-field"><span>介绍信编号</span><input v-model="inForm.letter_no" class="input" maxlength="64" required /></label>
          <label class="wb-field"><span>开具日期</span><input v-model="inForm.issued_on" class="input" type="date" required /></label>
          <label class="wb-field"><span>有效期至（留空按配置默认天数）</span><input v-model="inForm.valid_until" class="input" type="date" /></label>
        </div>
        <label class="wb-field"><span>备注（可留空）</span><textarea v-model="inForm.note" class="textarea" rows="2" maxlength="2000" /></label>
        <label class="wb-field"><span>办理依据 / 说明</span><textarea v-model="inForm.reason" class="textarea" rows="2" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !inValid">{{ busy ? '保存中' : '登记转入并生成档案清单' }}</button>
      </form>
    </ActionDialog>

    <!-- ---------------------------- 登记回执 ---------------------------- -->
    <ActionDialog :open="settling !== null" title="登记接转回执" :busy="busy" @close="settling = null">
      <form v-if="settling" class="wb-stack" @submit.prevent="settle">
        <p>{{ settling.direction_label }} · {{ settling.member_name }} · 介绍信 {{ settling.letter_no }}</p>
        <p class="wb-note">
          {{ settling.direction === 'out'
            ? '收到接收组织回执后登记：登记完成即视为本次转出办结，该党员不再计入本组织在册名单与应评议名单。'
            : '档案核对完成后登记：人已在本组织在册，回执只表示核对办结，缺项仍可在档案中补齐。' }}
        </p>
        <div class="wb-grid">
          <label class="wb-field"><span>回执日期</span><input v-model="settleForm.settled_on" class="input" type="date" /></label>
          <label class="wb-field"><span>回执编号（可留空）</span><input v-model="settleForm.receipt_no" class="input" maxlength="64" /></label>
        </div>
        <label class="wb-field"><span>说明（可留空）</span><textarea v-model="settleForm.note" class="textarea" rows="2" maxlength="2000" /></label>
        <label class="wb-field"><span>办理依据 / 说明</span><textarea v-model="settleForm.reason" class="textarea" rows="2" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || settleForm.reason.trim() === ''">{{ busy ? '保存中' : '确认登记回执' }}</button>
      </form>
    </ActionDialog>

    <!-- ---------------------------- 作废 ---------------------------- -->
    <ActionDialog :open="revoking !== null" title="作废本次接转" :busy="busy" @close="revoking = null">
      <form v-if="revoking" class="wb-stack" @submit.prevent="revoke">
        <p>{{ revoking.direction_label }} · {{ revoking.member_name }} · 介绍信 {{ revoking.letter_no }}</p>
        <p class="wb-note">作废用于介绍信开错、未办成或回执录错。作废后该次接转视同未发生，组织关系状态按其余有效记录重新推导；记录本身保留可查，不会消失。</p>
        <label class="wb-field"><span>作废理由</span><textarea v-model="revokeForm.reason" class="textarea" rows="3" maxlength="2000" required /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || revokeForm.reason.trim() === ''">{{ busy ? '保存中' : '确认作废' }}</button>
      </form>
    </ActionDialog>
  </section>
</template>

<style scoped>
.tr-summary { display: flex; flex-wrap: wrap; gap: var(--space-4); padding: var(--space-3) var(--space-4); border: var(--border); }
.tr-summary__item { color: var(--ink-muted); }
.tr-summary__item b { color: var(--ink); }
.tr-summary__item.is-alert b { color: var(--bad-ink); }
.tr-alert ul, .tr-history ul { margin: 0; padding-left: var(--space-4); }
.tr-history td { background: var(--paper-sunken); }
</style>
