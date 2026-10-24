<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { ApiError } from '@/api/http'
import { listMembers } from '@/api/member'
import {
  REMINDER_LABELS,
  memberDevelopmentApi as api,
  type MemberBatch,
  type MemberReminder,
  type VoteSummary,
} from '@/api/member-development'
import { STAGE_LABELS, type MemberOrgOption, type MemberRosterItem } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import MemberFilePanel from './MemberFilePanel.vue'
import MemberSelectionPanel from './MemberSelectionPanel.vue'
import { session } from '@/stores/session'
import { todayISO } from '@/utils/files'

const props = defineProps<{ mode: string; organizations: MemberOrgOption[] }>()
const emit = defineEmits<{ selectBatch: [year: number, batch: string]; busy: [value: boolean] }>()
const canManage = computed(() => session.can('member.stage_transition'))
const canScore = computed(() => session.can('member.scoring'))
const loading = ref(false)
const busy = ref(false)
const profileBusy = ref(false)
const selectionBusy = ref(false)
const selectionPanel = ref<InstanceType<typeof MemberSelectionPanel> | null>(null)
watch([busy, profileBusy, selectionBusy], () => emit('busy', busy.value || profileBusy.value || selectionBusy.value))
const error = ref<unknown>(null)
const message = ref('')
const year = ref(new Date().getFullYear())
const page = ref(1)
const total = ref(0)
const batches = ref<MemberBatch[]>([])
const reminders = ref<MemberReminder[]>([])
const reminderStatus = ref('open')
const selectedProfile = ref('')
const batchOpen = ref(false)
const batch = reactive({ batch_no: '', label: '', org_unit_id: '', reason: '' })
const resolving = ref<MemberReminder | null>(null)
const resolution = reactive({ status: 'closed' as 'closed' | 'skipped', note: '' })
const voteBatch = ref('')
const round = ref(1)
const votePage = ref(1)
const voteTotal = ref(0)
const voteRows = ref<MemberRosterItem[]>([])
const choices = reactive<
  Record<string, { vote: '' | 'agree' | 'disagree' | 'abstain'; comment: string; name: string }>
>({})
const summary = ref<VoteSummary | null>(null)
const votingOpen = ref(false)
const confirmed = ref(false)
const recordedRounds = reactive(new Set<string>())
const voteLabels = { agree: '同意', disagree: '不同意', abstain: '弃权' }
const ballot = computed(() =>
  Object.entries(choices)
    .filter(([, entry]) => entry.vote !== '')
    .map(([profile_id, entry]) => ({
      profile_id,
      vote: entry.vote as 'agree' | 'disagree' | 'abstain',
      comment: entry.comment,
      name: entry.name,
    })),
)
const alreadyVoted = computed(
  () =>
    recordedRounds.has(`${voteBatch.value}:${round.value}`) ||
    Object.values(summary.value?.tally ?? {}).some((entry) => entry.voted_by_me),
)
let sequence = 0
let voteSequence = 0
let alive = true
const validYear = () => Number.isInteger(year.value) && year.value >= 2000 && year.value <= 2100

async function load(): Promise<void> {
  if (props.mode !== 'reminders' && !validYear()) return
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const result =
      props.mode === 'reminders'
        ? await api.reminders({
            status: reminderStatus.value || undefined,
            page: page.value,
            page_size: 20,
          })
        : await api.batches({ year: year.value, page: page.value, page_size: 20 })
    if (current !== sequence || !alive) return
    total.value = result.total
    if (props.mode === 'reminders') reminders.value = result.items as MemberReminder[]
    else batches.value = result.items as MemberBatch[]
  } catch (err) {
    if (current === sequence && alive) error.value = err
  } finally {
    if (current === sequence && alive) loading.value = false
  }
}
watch(
  () => props.mode,
  () => {
    page.value = 1
    message.value = ''
    selectedProfile.value = ''
    void load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  alive = false
  sequence += 1
  voteSequence += 1
})

async function mutate(fn: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = null
  message.value = ''
  try {
    await fn()
  } catch (err) {
    error.value = err
  } finally {
    busy.value = false
  }
}
async function createBatch(): Promise<void> {
  await mutate(async () => {
    await api.createBatch({
      year: year.value,
      ...batch,
      batch_no: batch.batch_no.trim(),
      label: batch.label.trim(),
      reason: batch.reason.trim(),
    })
    batchOpen.value = false
    Object.assign(batch, { batch_no: '', label: '', reason: '' })
    await load()
    message.value = '年度批次已建立，可在人员档案中分配归属。'
  })
}
function openBatch(): void {
  batch.org_unit_id =
    props.organizations.find((org) => org.id === session.state.user?.org_unit_id)?.id ??
    props.organizations[0]?.id ??
    ''
  error.value = null
  batchOpen.value = true
}
async function resolve(): Promise<void> {
  if (!resolving.value) return
  const id = resolving.value.id
  await mutate(async () => {
    await api.resolveReminder(id, { status: resolution.status, note: resolution.note.trim() })
    resolving.value = null
    await load()
    message.value = '提醒处理结果已保存。'
  })
}
function openReminder(item: MemberReminder): void {
  error.value = null
  resolving.value = item
  Object.assign(resolution, { status: 'closed', note: '' })
}
function changeReminderStatus(): void {
  page.value = 1
  void load()
}
function changePage(delta: number): void {
  page.value += delta
  void load()
}
function changeVotePage(delta: number): void {
  votePage.value += delta
  void loadVotes()
}
function startVoteReview(): void {
  error.value = null
  confirmed.value = false
  votingOpen.value = true
}

async function loadVotes(): Promise<void> {
  if (
    !voteBatch.value ||
    !validYear() ||
    !Number.isInteger(round.value) ||
    round.value < 1 ||
    round.value > 20
  )
    return
  const current = ++voteSequence
  loading.value = true
  error.value = null
  try {
    const [roster, result] = await Promise.all([
      listMembers({
        year: year.value,
        batch_no: voteBatch.value,
        page: votePage.value,
        page_size: 40,
      }),
      api.voteSummary(voteBatch.value, round.value),
    ])
    if (current !== voteSequence || !alive) return
    voteRows.value = roster.items
    voteTotal.value = roster.total
    summary.value = result
    for (const row of roster.items) choices[row.id] ??= { vote: '', comment: '', name: row.name }
  } catch (err) {
    if (current === voteSequence && alive) error.value = err
  } finally {
    if (current === voteSequence && alive) loading.value = false
  }
}
function resetVote(): void {
  for (const id of Object.keys(choices)) delete choices[id]
  summary.value = null
  voteRows.value = []
  votePage.value = 1
  void loadVotes()
}
watch([voteBatch, round], resetVote)

/**
 * 工作区刷新：多轮选优这一屏既要重取投票汇总，也要重取选优结论与团组织推优台账
 * （结论可能在另一位组织人员那边刚审核过）。
 */
async function refreshWorkspace(): Promise<void> {
  if (props.mode === 'votes' && voteBatch.value) {
    await loadVotes()
    selectionPanel.value?.refresh()
    return
  }
  await load()
}
function changeYear(): void {
  page.value = 1
  voteBatch.value = ''
  resetVote()
  void load()
}
async function submitVotes(): Promise<void> {
  if (!confirmed.value || !ballot.value.length || ballot.value.length > 200) return
  const body = {
    batch_no: voteBatch.value,
    round_no: round.value,
    votes: ballot.value.map(({ profile_id, vote, comment }) => ({
      profile_id,
      vote,
      comment: comment.trim(),
    })),
  }
  await mutate(async () => {
    if (body.votes.some((entry) => !entry.vote)) throw new ApiError('请填写本轮选择。', 42201)
    const result = await api.submitVotes(body)
    recordedRounds.add(`${body.batch_no}:${body.round_no}`)
    votingOpen.value = false
    confirmed.value = false
    await loadVotes()
    message.value = `已保存 ${result.recorded} 条本轮投票记录，汇总不自动形成选拔结论。`
  })
}
</script>

<template>
  <section class="wb wb-stack" :aria-busy="busy || loading">
    <div class="wb-toolbar">
      <div class="wb-actions">
        <label v-if="mode !== 'reminders'" class="wb-field"
          ><span>年度</span
          ><input
            v-model.number="year"
            class="input"
            type="number"
            min="2000"
            max="2100"
            :disabled="busy"
            @change="changeYear"
        /></label>
        <label v-else class="wb-field"
          ><span>提醒状态</span
          ><select
            v-model="reminderStatus"
            class="select"
            :disabled="busy"
            @change="changeReminderStatus"
          >
            <option value="open">待处理</option>
            <option value="closed">已完成</option>
            <option value="skipped">已跳过</option>
            <option value="">全部</option>
          </select></label
        >
      </div>
      <button
        v-if="mode === 'batches' && canManage"
        class="btn btn--primary"
        type="button"
        :disabled="busy"
        @click="openBatch"
      >
        建立年度批次
      </button>
      <button
        class="btn btn--quiet"
        type="button"
        :disabled="loading || busy"
        @click="refreshWorkspace"
      >
        刷新
      </button>
    </div>
    <ErrorState v-if="error && !batchOpen && !resolving && !votingOpen" :error="error" />
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>
    <LoadingBlock v-if="loading" variant="table" :rows="4" />
    <template v-if="mode === 'batches' && !loading">
      <p class="u-meta">
        批次及人数按当前组织权限查询。建立批次后，在人员档案中登记年度和批次归属。
      </p>
      <div v-if="batches.length" class="wb-table-wrap">
        <table class="wb-table">
          <thead>
            <tr>
              <th>批次名称</th>
              <th>批次号</th>
              <th>所属组织</th>
              <th>人数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in batches" :key="item.id">
              <td>{{ item.label }}</td>
              <td>{{ item.batch_no }}</td>
              <td>{{ item.org_name }}</td>
              <td>{{ item.member_count }}</td>
              <td>
                <button
                  type="button"
                  class="btn btn--ghost btn--sm"
                  @click="emit('selectBatch', item.year, item.batch_no)"
                >
                  查看批次人员
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!error" class="wb-empty">本年度尚无可访问的批次。</p>
    </template>
    <template v-else-if="mode === 'reminders' && !loading">
      <div v-if="reminders.length" class="wb-table-wrap">
        <table class="wb-table">
          <thead>
            <tr>
              <th>提醒事项</th>
              <th>培养对象</th>
              <th>截止日期</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in reminders" :key="item.id">
              <td>{{ REMINDER_LABELS[item.kind] || item.kind }}</td>
              <td>
                <button
                  class="btn btn--quiet btn--sm"
                  type="button"
                  @click="selectedProfile = item.profile_id"
                >
                  查看对象档案
                </button>
                <p class="u-meta">编号 {{ item.profile_id.slice(0, 8) }}</p>
              </td>
              <td>
                {{ item.due_on }}
                <p v-if="item.status === 'open' && item.due_on < todayISO()" class="field__error">
                  已逾期
                </p>
              </td>
              <td>
                {{
                  item.status === 'open' ? '待处理' : item.status === 'closed' ? '已完成' : '已跳过'
                }}
                <p v-if="item.note" class="u-meta">{{ item.note }}</p>
              </td>
              <td>
                <button
                  v-if="canManage && item.status === 'open'"
                  class="btn btn--ghost btn--sm"
                  type="button"
                  :disabled="busy"
                  @click="openReminder(item)"
                >
                  登记处理
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!error" class="wb-empty">
        当前状态下没有提醒。可在人员档案的人工流转页同步阶段提醒。
      </p>
    </template>
    <div v-else-if="mode === 'votes'" class="wb-stack">
      <p class="wb-note">
        多轮记录用于组织人员选优参考。同一账号每轮只能提交一次；票数和评分均不自动形成组织认定。投票按批次号与轮次归集，跨年度选优请使用不同批次号。
      </p>
      <div class="wb-grid">
        <label class="wb-field"
          ><span>本年度批次</span
          ><select v-model="voteBatch" class="select" :disabled="busy || loading">
            <option value="">请选择批次</option>
            <option v-for="item in batches" :key="item.id" :value="item.batch_no">
              {{ item.label }}（{{ item.batch_no }}）
            </option>
          </select></label
        ><label class="wb-field"
          ><span>投票轮次</span
          ><input
            v-model.number="round"
            class="input"
            type="number"
            min="1"
            max="20"
            :disabled="busy || loading"
        /></label>
      </div>
      <template v-if="voteBatch && !loading"
        ><p v-if="alreadyVoted" class="wb-note">当前账号已提交本轮记录，可以查看汇总。</p>
        <div v-if="voteRows.length" class="wb-table-wrap">
          <table class="wb-table">
            <thead>
              <tr>
                <th>培养对象</th>
                <th>当前阶段</th>
                <th v-if="canScore && !alreadyVoted">本轮选择</th>
                <th v-if="canScore && !alreadyVoted">说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in voteRows" :key="item.id">
                <td>{{ item.name }}</td>
                <td>{{ STAGE_LABELS[item.stage] }}</td>
                <td v-if="canScore && !alreadyVoted">
                  <select
                    v-model="choices[item.id]!.vote"
                    class="select"
                    :aria-label="`${item.name}的本轮选择`"
                  >
                    <option value="">暂不纳入</option>
                    <option value="agree">同意</option>
                    <option value="disagree">不同意</option>
                    <option value="abstain">弃权</option>
                  </select>
                </td>
                <td v-if="canScore && !alreadyVoted">
                  <input
                    v-model="choices[item.id]!.comment"
                    class="input"
                    :aria-label="`${item.name}的投票说明`"
                    maxlength="500"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="!error" class="wb-empty">该批次暂无可访问的培养对象。</p>
        <div v-if="voteTotal > 40" class="wb-pager">
          <button
            class="btn btn--ghost"
            type="button"
            :disabled="votePage <= 1 || busy"
            @click="changeVotePage(-1)"
          >
            上一页人员</button
          ><span>第 {{ votePage }} 页，共 {{ voteTotal }} 人</span
          ><button
            class="btn btn--ghost"
            type="button"
            :disabled="votePage * 40 >= voteTotal || busy"
            @click="changeVotePage(1)"
          >
            下一页人员
          </button>
        </div>
        <div v-if="canScore && !alreadyVoted" class="wb-actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="busy || !ballot.length || ballot.length > 200"
            @click="startVoteReview"
          >
            核对本轮记录（{{ ballot.length }}）
          </button>
        </div>
        <section v-if="summary" class="wb-section wb-stack">
          <div class="wb-toolbar">
            <h3>本轮汇总</h3>
            <span class="u-meta">{{ summary.voter_count }} 人参与记录</span>
          </div>
          <p>{{ summary.note }}</p>
          <div v-if="Object.keys(summary.tally).length" class="wb-table-wrap">
            <table class="wb-table">
              <thead>
                <tr>
                  <th>培养对象</th>
                  <th>同意</th>
                  <th>不同意</th>
                  <th>弃权</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(entry, id) in summary.tally" :key="id">
                  <td>{{ choices[id]?.name || `对象编号 ${String(id).slice(0, 8)}` }}</td>
                  <td>{{ entry.agree }}</td>
                  <td>{{ entry.disagree }}</td>
                  <td>{{ entry.abstain }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="u-meta">本轮尚无记录。</p>
        </section>
        <MemberSelectionPanel
          ref="selectionPanel"
          :batch-no="voteBatch"
          :round-no="round"
          :rows="voteRows"
          :summary="summary"
          @busy="selectionBusy = $event"
        />
      </template>
    </div>
    <div v-if="!loading && total > 20" class="wb-pager">
      <button
        class="btn btn--ghost"
        type="button"
        :disabled="page <= 1 || busy"
        @click="changePage(-1)"
      >
        上一页{{ mode === 'votes' ? '批次' : '' }}</button
      ><span>第 {{ page }} 页，共 {{ total }} 项</span
      ><button
        class="btn btn--ghost"
        type="button"
        :disabled="page * 20 >= total || busy"
        @click="changePage(1)"
      >
        下一页{{ mode === 'votes' ? '批次' : '' }}
      </button>
    </div>
    <ActionDialog :open="batchOpen" title="建立年度发展批次" :busy="busy" @close="batchOpen = false"
      ><form class="wb-stack" @submit.prevent="createBatch">
        <p>{{ year }} 年度</p>
        <label class="wb-field"
          ><span>批次号</span
          ><input v-model="batch.batch_no" class="input" maxlength="20" required /></label
        ><label class="wb-field"
          ><span>批次名称</span
          ><input v-model="batch.label" class="input" maxlength="100" required /></label
        ><label class="wb-field"
          ><span>所属组织</span
          ><select v-model="batch.org_unit_id" class="select" required>
            <option value="">请选择有效组织</option>
            <option v-for="org in organizations" :key="org.id" :value="org.id">
              {{ org.name }}
            </option>
          </select></label
        ><label class="wb-field"
          ><span>建立理由</span
          ><textarea
            v-model="batch.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
          /></label
        ><ErrorState v-if="error" :error="error" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !batch.org_unit_id || !batch.reason.trim()"
        >
          保存年度批次
        </button>
      </form></ActionDialog
    >
    <ActionDialog
      :open="resolving !== null"
      title="登记提醒处理结果"
      :busy="busy"
      @close="resolving = null"
      ><form class="wb-stack" @submit.prevent="resolve">
        <p>{{ resolving ? REMINDER_LABELS[resolving.kind] || resolving.kind : '' }}</p>
        <label class="wb-field"
          ><span>处理结果</span
          ><select v-model="resolution.status" class="select">
            <option value="closed">已完成</option>
            <option value="skipped">依规跳过</option>
          </select></label
        ><label class="wb-field"
          ><span>处理说明</span
          ><textarea
            v-model="resolution.note"
            class="textarea"
            rows="3"
            maxlength="500"
            required
          /></label
        ><ErrorState v-if="error" :error="error" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !resolution.note.trim()"
        >
          保存处理结果
        </button>
      </form></ActionDialog
    >
    <ActionDialog
      :open="votingOpen"
      title="核对本轮投票记录"
      :busy="busy"
      @close="votingOpen = false"
      ><form class="wb-stack" @submit.prevent="submitVotes">
        <p>{{ voteBatch }}批次 / 第 {{ round }} 轮</p>
        <p v-for="entry in ballot" :key="entry.profile_id">
          {{ entry.name }}：{{ voteLabels[entry.vote]
          }}{{ entry.comment ? `（${entry.comment}）` : '' }}
        </p>
        <label class="wb-check"
          ><input
            v-model="confirmed"
            type="checkbox"
            required
          />我已逐项核对，同意提交本轮记录。提交后本账号不可重复投票。</label
        ><ErrorState v-if="error" :error="error" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !confirmed"
        >
          提交本轮记录
        </button>
      </form></ActionDialog
    >
    <ActionDialog
      :open="!!selectedProfile"
      title="培养对象办理档案"
      wide
      :busy="profileBusy"
      @close="selectedProfile = ''"
      ><MemberFilePanel
        v-if="selectedProfile"
        :key="selectedProfile"
        :profile-id="selectedProfile"
        @busy="profileBusy = $event"
    /></ActionDialog>
  </section>
</template>
