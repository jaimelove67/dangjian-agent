<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  GRADE_LABELS,
  memberReviewApi,
  type MemberReviewAttention,
  type MemberReviewDetail,
  type MemberReviewTarget,
  type MemberReviewWorkspace,
  type Organization,
  type ReviewGrade,
} from '@/api/meeting'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'

/**
 * 民主评议党员工作区（模块3 / T-ORG-11）。
 *
 * 一条 = 一个年度 × 一名党员。页面先给"应评议名单与进度"，再逐个录入程序与等次；
 * 录入后必须由**另一位**有审核权的人员审核通过才生效。审核按钮由后端按"这一条是不是
 * 本人提交、本人有没有审核权"逐行给出（``can_review``），前端不自己猜——否则会出现
 * 一点必然报 403 的按钮。
 */

const props = defineProps<{
  year: number
  orgUnitId: string
  orgs: Organization[]
  canManage: boolean
}>()

const STATUS_LABELS: Record<string, string> = {
  not_started: '未发起',
  draft: '草稿',
  pending: '待审核',
  approved: '已通过',
  rejected: '已退回',
}

const workspace = ref<MemberReviewWorkspace | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref<unknown>(null)
const actionError = ref<unknown>(null)
const message = ref('')
const dialog = ref<'record' | 'launch' | 'decision' | ''>('')
const editing = ref<MemberReviewTarget | null>(null)
const detail = ref<MemberReviewDetail | null>(null)
const currentId = ref('')
const currentRevision = ref(0)

const branchOrgs = computed(() => props.orgs.filter((org) => org.org_type === 'branch'))
const readonly = computed(() => !props.canManage)
const gradeOptions = computed(() => workspace.value?.grade_options ?? [])
const recordTitle = computed(() => {
  const name = editing.value?.member_name || ''
  if (readonly.value) return `${name} 的民主评议结果`
  return `${editing.value?.review_id ? '修订' : '录入'}${name} 的民主评议`
})

const form = reactive({
  self_assessment: '',
  peer_review: '',
  branch_opinion: '',
  eligible: '',
  attended: '',
  outstanding: '',
  qualified: '',
  basic: '',
  unqualified: '',
  grade: '' as ReviewGrade | '',
  basis: '',
  rectification: '',
  reason: '',
})

const launchForm = reactive({ org_unit_id: '', reason: '' })
const decisionForm = reactive({ decision: 'approved' as 'approved' | 'rejected', reason: '' })

function gradeClass(grade: string): string {
  if (grade === 'outstanding') return 'badge badge--ok'
  if (grade === 'unqualified') return 'badge badge--bad'
  if (grade === 'basic') return 'badge badge--warn'
  return 'badge'
}

function statusClass(status: string): string {
  if (status === 'approved') return 'badge badge--ok'
  if (status === 'rejected') return 'badge badge--bad'
  if (status === 'pending') return 'badge badge--warn'
  return 'badge'
}

function numberOrNull(value: string): number | null {
  return value.trim() === '' ? null : Number(value)
}

function loadForm(data: MemberReviewDetail | null): void {
  const procedure = data?.procedure ?? {}
  const test = procedure.test ?? null
  form.self_assessment = procedure.self_assessment ?? ''
  form.peer_review = procedure.peer_review ?? ''
  form.branch_opinion = procedure.branch_opinion ?? ''
  form.eligible = test ? String(test.eligible) : ''
  form.attended = test ? String(test.attended) : ''
  form.outstanding = test ? String(test.outstanding) : ''
  form.qualified = test ? String(test.qualified) : ''
  form.basic = test ? String(test.basic) : ''
  form.unqualified = test ? String(test.unqualified) : ''
  form.grade = (data?.grade as ReviewGrade | undefined) || ''
  form.basis = data?.basis ?? ''
  form.rectification = data?.rectification ?? ''
  form.reason = ''
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    workspace.value = await memberReviewApi.workspace({
      year: props.year,
      org_unit_id: props.orgUnitId || undefined,
    })
  } catch (err) {
    error.value = err
  } finally {
    loading.value = false
  }
}

function reload(): Promise<void> {
  return load()
}
defineExpose({ reload })

watch([() => props.year, () => props.orgUnitId], () => {
  void load()
})
onMounted(load)

async function openRecord(target: MemberReviewTarget, mode: 'record' | 'decision'): Promise<void> {
  editing.value = target
  detail.value = null
  currentId.value = target.review_id || ''
  currentRevision.value = target.revision
  actionError.value = null
  message.value = ''
  decisionForm.decision = 'approved'
  decisionForm.reason = ''
  if (target.review_id) {
    busy.value = true
    try {
      const data = await memberReviewApi.detail(target.review_id)
      detail.value = data
      currentId.value = data.id
      currentRevision.value = data.revision
      loadForm(data)
    } catch (err) {
      actionError.value = err
      return
    } finally {
      busy.value = false
    }
  } else {
    loadForm(null)
  }
  dialog.value = mode
}

function openAttention(item: MemberReviewAttention): void {
  const target = workspace.value?.targets.find((row) => row.review_id === item.review_id)
  if (target) void openRecord(target, 'record')
}

function startLaunch(): void {
  actionError.value = null
  message.value = ''
  const chosen = branchOrgs.value.find((org) => org.id === props.orgUnitId)
  launchForm.org_unit_id = chosen
    ? chosen.id
    : branchOrgs.value.length === 1
      ? branchOrgs.value[0].id
      : ''
  launchForm.reason = ''
  dialog.value = 'launch'
}

function procedurePayload() {
  const counts = {
    eligible: numberOrNull(form.eligible),
    attended: numberOrNull(form.attended),
    outstanding: numberOrNull(form.outstanding),
    qualified: numberOrNull(form.qualified),
    basic: numberOrNull(form.basic),
    unqualified: numberOrNull(form.unqualified),
  }
  const hasTest = Object.values(counts).some((value) => value !== null)
  return {
    self_assessment: form.self_assessment,
    peer_review: form.peer_review,
    branch_opinion: form.branch_opinion,
    test: hasTest
      ? {
          eligible: counts.eligible ?? 0,
          attended: counts.attended ?? 0,
          outstanding: counts.outstanding ?? 0,
          qualified: counts.qualified ?? 0,
          basic: counts.basic ?? 0,
          unqualified: counts.unqualified ?? 0,
        }
      : null,
  }
}

async function save(andSubmit: boolean): Promise<void> {
  if (!editing.value) return
  busy.value = true
  actionError.value = null
  try {
    const reason = form.reason.trim() || (andSubmit ? '录入完成并送审' : '录入评议草稿')
    const payload = {
      procedure: procedurePayload(),
      grade: form.grade || null,
      basis: form.basis,
      rectification: form.rectification,
      reason,
    }
    const name = editing.value.member_name
    if (!currentId.value) {
      const created = await memberReviewApi.create({
        year: props.year,
        profile_id: editing.value.profile_id,
        ...payload,
      })
      currentId.value = created.id
      currentRevision.value = created.revision
    } else {
      const updated = await memberReviewApi.update(currentId.value, {
        expected_revision: currentRevision.value,
        ...payload,
      })
      currentRevision.value = updated.revision
    }
    if (andSubmit) {
      await memberReviewApi.submit(currentId.value, {
        expected_revision: currentRevision.value,
        reason,
      })
      message.value = `${name} 的评议已送审，需由另一位有权限的人员审核后生效。`
    } else {
      message.value = `${name} 的评议草稿已保存。`
    }
    dialog.value = ''
    await load()
  } catch (err) {
    actionError.value = err
  } finally {
    busy.value = false
  }
}

async function launch(): Promise<void> {
  busy.value = true
  actionError.value = null
  try {
    const result = await memberReviewApi.launch({
      year: props.year,
      org_unit_id: launchForm.org_unit_id,
      reason: launchForm.reason.trim() || `按年度发起 ${props.year} 年民主评议`,
    })
    message.value = `已发起：新建 ${result.created} 条草稿，跳过 ${result.skipped} 条已有记录（共 ${result.target_total} 名在册党员）。`
    dialog.value = ''
    await load()
  } catch (err) {
    actionError.value = err
  } finally {
    busy.value = false
  }
}

async function decide(): Promise<void> {
  if (!editing.value || !currentId.value) return
  busy.value = true
  actionError.value = null
  try {
    await memberReviewApi.review(currentId.value, {
      expected_revision: currentRevision.value,
      decision: decisionForm.decision,
      reason: decisionForm.reason.trim(),
    })
    message.value =
      decisionForm.decision === 'approved'
        ? `${editing.value.member_name} 的评议已通过人工审核并生效，可在本人档案与考核中复用。`
        : `${editing.value.member_name} 的评议已退回，请录入人修订后重新送审。`
    dialog.value = ''
    await load()
  } catch (err) {
    actionError.value = err
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="review wb-stack">
    <div class="wb-toolbar">
      <div>
        <h2>{{ year }} 年度民主评议党员</h2>
        <p class="u-meta">
          一般每年开展 1 次，按个人自评、党员互评、民主测评的程序进行；等次由人工审定，
          系统不按票数排名、不自动定等次。
        </p>
      </div>
      <div class="review__actions">
        <button
          v-if="canManage"
          class="btn btn--primary"
          type="button"
          :disabled="busy || !branchOrgs.length"
          @click="startLaunch"
        >
          按年度发起
        </button>
        <button class="btn btn--quiet" type="button" :disabled="loading || busy" @click="load">
          刷新
        </button>
      </div>
    </div>
    <p v-if="!branchOrgs.length" class="wb-note">
      当前账号可访问的组织里没有支部。民主评议党员按支部开展，请联系管理员补充支部或调整数据范围。
    </p>
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>
    <ErrorState v-if="error" :error="error"
      ><button class="btn btn--ghost" type="button" @click="load">重新加载</button></ErrorState
    >
    <LoadingBlock v-if="loading" variant="table" :rows="4" />
    <template v-else-if="workspace">
      <dl class="wb-facts">
        <div>
          <dt>应评议党员</dt>
          <dd>{{ workspace.target_total }}</dd>
        </div>
        <div>
          <dt>已发起</dt>
          <dd>{{ workspace.progress.launched }}</dd>
          <span class="u-meta">未发起 {{ workspace.progress.not_started }}</span>
        </div>
        <div>
          <dt>已通过审核</dt>
          <dd>{{ workspace.progress.approved }}</dd>
          <span class="u-meta"
            >草稿 {{ workspace.progress.draft }} / 待审核 {{ workspace.progress.pending }} / 已退回
            {{ workspace.progress.rejected }}</span
          >
        </div>
        <div>
          <dt>等次分布（已通过）</dt>
          <dd>
            <span v-for="(label, key) in GRADE_LABELS" :key="key" class="review__grade">
              {{ label }} {{ workspace.grades[key] ?? 0 }}
            </span>
          </dd>
        </div>
      </dl>
      <p class="wb-note">
        优秀 {{ workspace.outstanding }} 人，占应评议 {{ workspace.outstanding_ratio }}%。
        {{ workspace.notices.outstanding_notice }}
      </p>
      <p v-if="workspace.advisory_count" class="wb-note">
        有 {{ workspace.advisory_count }} 人的党员互评意见或民主测评票数尚未登记（不阻断送审，可事后补充）。
      </p>
      <p v-for="item in workspace.missing" :key="item" class="field__error">{{ item }}</p>
      <div class="wb-table-wrap review__list">
        <table class="wb-table">
          <thead>
            <tr>
              <th>党员</th>
              <th>阶段</th>
              <th>评议状态</th>
              <th>等次</th>
              <th>缺项与提示</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in workspace.targets"
              :key="item.profile_id || item.review_id || item.member_name"
            >
              <td>
                <strong>{{ item.member_name }}</strong>
                <p class="u-meta">
                  {{ item.org_name }}<template v-if="!item.in_roster">（已不在在册名单）</template>
                </p>
              </td>
              <td>{{ item.stage_label || '—' }}</td>
              <td>
                <span :class="statusClass(item.review_status)">
                  {{ STATUS_LABELS[item.review_status] || item.review_status }}
                </span>
              </td>
              <td>
                <span v-if="item.grade_label" :class="gradeClass(item.grade)">
                  {{ item.grade_label }}
                </span>
                <span v-else class="u-meta">—</span>
              </td>
              <td>
                <p v-for="text in item.missing" :key="text" class="field__error">{{ text }}</p>
                <p v-for="text in item.advisories" :key="text" class="u-meta">{{ text }}</p>
                <span v-if="!item.missing.length && !item.advisories.length" class="u-meta">—</span>
              </td>
              <td>
                <button
                  class="btn btn--ghost btn--sm"
                  type="button"
                  :disabled="busy"
                  @click="openRecord(item, 'record')"
                >
                  {{ item.review_id ? (readonly ? '查看' : '录入/修订') : '录入评议' }}
                </button>
                <button
                  v-if="item.can_review"
                  class="btn btn--primary btn--sm"
                  type="button"
                  :disabled="busy"
                  @click="openRecord(item, 'decision')"
                >
                  审核
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!workspace.targets.length" class="wb-empty">
        没有需要评议的党员。在册的正式党员与预备党员会自动出现在这里。
      </p>
      <section v-if="workspace.attention.length" class="wb-section wb-stack">
        <h3>需按党章党规研究处置（{{ workspace.attention.length }}）</h3>
        <p class="wb-note">{{ workspace.notices.unqualified_notice }}</p>
        <ul>
          <li v-for="item in workspace.attention" :key="item.review_id">
            {{ item.org_name }} / {{ item.member_name }}：{{ item.grade_label }}
            <p v-if="item.rectification" class="u-meta">已提出的整改要求：{{ item.rectification }}</p>
            <button
              class="btn btn--quiet btn--sm"
              type="button"
              :disabled="busy"
              @click="openAttention(item)"
            >
              查看评议记录
            </button>
          </li>
        </ul>
      </section>
      <p class="u-meta">{{ workspace.notices.feedback_notice }}</p>
      <p class="u-meta">{{ workspace.boundary }}</p>
    </template>

    <ActionDialog
      :open="dialog === 'launch'"
      title="按年度发起民主评议党员"
      :busy="busy"
      @close="dialog = ''"
      ><form class="wb-stack" @submit.prevent="launch">
        <p class="wb-note">
          将为本支部在册的正式党员与预备党员建立 {{ year }} 年度评议草稿；已有记录的党员会被跳过，
          不会覆盖已录入的内容。
        </p>
        <label class="wb-field"
          ><span>支部</span
          ><select v-model="launchForm.org_unit_id" class="select" required>
            <option value="" disabled>请选择支部</option>
            <option v-for="org in branchOrgs" :key="org.id" :value="org.id">{{ org.name }}</option>
          </select></label
        >
        <label class="wb-field"
          ><span>发起理由</span
          ><input v-model="launchForm.reason" class="input" maxlength="2000" required
        /></label>
        <ErrorState v-if="actionError" :error="actionError" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !launchForm.org_unit_id || !launchForm.reason.trim()"
        >
          确认发起
        </button>
      </form></ActionDialog
    >

    <ActionDialog
      :open="dialog === 'record'"
      :title="recordTitle"
      :busy="busy"
      wide
      @close="dialog = ''"
      ><form class="wb-stack" @submit.prevent="save(false)">
        <p class="u-meta">
          {{ editing?.org_name }} / {{ year }} 年度 /
          {{ STATUS_LABELS[editing?.review_status || 'not_started'] }}
          <template v-if="currentId">/ 版本 {{ currentRevision }}</template>
        </p>
        <label class="wb-field"
          ><span>个人自评</span
          ><textarea
            v-model="form.self_assessment"
            class="textarea"
            rows="3"
            maxlength="5000"
            :disabled="readonly || busy"
            placeholder="本人对照党员标准作的自我评价（原文录入，不由系统代写）。"
          /></label
        >
        <label class="wb-field"
          ><span>党员互评意见（可后补）</span
          ><textarea
            v-model="form.peer_review"
            class="textarea"
            rows="3"
            maxlength="5000"
            :disabled="readonly || busy"
            placeholder="其他党员的评议意见汇总；未开展可留空，留空只提示、不阻断送审。"
          /></label
        >
        <fieldset class="review__test">
          <legend>民主测评票数（不记名，只汇总）</legend>
          <div class="wb-grid">
            <label class="wb-field"
              ><span>应参加人数</span
              ><input
                v-model="form.eligible"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
            <label class="wb-field"
              ><span>实际参加人数</span
              ><input
                v-model="form.attended"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
            <label class="wb-field"
              ><span>优秀票</span
              ><input
                v-model="form.outstanding"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
            <label class="wb-field"
              ><span>合格票</span
              ><input
                v-model="form.qualified"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
            <label class="wb-field"
              ><span>基本合格票</span
              ><input
                v-model="form.basic"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
            <label class="wb-field"
              ><span>不合格票</span
              ><input
                v-model="form.unqualified"
                class="input"
                type="number"
                min="0"
                :disabled="readonly || busy"
            /></label>
          </div>
          <p class="u-meta">
            只记汇总票数，不记谁投给谁：逐人明细属于第三人信息，也不符合不记名测评的做法。
          </p>
        </fieldset>
        <label class="wb-field"
          ><span>支部评定意见</span
          ><textarea
            v-model="form.branch_opinion"
            class="textarea"
            rows="3"
            maxlength="5000"
            :disabled="readonly || busy"
            placeholder="支委会或党员大会根据评议情况和日常表现提出的评定意见。"
          /></label
        >
        <div class="wb-grid">
          <label class="wb-field"
            ><span>评定等次</span
            ><select v-model="form.grade" class="select" :disabled="readonly || busy">
              <option value="">暂不定等次</option>
              <option v-for="item in gradeOptions" :key="item.key" :value="item.key">
                {{ item.label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>评定依据</span
            ><input
              v-model="form.basis"
              class="input"
              maxlength="2000"
              :disabled="readonly || busy"
              placeholder="如：民主测评情况与日常表现、支部意见形成依据。"
          /></label>
        </div>
        <label class="wb-field"
          ><span>对本人提出的整改要求</span
          ><textarea
            v-model="form.rectification"
            class="textarea"
            rows="2"
            maxlength="2000"
            :disabled="readonly || busy"
        /></label>
        <label class="wb-field"
          ><span>操作理由</span
          ><input
            v-model="form.reason"
            class="input"
            maxlength="2000"
            :disabled="readonly || busy"
        /></label>
        <p v-if="detail?.missing.length" class="field__error">
          送审前还需补齐：{{ detail.missing.join('；') }}
        </p>
        <p v-if="detail?.advisories.length" class="u-meta">
          未登记（不阻断送审）：{{ detail.advisories.join('；') }}
        </p>
        <p v-if="detail?.revisions.length" class="u-meta">
          当前版本 {{ detail?.revision }}；修改后须重新送审，旧版本留在修订记录中。
        </p>
        <ErrorState v-if="actionError" :error="actionError" />
        <div class="review__actions">
          <button
            v-if="editing?.can_review"
            class="btn btn--quiet"
            type="button"
            :disabled="busy"
            @click="dialog = 'decision'"
          >
            去审核这条
          </button>
          <button
            v-if="!readonly"
            class="btn btn--ghost"
            type="submit"
            :disabled="busy || !editing?.profile_id"
          >
            保存草稿
          </button>
          <button
            v-if="!readonly"
            class="btn btn--primary"
            type="button"
            :disabled="busy || !editing?.profile_id"
            @click="save(true)"
          >
            保存并送审
          </button>
        </div>
        <p v-if="editing?.review_status === 'approved'" class="wb-note">
          该评议已通过审核并生效。修订后会回到草稿状态、须重新送审，生效结果以最新通过的版本为准。
        </p>
      </form></ActionDialog
    >

    <ActionDialog
      :open="dialog === 'decision'"
      title="审核民主评议结果"
      :busy="busy"
      @close="dialog = ''"
      ><form class="wb-stack" @submit.prevent="decide">
        <p class="u-meta">
          {{ editing?.member_name }} / {{ year }} 年度 / 拟评定
          {{ editing?.grade_label || '未定等次' }}
        </p>
        <p class="wb-note">
          审核人与录入人必须是不同的人：提交人不能审核自己的版本。审核通过后结果生效并进入本人档案。
        </p>
        <label class="wb-field"
          ><span>审核结论</span
          ><select v-model="decisionForm.decision" class="select">
            <option value="approved">通过（结果生效）</option>
            <option value="rejected">退回（需修订后重新送审）</option>
          </select></label
        >
        <label class="wb-field"
          ><span>审核意见与依据</span
          ><textarea
            v-model="decisionForm.reason"
            class="textarea"
            rows="3"
            maxlength="2000"
            required
          /></label>
        <ErrorState v-if="actionError" :error="actionError" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !decisionForm.reason.trim()"
        >
          确认审核
        </button>
      </form></ActionDialog
    >
  </section>
</template>

<style scoped>
/* wb-table 的单元格默认不换行，长意见与缺项提示会被挤成一列窄条。 */
.review__list td {
  vertical-align: top;
  min-width: 6rem;
}

.review__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.review__grade {
  margin-right: 0.75rem;
  white-space: nowrap;
}

.review__test {
  border: 1px solid var(--color-border, #dcdfe6);
  border-radius: 6px;
  padding: 0.5rem 0.75rem 0.75rem;
}

.review__test legend {
  padding: 0 0.35rem;
  font-size: 0.9em;
}
</style>
