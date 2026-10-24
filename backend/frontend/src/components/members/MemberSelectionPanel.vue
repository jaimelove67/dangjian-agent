<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import {
  RESEARCH_METHOD_LABELS,
  memberDevelopmentApi as api,
  type LeagueRecommendation,
  type MemberSelection,
  type ResearchMethod,
  type SelectionStatus,
  type VoteSummary,
} from '@/api/member-development'
import { STAGE_LABELS, STAGE_ORDER, type MemberRosterItem } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { session } from '@/stores/session'
import { todayISO } from '@/utils/files'

/**
 * 选优结论（拟推荐名单）与团组织推优（T-MEM-13、T-MEM-06）。
 *
 * 这一屏最容易被做成"反人类"的是三件事，界面逐条绕开：
 *
 * 1. **不替组织出结论**。投票汇总只是辅助材料：界面把本轮票数摊开，供写依据与审阅时核对；
 *    名单必须由人逐人勾选、依据必须由人写清引用位置——这里没有"按票数自动生成名单"的按钮，
 *    也没有"系统建议人选"。
 * 2. **不一个人说了算**。结论走「登记 → 送审 → 第二位组织人员审核」：自己提交的版本不给
 *    审核入口（后端也拦），修订后要重新送审，全过程留痕可查。
 * 3. **不用年龄规则编数据**。名册里没有出生年月，系统判不了 28 周岁：团组织推优只登记与
 *    提示"请组织核对"，缺推优记录不阻断选优与阶段流转（否则只会逼出假日期）。
 */

const props = defineProps<{
  batchNo: string
  roundNo: number
  rows: MemberRosterItem[]
  summary: VoteSummary | null
}>()
const emit = defineEmits<{ busy: [value: boolean] }>()

const canScore = computed(() => session.can('member.scoring'))
const loading = ref(true)
const busy = ref(false)
const error = ref<unknown>(null)
const message = ref('')

const selections = ref<MemberSelection[]>([])
const selectionTotal = ref(0)
const summaryCount = ref<Record<string, number>>({})
const notice = ref('')
const boundary = ref('')
const recommendations = ref<LeagueRecommendation[]>([])
const recommendationNotice = ref('')
const ageNotice = ref('')

const picked = ref<string[]>([])
const picking = reactive<{ target_stage: string; research_method: ResearchMethod }>({
  target_stage: 'candidate',
  research_method: 'committee',
})
const form = reactive({ basis: '', research_on: todayISO(), reason: '' })

const submitting = ref<MemberSelection | null>(null)
const submitForm = reactive({ reason: '' })
const reviewing = ref<MemberSelection | null>(null)
const reviewForm = reactive({ decision: 'approved' as 'approved' | 'rejected', reason: '' })
const detailing = ref<MemberSelection | null>(null)
const editing = ref<MemberSelection | null>(null)
const editForm = reactive({
  target_stage: 'candidate',
  candidate_ids: [] as string[],
  basis: '',
  research_method: 'committee' as ResearchMethod,
  research_on: todayISO(),
  reason: '',
})
const recordingFor = ref<MemberRosterItem | null>(null)
const recordForm = reactive({
  league_org: '',
  recommended_on: todayISO(),
  note: '',
  reason: '',
})
const revoking = ref<LeagueRecommendation | null>(null)
const revokeReason = ref('')

const TARGET_STAGES = ['activist', 'candidate', 'probationary', 'member'] as const

function stageRank(stage: string): number {
  return STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number])
}

/** 拟推荐对象必须比目标阶段靠前：与后端"只能向前"同一条规则，界面先挡住明显不合规的选择。 */
function canBeCandidate(row: MemberRosterItem, targetStage: string): boolean {
  const current = stageRank(row.stage)
  const target = stageRank(targetStage)
  return current >= 0 && target >= 0 && current < target
}

function pickable(row: MemberRosterItem): boolean {
  return canBeCandidate(row, picking.target_stage)
}

/** 修订时按修订表单里的目标阶段重新算可入选范围（与后端\"只能向前\"同一条规则）。 */
const editableRows = computed(() =>
  props.rows.filter((row) => canBeCandidate(row, editForm.target_stage)),
)

const editValid = computed(
  () =>
    editForm.candidate_ids.length > 0 &&
    editForm.basis.trim() !== '' &&
    editForm.research_on !== '' &&
    editForm.reason.trim() !== '',
)

const pickedRows = computed(() =>
  picked.value
    .map((id) => props.rows.find((row) => row.id === id))
    .filter((row): row is MemberRosterItem => Boolean(row)),
)

const formValid = computed(
  () =>
    pickedRows.value.length > 0 &&
    form.basis.trim() !== '' &&
    form.research_on !== '' &&
    form.reason.trim() !== '',
)

function tallyOf(profileId: string): { agree: number; disagree: number; abstain: number } | null {
  const bucket = props.summary?.tally?.[profileId]
  if (!bucket) return null
  return { agree: bucket.agree, disagree: bucket.disagree, abstain: bucket.abstain }
}

function activeRecommendation(profileId: string): LeagueRecommendation | null {
  return recommendations.value.find((row) => row.profile_id === profileId && row.active) ?? null
}

/** 已作废的记录也要看得见：只显示"尚无推优记录"会让作废这段历史凭空消失。 */
function revokedRecommendation(profileId: string): LeagueRecommendation | null {
  return recommendations.value.find((row) => row.profile_id === profileId && !row.active) ?? null
}

function statusTone(status: SelectionStatus): string {
  if (status === 'approved') return 'badge--ok'
  if (status === 'pending') return 'badge--warn'
  if (status === 'rejected') return 'badge--bad'
  return ''
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

async function load(): Promise<void> {
  if (!props.batchNo) return
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const profileIds = props.rows.map((row) => row.id).join(',')
    const [list, recs] = await Promise.all([
      api.selections({ batch_no: props.batchNo, round_no: props.roundNo, page: 1, page_size: 50 }),
      api.leagueRecommendations({ profile_ids: profileIds, page: 1, page_size: 100 }),
    ])
    if (current !== sequence || !alive) return
    selections.value = list.items
    selectionTotal.value = list.total
    summaryCount.value = list.summary
    notice.value = list.notice
    boundary.value = list.boundary
    recommendations.value = recs.items
    recommendationNotice.value = recs.notice
    ageNotice.value = recs.age_notice
  } catch (err) {
    if (current === sequence && alive) error.value = err
  } finally {
    if (current === sequence && alive) loading.value = false
  }
}

watch(
  () => [props.batchNo, props.roundNo, props.rows.map((row) => row.id).join(',')],
  () => {
    picked.value = []
    void load()
  },
  { immediate: true },
)

function togglePick(row: MemberRosterItem, checked: boolean): void {
  if (checked) {
    if (!picked.value.includes(row.id)) picked.value = [...picked.value, row.id]
  } else {
    picked.value = picked.value.filter((id) => id !== row.id)
  }
}

async function registerSelection(): Promise<void> {
  await mutate(async () => {
    const created = await api.createSelection({
      batch_no: props.batchNo,
      round_no: props.roundNo,
      target_stage: picking.target_stage as MemberRosterItem['stage'],
      candidate_ids: pickedRows.value.map((row) => row.id),
      basis: form.basis.trim(),
      research_on: form.research_on,
      research_method: picking.research_method,
      reason: form.reason.trim(),
    })
    form.basis = ''
    form.reason = ''
    picked.value = []
    await load()
    message.value = `已登记拟推荐名单（${created.candidate_count} 人，草稿）：${created.notice}`
  })
}

function openSubmit(row: MemberSelection): void {
  error.value = null
  submitForm.reason = ''
  submitting.value = row
}

function openEdit(row: MemberSelection): void {
  error.value = null
  Object.assign(editForm, {
    target_stage: row.target_stage,
    candidate_ids: row.candidates.map((item) => item.profile_id),
    basis: row.basis,
    research_method: row.research_method,
    research_on: row.research_on,
    reason: '',
  })
  editing.value = row
}

function toggleEditPick(row: MemberRosterItem, checked: boolean): void {
  if (checked) {
    if (!editForm.candidate_ids.includes(row.id)) {
      editForm.candidate_ids = [...editForm.candidate_ids, row.id]
    }
  } else {
    editForm.candidate_ids = editForm.candidate_ids.filter((id) => id !== row.id)
  }
}

async function saveEdit(): Promise<void> {
  const target = editing.value
  if (!target) return
  await mutate(async () => {
    const done = await api.updateSelection(target.id, {
      expected_revision: target.revision,
      target_stage: editForm.target_stage as MemberRosterItem['stage'],
      candidate_ids: editForm.candidate_ids,
      basis: editForm.basis.trim(),
      research_on: editForm.research_on,
      research_method: editForm.research_method,
      reason: editForm.reason.trim(),
    })
    editing.value = null
    await load()
    message.value = `已保存第 ${done.revision} 版：修订后状态回到草稿，必须重新送审、由另一位组织人员审核。`
  })
}

async function sendForReview(): Promise<void> {
  const target = submitting.value
  if (!target) return
  await mutate(async () => {
    const done = await api.submitSelection(target.id, {
      expected_revision: target.revision,
      reason: submitForm.reason.trim(),
    })
    submitting.value = null
    await load()
    message.value = `已送另一位组织人员审核（${done.candidate_count} 人）。审核通过后才是生效结论。`
  })
}

function openReview(row: MemberSelection): void {
  error.value = null
  reviewForm.decision = 'approved'
  reviewForm.reason = ''
  reviewing.value = row
}

async function decideReview(): Promise<void> {
  const target = reviewing.value
  if (!target) return
  await mutate(async () => {
    const done = await api.reviewSelection(target.id, {
      expected_revision: target.revision,
      decision: reviewForm.decision,
      reason: reviewForm.reason.trim(),
    })
    reviewing.value = null
    await load()
    message.value = done.effective
      ? `结论已通过并生效：${done.next_step_hint}`
      : '已退回该结论：请登记人修订后重新送审。'
  })
}

async function openDetail(row: MemberSelection): Promise<void> {
  detailing.value = row
  await mutate(async () => {
    const detail = await api.selection(row.id)
    if (detailing.value?.id === row.id) detailing.value = detail
  })
}

function openRecord(row: MemberRosterItem): void {
  error.value = null
  Object.assign(recordForm, {
    league_org: '',
    recommended_on: todayISO(),
    note: '',
    reason: '',
  })
  recordingFor.value = row
}

async function saveRecommendation(): Promise<void> {
  const target = recordingFor.value
  if (!target) return
  await mutate(async () => {
    const created = await api.createLeagueRecommendation({
      profile_id: target.id,
      league_org: recordForm.league_org.trim(),
      recommended_on: recordForm.recommended_on,
      note: recordForm.note.trim(),
      reason: recordForm.reason.trim(),
    })
    recordingFor.value = null
    await load()
    message.value = `已登记团组织推优：${created.member_name} · ${created.league_org}。${created.age_notice}`
  })
}

function openRevoke(row: LeagueRecommendation): void {
  error.value = null
  revokeReason.value = ''
  revoking.value = row
}

async function revokeRecommendation(): Promise<void> {
  const target = revoking.value
  if (!target) return
  await mutate(async () => {
    await api.revokeLeagueRecommendation(target.id, { reason: revokeReason.value.trim() })
    revoking.value = null
    await load()
    message.value = '该条推优记录已作废：记录保留可查，作废不影响选优与阶段流转。'
  })
}

function refresh(): void {
  void load()
}

defineExpose({ refresh })
</script>

<template>
  <section class="wb-stack sp-panel" :aria-busy="busy || loading">
    <p class="wb-note">
      选优结论是<strong>拟推荐名单</strong>，由组织人员登记、<strong>第二位组织人员审核</strong>后才生效：
      自己提交的版本没有审核入口，修订后要重新送审。投票汇总是辅助材料，界面把它摊开供核对，
      系统<strong>不按票数自动排序、不自动产生名单、不自动定等次</strong>；结论生效也不自动改阶段、
      不自动向上级报送（报送走上级审批 / 备案台账，由人登记）。
    </p>
    <p class="wb-note">
      团组织推优只登记事实（推荐团组织 / 推荐日期 / 推优说明）。{{ ageNotice }}。
      名册里没有出生年月，系统判不了 28 周岁，请组织核对。
    </p>

    <ErrorState
      v-if="error && !submitting && !reviewing && !recordingFor && !revoking && !editing"
      :error="error"
    />
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>
    <p v-if="!batchNo" class="wb-empty">请先选择批次：选优结论按批次与轮次归集。</p>

    <LoadingBlock v-else-if="loading" variant="table" :rows="3" />
    <template v-else>
      <div class="wb-table-wrap">
        <table class="wb-table">
          <thead>
            <tr>
              <th>培养对象</th>
              <th>当前阶段</th>
              <th>团组织推优</th>
              <th>拟推荐名单</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>{{ row.name }}</td>
              <td>{{ STAGE_LABELS[row.stage] }}</td>
              <td>
                <template v-if="activeRecommendation(row.id)">
                  <span>{{ activeRecommendation(row.id)!.league_org }}</span>
                  <p class="u-meta">
                    {{ activeRecommendation(row.id)!.recommended_on }} · 已记录
                    <template v-if="activeRecommendation(row.id)!.note">
                      ：{{ activeRecommendation(row.id)!.note }}
                    </template>
                  </p>
                </template>
                <template v-else-if="revokedRecommendation(row.id)">
                  <span class="u-meta"
                    >原有记录已作废（{{ revokedRecommendation(row.id)!.recommended_on }} ·
                    {{ revokedRecommendation(row.id)!.league_org }}）</span
                  >
                </template>
                <span v-else class="u-meta">尚无推优记录（不阻断选优，请组织核对是否为 28 周岁以下青年）</span>
              </td>
              <td>
                <label v-if="canScore" class="wb-check">
                  <input
                    type="checkbox"
                    :checked="picked.includes(row.id)"
                    :disabled="busy || !pickable(row)"
                    :aria-label="`${row.name}纳入拟推荐名单`"
                    @change="togglePick(row, ($event.target as HTMLInputElement).checked)"
                  />
                  <span>{{ pickable(row) ? '纳入' : '阶段已到 / 已过' }}</span>
                </label>
                <span v-else class="u-meta">—</span>
              </td>
              <td>
                <template v-if="canScore">
                  <button
                    v-if="!activeRecommendation(row.id)"
                    class="btn btn--quiet btn--sm"
                    type="button"
                    :disabled="busy"
                    @click="openRecord(row)"
                  >
                    登记推优
                  </button>
                  <button
                    v-else
                    class="btn btn--quiet btn--sm"
                    type="button"
                    :disabled="busy"
                    @click="openRevoke(activeRecommendation(row.id)!)"
                  >
                    作废推优
                  </button>
                </template>
                <span v-else class="u-meta">—</span>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="5" class="u-meta">该批次暂无可访问的培养对象。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <section v-if="canScore" class="wb-section wb-stack">
        <h3>登记本轮拟推荐名单</h3>
        <div class="wb-grid">
          <label class="wb-field"
            ><span>拟推进阶段</span
            ><select v-model="picking.target_stage" class="select" :disabled="busy">
              <option v-for="stage in TARGET_STAGES" :key="stage" :value="stage">
                {{ STAGE_LABELS[stage] }}
              </option>
            </select></label
          ><label class="wb-field"
            ><span>研究程序</span
            ><select v-model="picking.research_method" class="select" :disabled="busy">
              <option v-for="(label, key) in RESEARCH_METHOD_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          ><label class="wb-field"
            ><span>研究日期</span
            ><input v-model="form.research_on" class="input" type="date" :disabled="busy"
          /></label>
        </div>
        <div v-if="pickedRows.length" class="sp-basis">
          <p class="u-meta">本轮辅助材料（无记名汇总，仅供核对，不构成结论）：</p>
          <ul>
            <li v-for="row in pickedRows" :key="row.id">
              {{ row.name }}：<template v-if="tallyOf(row.id)"
                >同意 {{ tallyOf(row.id)!.agree }} / 不同意 {{ tallyOf(row.id)!.disagree }} / 弃权
                {{ tallyOf(row.id)!.abstain }}</template
              ><template v-else>本轮暂无投票记录</template>
            </li>
          </ul>
          <p v-if="summary" class="u-meta">本轮共 {{ summary.voter_count }} 人次参与记录（无记名）。</p>
        </div>
        <label class="wb-field"
          ><span>结论依据（必须写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录）</span
          ><textarea
            v-model="form.basis"
            class="textarea"
            rows="2"
            maxlength="2000"
            :disabled="busy"
            required
        /></label>
        <label class="wb-field"
          ><span>办理依据 / 说明</span
          ><textarea
            v-model="form.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            :disabled="busy"
            required
        /></label>
        <div class="wb-actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="busy || !formValid"
            @click="registerSelection"
          >
            登记拟推荐名单（{{ pickedRows.length }}）
          </button>
        </div>
      </section>

      <section class="wb-section wb-stack">
        <div class="wb-toolbar">
          <h3>本轮选优结论（{{ selectionTotal }}）</h3>
          <div class="wb-actions">
            <span v-if="summaryCount.draft" class="badge">草稿 {{ summaryCount.draft }}</span>
            <span v-if="summaryCount.pending" class="badge badge--warn"
              >待审核 {{ summaryCount.pending }}</span
            >
            <span v-if="summaryCount.approved" class="badge badge--ok"
              >已通过 {{ summaryCount.approved }}</span
            >
            <span v-if="summaryCount.rejected" class="badge badge--bad"
              >已退回 {{ summaryCount.rejected }}</span
            >
            <button class="btn btn--quiet btn--sm" type="button" :disabled="busy || loading" @click="refresh">
              刷新结论
            </button>
          </div>
        </div>
        <div v-if="selections.length" class="wb-table-wrap">
          <table class="wb-table">
            <thead>
              <tr>
                <th>拟推进阶段</th>
                <th>拟推荐名单</th>
                <th>依据与程序</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in selections" :key="row.id">
                <td>
                  {{ row.target_stage_label }}
                  <p class="u-meta">{{ row.org_name }}</p>
                </td>
                <td>
                  {{ row.candidate_count }} 人
                  <p class="u-meta">
                    {{ row.candidates.map((item) => item.member_name).join('、') || '—' }}
                  </p>
                </td>
                <td>
                  {{ row.basis }}
                  <p class="u-meta">
                    {{ row.research_method_label }} · {{ row.research_on }} · 第 {{ row.revision }} 版
                  </p>
                  <p v-if="row.review_comment" class="u-meta">审核意见：{{ row.review_comment }}</p>
                  <p v-if="row.effective" class="u-meta">{{ row.next_step_hint }}</p>
                </td>
                <td>
                  <span class="badge" :class="statusTone(row.review_status)">{{
                    row.review_status_label
                  }}</span>
                  <p v-if="row.reviewed_by" class="u-meta">审核人 {{ row.reviewed_by }}</p>
                </td>
                <td class="sp-actions">
                  <button
                    v-if="canScore && (row.review_status === 'draft' || row.review_status === 'rejected')"
                    class="btn btn--primary btn--sm"
                    type="button"
                    :disabled="busy"
                    @click="openSubmit(row)"
                  >
                    送审
                  </button>
                  <button
                    v-if="canScore && (row.review_status === 'draft' || row.review_status === 'rejected')"
                    class="btn btn--quiet btn--sm"
                    type="button"
                    :disabled="busy"
                    @click="openEdit(row)"
                  >
                    修订名单与依据
                  </button>
                  <button
                    v-if="row.can_review"
                    class="btn btn--primary btn--sm"
                    type="button"
                    :disabled="busy"
                    @click="openReview(row)"
                  >
                    审核
                  </button>
                  <button class="btn btn--quiet btn--sm" type="button" :disabled="busy" @click="openDetail(row)">
                    明细与留痕
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="wb-empty">
          本轮还没有登记拟推荐名单。名单与依据由人填写——系统不会按票数自动生成。
        </p>
        <p v-if="notice" class="u-meta">{{ notice }}</p>
        <p v-if="boundary" class="u-meta">{{ boundary }}</p>
        <p v-if="recommendationNotice" class="u-meta">{{ recommendationNotice }}</p>
      </section>
    </template>

    <!-- 修订（修订后必须重新送审） -->
    <ActionDialog
      :open="editing !== null"
      title="修订拟推荐名单与依据"
      :busy="busy"
      wide
      @close="editing = null"
      ><form v-if="editing" class="wb-stack" @submit.prevent="saveEdit">
        <p class="wb-note">
          修订会保存为新版本并<strong>回到草稿</strong>：原来审核通过的版本已经留痕，改完必须重新送审、由另一位组织人员审核。
        </p>
        <div class="wb-grid">
          <label class="wb-field"
            ><span>拟推进阶段</span
            ><select v-model="editForm.target_stage" class="select" :disabled="busy">
              <option v-for="stage in TARGET_STAGES" :key="stage" :value="stage">
                {{ STAGE_LABELS[stage] }}
              </option>
            </select></label
          ><label class="wb-field"
            ><span>研究程序</span
            ><select v-model="editForm.research_method" class="select" :disabled="busy">
              <option v-for="(label, key) in RESEARCH_METHOD_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          ><label class="wb-field"
            ><span>研究日期</span
            ><input v-model="editForm.research_on" class="input" type="date" :disabled="busy"
          /></label>
        </div>
        <div class="wb-field">
          <span>拟推荐名单（当前阶段不早于目标阶段的人不列出）</span>
          <label v-for="row in editableRows" :key="row.id" class="sp-check">
            <input
              type="checkbox"
              :checked="editForm.candidate_ids.includes(row.id)"
              :disabled="busy"
              :aria-label="`修订名单：${row.name}`"
              @change="toggleEditPick(row, ($event.target as HTMLInputElement).checked)"
            />
            <span>{{ row.name }}（{{ STAGE_LABELS[row.stage] }}）</span>
          </label>
          <p v-if="!editableRows.length" class="u-meta">
            当前目标阶段下没有可登记的对象：请在名册里核对人员阶段。
          </p>
        </div>
        <label class="wb-field"
          ><span>结论依据</span
          ><textarea
            v-model="editForm.basis"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
        /></label>
        <label class="wb-field"
          ><span>修订理由</span
          ><textarea
            v-model="editForm.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
        /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !editValid">保存修订</button>
      </form></ActionDialog
    >

    <!-- 送审 -->
    <ActionDialog
      :open="submitting !== null"
      title="送另一位组织人员审核"
      :busy="busy"
      @close="submitting = null"
      ><form v-if="submitting" class="wb-stack" @submit.prevent="sendForReview">
        <p>{{ submitting.target_stage_label }} · {{ submitting.candidate_count }} 人</p>
        <p class="wb-note">
          送审后由<strong>另一位</strong>组织人员审核：你自己不能审核自己的版本；审核通过才是生效结论。
        </p>
        <label class="wb-field"
          ><span>送审说明</span
          ><textarea
            v-model="submitForm.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
        /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !submitForm.reason.trim()">
          提交审核
        </button>
      </form></ActionDialog
    >

    <!-- 审核 -->
    <ActionDialog :open="reviewing !== null" title="审核选优结论" :busy="busy" @close="reviewing = null"
      ><form v-if="reviewing" class="wb-stack" @submit.prevent="decideReview">
        <p>{{ reviewing.target_stage_label }} · {{ reviewing.candidate_count }} 人 · {{ reviewing.basis }}</p>
        <p class="u-meta">
          拟推荐名单：{{ reviewing.candidates.map((item) => item.member_name).join('、') || '—' }}
        </p>
        <p v-if="reviewing.advisories?.length" class="u-meta">
          {{ reviewing.advisories.join('；') }}
        </p>
        <label class="wb-field"
          ><span>审核结果</span
          ><select v-model="reviewForm.decision" class="select" required>
            <option value="approved">通过（成为生效结论）</option>
            <option value="rejected">退回登记人修订</option>
          </select></label
        >
        <label class="wb-field"
          ><span>审核意见</span
          ><textarea
            v-model="reviewForm.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
        /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !reviewForm.reason.trim()">
          提交审核结果
        </button>
      </form></ActionDialog
    >

    <!-- 明细与留痕 -->
    <ActionDialog
      :open="detailing !== null"
      title="选优结论明细与留痕"
      :busy="busy"
      wide
      @close="detailing = null"
      ><div v-if="detailing" class="wb-stack">
        <p>
          {{ detailing.target_stage_label }} ·
          {{ detailing.candidates.map((item) => item.member_name).join('、') }}
        </p>
        <p>依据：{{ detailing.basis }}</p>
        <p class="u-meta">
          {{ detailing.research_method_label }} · {{ detailing.research_on }} ·
          {{ detailing.review_status_label }} · 第 {{ detailing.revision }} 版
        </p>
        <section v-if="detailing.evidence" class="wb-section">
          <h4>{{ detailing.evidence.evidence_note || '依据快照' }}</h4>
          <p class="u-meta">
            无记名汇总：本轮共 {{ detailing.evidence.voter_count }} 人次参与记录。
          </p>
          <ul>
            <li v-for="item in detailing.candidates" :key="item.profile_id">
              {{ item.member_name }}：<template v-if="detailing.evidence.tally[item.profile_id]"
                >同意 {{ detailing.evidence.tally[item.profile_id]!.agree }} / 不同意
                {{ detailing.evidence.tally[item.profile_id]!.disagree }} / 弃权
                {{ detailing.evidence.tally[item.profile_id]!.abstain }}</template
              ><template v-else>本轮暂无投票记录</template>
            </li>
          </ul>
        </section>
        <section v-if="detailing.missing?.length" class="wb-section">
          <h4>送审前还需要补</h4>
          <ul>
            <li v-for="text in detailing.missing" :key="text">{{ text }}</li>
          </ul>
        </section>
        <section v-if="detailing.advisories?.length" class="wb-section">
          <h4>提示（不阻断）</h4>
          <ul>
            <li v-for="text in detailing.advisories" :key="text">{{ text }}</li>
          </ul>
        </section>
        <section class="wb-section">
          <h4>只追加留痕（{{ detailing.revisions?.length ?? 0 }} 版）</h4>
          <ul>
            <li v-for="item in detailing.revisions" :key="item.revision">
              第 {{ item.revision }} 版 · {{ item.action }} · 操作人 {{ item.actor_id }}
              <p class="u-meta">{{ item.reason || '未填写理由' }}</p>
            </li>
          </ul>
        </section>
        <p class="wb-note">{{ detailing.boundary }}</p>
      </div></ActionDialog
    >

    <!-- 登记团组织推优 -->
    <ActionDialog
      :open="recordingFor !== null"
      title="登记团组织推优"
      :busy="busy"
      @close="recordingFor = null"
      ><form v-if="recordingFor" class="wb-stack" @submit.prevent="saveRecommendation">
        <p>{{ recordingFor.name }} · {{ STAGE_LABELS[recordingFor.stage] }}</p>
        <p class="wb-note">
          {{ ageNotice }}。只需如实登记推优事实；缺这条记录不会阻断选优与阶段流转。
        </p>
        <div class="wb-grid">
          <label class="wb-field"
            ><span>推荐团组织</span
            ><input v-model="recordForm.league_org" class="input" maxlength="200" required
          /></label>
          <label class="wb-field"
            ><span>推荐日期</span
            ><input v-model="recordForm.recommended_on" class="input" type="date" required
          /></label>
        </div>
        <label class="wb-field"
          ><span>推优说明（团组织意见，第三人信息按密级收敛）</span
          ><textarea v-model="recordForm.note" class="textarea" rows="2" maxlength="5000"
        /></label>
        <label class="wb-field"
          ><span>办理依据 / 说明</span
          ><textarea
            v-model="recordForm.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
        /></label>
        <ErrorState v-if="error" :error="error" />
        <button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !recordForm.league_org.trim() || !recordForm.reason.trim()"
        >
          登记推优记录
        </button>
      </form></ActionDialog
    >

    <!-- 作废推优 -->
    <ActionDialog
      :open="revoking !== null"
      title="作废团组织推优记录"
      :busy="busy"
      @close="revoking = null"
      ><form v-if="revoking" class="wb-stack" @submit.prevent="revokeRecommendation">
        <p>{{ revoking.member_name }} · {{ revoking.league_org }} · {{ revoking.recommended_on }}</p>
        <p class="wb-note">作废后视同未发生（例如推荐单位填错、材料未办成），记录保留可查。</p>
        <label class="wb-field"
          ><span>作废理由</span
          ><textarea v-model="revokeReason" class="textarea" rows="2" maxlength="2000" required
        /></label>
        <ErrorState v-if="error" :error="error" />
        <button class="btn btn--primary" type="submit" :disabled="busy || !revokeReason.trim()">
          作废该记录
        </button>
      </form></ActionDialog
    >
  </section>
</template>

<style scoped>
.sp-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.sp-basis ul {
  margin: 0;
  padding-left: 1.2em;
}
.sp-check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: normal;
}
</style>
