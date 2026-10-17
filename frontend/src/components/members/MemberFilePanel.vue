<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { ApiError } from '@/api/http'
import {
  CULTIVATION_LABELS,
  memberDevelopmentApi as api,
  type ArchiveCheckResult,
  type CultivationCategory,
  type MemberMaterial,
  type MemberProfile,
  type MemberScoring,
} from '@/api/member-development'
import { STAGE_LABELS, STAGE_ORDER, type MemberStage } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import { session } from '@/stores/session'
import { todayISO } from '@/utils/files'

const props = defineProps<{ profileId: string }>()
const emit = defineEmits<{ updated: []; busy: [value: boolean] }>()
const profile = ref<MemberProfile | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const message = ref('')
const busy = ref(false)
const tab = ref('materials')
const canManage = computed(() => session.can('member.stage_transition'))
const canScore = computed(() => session.can('member.scoring'))
const tabs = [
  { key: 'materials', label: '档案与材料' },
  { key: 'cultivation', label: '培养与评分' },
  { key: 'transition', label: '人工流转' },
  { key: 'history', label: '办理记录' },
  { key: 'archive', label: '档案检查' },
]
const materialLabels = { pending: '待核验', approved: '人工核验通过', rejected: '已退回' }
// 字段级敏感分级（T-MEM-12）：敏感 / 涉密材料在界面上标出来，让组织人员知道它不进导出、
// 也不交给模型；第三人字段是否已按查看者等级脱敏由后端返回的 redacted_fields 说明。
const levelLabels: Record<string, string> = { sensitive: '敏感', classified: '涉密' }
function materialLevelLabel(item: MemberMaterial): string {
  return levelLabels[item.data_level ?? ''] ?? ''
}
// 提示句按后端返回的口径拼，不写死：出网 / 向量化能不能，由 cloud_allowed / embedding_allowed 说了算。
function materialLevelNote(item: MemberMaterial): string {
  const label = materialLevelLabel(item)
  if (!label) return ''
  const parts = [`${label}级材料：不进名册 / 台账导出`]
  if (item.cloud_allowed === false) parts.push('也不交给模型')
  if (item.embedding_allowed === false) parts.push('也不用于检索向量化')
  parts.push('其中的第三人信息按查看者等级脱敏')
  return `${parts.join('，')}。`
}
const assignment = reactive({ year: new Date().getFullYear(), batch_no: '', reason: '' })
const material = reactive({
  material_type: '',
  file_version: '',
  submit_date: todayISO(),
  reason: '',
})
const reviewing = ref<MemberMaterial | null>(null)
const review = reactive({
  review_status: 'approved' as 'approved' | 'rejected',
  note: '',
  reason: '',
})
const cultivation = reactive({
  category: 'theory_test' as CultivationCategory,
  score: '' as number | '',
  year: new Date().getFullYear(),
  source_note: '',
  is_risk: false,
  risk_note: '',
})
const scoringYear = ref(new Date().getFullYear())
const scoring = ref<MemberScoring | null>(null)
watch(scoringYear, () => {
  scoring.value = null
})
const decision = reactive({
  target_stage: 'activist' as MemberStage,
  decision_date: todayISO(),
  basis: '',
  opinion: '',
  confirmed: false,
})
const checkRows = ref<{ name: string; text: string }[]>([])
const check = ref<ArchiveCheckResult | null>(null)
const nextStages = computed(() => {
  const stage = profile.value?.current_stage
  if (!stage) return []
  const next = STAGE_ORDER[STAGE_ORDER.indexOf(stage) + 1]
  return stage === 'member' || stage === 'rejected'
    ? []
    : [...(next ? [next] : []), 'rejected' as MemberStage]
})
let sequence = 0
let alive = true

async function load(): Promise<void> {
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const response = await api.profile(props.profileId)
    if (current !== sequence || !alive) return
    profile.value = response
    Object.assign(assignment, {
      year: response.year ?? new Date().getFullYear(),
      batch_no: response.batch_no ?? '',
      reason: '',
    })
    decision.target_stage = nextStages.value[0] ?? 'rejected'
    checkRows.value = response.materials.map((item) => ({ name: item.material_type, text: '' }))
  } catch (err) {
    if (current === sequence && alive) error.value = err
  } finally {
    if (current === sequence && alive) loading.value = false
  }
}
watch(
  () => props.profileId,
  () => {
    scoring.value = null
    check.value = null
    message.value = ''
    void load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  alive = false
  sequence += 1
})

async function action(fn: () => Promise<unknown>, success: string, reload = true): Promise<void> {
  if (busy.value) return
  busy.value = true
  emit('busy', true)
  error.value = null
  message.value = ''
  try {
    await fn()
    if (!alive) return
    if (reload) {
      await load()
      emit('updated')
    }
    if (success) message.value = success
  } catch (err) {
    if (alive) error.value = err
  } finally {
    busy.value = false
    emit('busy', false)
  }
}

async function saveAssignment(): Promise<void> {
  await action(
    () =>
      api.updateProfile(props.profileId, {
        year: assignment.year,
        batch_no: assignment.batch_no.trim(),
        reason: assignment.reason.trim(),
      }),
    '年度批次归属已保存。',
  )
}
async function addMaterial(): Promise<void> {
  await action(async () => {
    await api.addMaterial(props.profileId, {
      material_type: material.material_type.trim(),
      file_version: material.file_version.trim(),
      submit_date: material.submit_date || null,
      reason: material.reason.trim(),
    })
    Object.assign(material, { material_type: '', file_version: '', reason: '' })
  }, '材料已登记为待核验。')
}
async function reviewMaterial(): Promise<void> {
  if (!reviewing.value?.id) return
  const id = reviewing.value.id
  await action(async () => {
    await api.reviewMaterial(id, {
      review_status: review.review_status,
      note: review.note.trim(),
      reason: review.reason.trim(),
    })
    reviewing.value = null
  }, '材料审核及意见已保存。')
}
function startMaterialReview(item: MemberMaterial): void {
  reviewing.value = item
  error.value = null
  Object.assign(review, { review_status: 'approved', note: '', reason: '' })
}
async function addCultivation(): Promise<void> {
  await action(async () => {
    await api.cultivation(props.profileId, {
      profile_id: props.profileId,
      category: cultivation.category,
      score: cultivation.score === '' ? null : cultivation.score,
      period: String(cultivation.year),
      source_note: cultivation.source_note.trim(),
      is_risk: cultivation.is_risk,
      risk_note: cultivation.risk_note.trim(),
    })
    Object.assign(cultivation, { score: '', source_note: '', risk_note: '', is_risk: false })
    scoring.value = null
  }, '培养记录及来源说明已保存。')
}
async function calculate(): Promise<void> {
  await action(
    async () => {
      scoring.value = await api.scoring(props.profileId, scoringYear.value)
    },
    '辅助评分已生成，请逐项核对证据。',
    false,
  )
}
async function transition(): Promise<void> {
  if (!decision.confirmed) return
  await action(async () => {
    await api.transition(props.profileId, {
      target_stage: decision.target_stage,
      decision_date: decision.decision_date,
      basis: decision.basis.trim(),
      opinion: decision.opinion.trim(),
    })
    Object.assign(decision, { basis: '', opinion: '', confirmed: false })
  }, '人工阶段决定已登记；决策人、日期、依据和意见已留存。')
}
async function syncReminders(): Promise<void> {
  await action(
    async () => {
      const result = await api.syncReminders(props.profileId)
      message.value = `新增 ${result.created} 项提醒。`
    },
    '',
    false,
  )
}
async function archiveCheck(): Promise<void> {
  await action(
    async () => {
      const notes: Record<string, string> = {}
      for (const row of checkRows.value) {
        if (!row.name.trim() || !row.text.trim()) continue
        if (row.name.trim() in notes) throw new ApiError('材料名称重复，请合并核验摘录。', 42201)
        notes[row.name.trim()] = row.text.trim()
      }
      check.value = await api.archiveCheck(props.profileId, notes)
    },
    '档案检查已完成，结果仅供人工核验。',
    false,
  )
}
</script>

<template>
  <div class="wb wb-stack" :aria-busy="busy || loading">
    <LoadingBlock v-if="loading && !profile" variant="list" :rows="3" />
    <ErrorState v-if="error && !reviewing" :error="error"
      ><button v-if="!profile" class="btn btn--ghost" type="button" @click="load">
        重新加载档案
      </button></ErrorState
    >
    <template v-if="profile">
      <div class="wb-toolbar">
        <h3 class="u-title-sub">{{ profile.name }}的办理档案</h3>
        <span class="badge">{{ STAGE_LABELS[profile.current_stage] }}</span>
      </div>
      <dl class="wb-facts wb-facts--small">
        <div>
          <dt>所属组织</dt>
          <dd>{{ profile.org_name }}</dd>
        </div>
        <div>
          <dt>年度 / 批次</dt>
          <dd>{{ profile.year ?? '待登记' }} / {{ profile.batch_no || '待分配' }}</dd>
        </div>
        <div>
          <dt>进入阶段日期</dt>
          <dd>{{ profile.stage_joined_on }}</dd>
        </div>
      </dl>
      <WorkspaceTabs v-model="tab" :items="tabs" label="培养对象办理功能" :disabled="busy">
        <div v-if="tab === 'materials'" class="wb-stack">
          <details v-if="canManage" class="wb-disclosure">
            <summary>调整年度与批次归属</summary>
            <form class="wb-stack" @submit.prevent="saveAssignment">
              <div class="wb-grid">
                <label class="wb-field"
                  ><span>所属年度</span
                  ><input
                    v-model.number="assignment.year"
                    class="input"
                    type="number"
                    min="2000"
                    max="2100"
                    required
                /></label>
                <label class="wb-field"
                  ><span>已有批次号</span
                  ><input
                    v-model="assignment.batch_no"
                    class="input"
                    maxlength="20"
                    required
                  /><small>先在“年度批次”中建立批次，再填写对应批次号。</small></label
                >
              </div>
              <label class="wb-field"
                ><span>调整理由</span
                ><input v-model="assignment.reason" class="input" maxlength="2000" required
              /></label>
              <div class="wb-actions">
                <button
                  type="submit"
                  class="btn btn--primary"
                  :disabled="busy || !assignment.reason.trim()"
                >
                  保存批次归属
                </button>
              </div>
            </form>
          </details>
          <p class="wb-note">
            材料登记记录名称、版本和人工核验结果。原件按学校档案流程留存，登记名称不代表已经核验。
          </p>
          <div v-if="profile.materials.length" class="wb-stack">
            <article
              v-for="(item, index) in profile.materials"
              :key="item.id || `legacy-${index}`"
              class="wb-section wb-stack"
            >
              <div class="wb-toolbar">
                <strong>{{ item.material_type }}</strong
                ><span
                  class="badge"
                  :class="item.review_status === 'approved' ? 'badge--ok' : 'badge--warn'"
                  >{{ materialLabels[item.review_status] }}</span
                ><span v-if="materialLevelLabel(item)" class="badge badge--warn">{{
                  materialLevelLabel(item)
                }}</span>
              </div>
              <p class="u-meta">
                {{
                  item.legacy_material
                    ? '历史名称记录，原件待核验'
                    : `版本 ${item.file_version || '未标注'} / 提交 ${item.submit_date || '未记录'}`
                }}
              </p>
              <p v-if="materialLevelNote(item)" class="u-meta">{{ materialLevelNote(item) }}</p>
              <p v-if="item.note">{{ item.note }}</p>
              <button
                v-if="canManage && item.id"
                class="btn btn--ghost btn--sm"
                type="button"
                :disabled="busy"
                @click="startMaterialReview(item)"
              >
                登记人工审核
              </button>
              <details v-if="item.review_history?.length" class="wb-disclosure">
                <summary>查看审核历史（{{ item.review_history.length }}）</summary>
                <div v-for="entry in item.review_history" :key="entry.revision" class="wb-log">
                  <p>版本 {{ entry.revision }} / {{ entry.created_at }}</p>
                  <p>审核人：{{ entry.actor_id }}</p>
                  <p>{{ entry.snapshot.note || '未填写意见' }}</p>
                  <p>理由：{{ entry.reason }}</p>
                </div>
              </details>
            </article>
          </div>
          <p v-else class="wb-empty">尚未登记材料。</p>
          <details v-if="canManage" class="wb-disclosure">
            <summary>补交材料登记</summary>
            <form class="wb-stack" @submit.prevent="addMaterial">
              <div class="wb-grid">
                <label class="wb-field"
                  ><span>材料名称</span
                  ><input v-model="material.material_type" class="input" maxlength="100" required
                /></label>
                <label class="wb-field"
                  ><span>原件版本标记</span
                  ><input v-model="material.file_version" class="input" maxlength="100"
                /></label>
                <label class="wb-field"
                  ><span>提交日期</span
                  ><input
                    v-model="material.submit_date"
                    class="input"
                    type="date"
                    :max="todayISO()"
                /></label>
                <label class="wb-field"
                  ><span>登记理由</span
                  ><input v-model="material.reason" class="input" maxlength="2000" required
                /></label>
              </div>
              <div class="wb-actions">
                <button
                  class="btn btn--primary"
                  type="submit"
                  :disabled="busy || !material.reason.trim()"
                >
                  登记待核验材料
                </button>
              </div>
            </form>
          </details>
        </div>
        <div v-else-if="tab === 'cultivation'" class="wb-stack">
          <div class="wb-table-wrap" v-if="profile.cultivation.length">
            <table class="wb-table">
              <thead>
                <tr>
                  <th>类别 / 年度</th>
                  <th>分值 / 风险</th>
                  <th>证据来源</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in profile.cultivation" :key="item.id">
                  <td>
                    {{ CULTIVATION_LABELS[item.category] }}
                    <p class="u-meta">{{ item.period || '未标注期间' }}</p>
                  </td>
                  <td>
                    {{ item.score ?? '无分值' }}
                    <p v-if="item.is_risk" class="field__error">
                      {{ item.risk_note || '待核验风险' }}
                    </p>
                  </td>
                  <td>
                    {{ item.source_note || '未填写来源' }}
                    <p class="u-meta">{{ item.verified_at || '核验时间未记录' }}</p>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="wb-empty">尚无培养记录，缺少证据的维度不会打分。</p>
          <details v-if="canManage" class="wb-disclosure">
            <summary>登记培养与表现记录</summary>
            <form class="wb-stack" @submit.prevent="addCultivation">
              <div class="wb-grid">
                <label class="wb-field"
                  ><span>类别</span
                  ><select v-model="cultivation.category" class="select">
                    <option v-for="(label, key) in CULTIVATION_LABELS" :key="key" :value="key">
                      {{ label }}
                    </option>
                  </select></label
                >
                <label class="wb-field"
                  ><span>统计年度</span
                  ><input
                    v-model.number="cultivation.year"
                    class="input"
                    type="number"
                    min="2000"
                    max="2100"
                    required
                /></label>
                <label class="wb-field"
                  ><span>分值（无评分证据时留空）</span
                  ><input
                    v-model.number="cultivation.score"
                    class="input"
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                /></label>
                <label class="wb-field"
                  ><span>证据来源说明</span
                  ><textarea
                    v-model="cultivation.source_note"
                    class="textarea"
                    rows="2"
                    maxlength="500"
                    required
                  />
                </label>
              </div>
              <label class="wb-check"
                ><input
                  v-model="cultivation.is_risk"
                  type="checkbox"
                />此项涉及需要人工核验的风险</label
              >
              <label v-if="cultivation.is_risk" class="wb-field"
                ><span>风险说明</span
                ><textarea
                  v-model="cultivation.risk_note"
                  class="textarea"
                  rows="2"
                  maxlength="500"
                  required
                />
              </label>
              <div class="wb-actions">
                <button class="btn btn--primary" type="submit" :disabled="busy">
                  保存培养记录
                </button>
              </div>
            </form>
          </details>
          <form v-if="canScore" class="wb-actions" @submit.prevent="calculate">
            <label class="wb-field"
              ><span>评分年度</span
              ><input
                v-model.number="scoringYear"
                class="input"
                type="number"
                min="2000"
                max="2100"
                required /></label
            ><button class="btn btn--ghost" type="submit" :disabled="busy">生成辅助评分</button>
          </form>
          <section v-if="scoring" class="wb-section wb-stack">
            <div class="wb-toolbar">
              <h3>{{ scoring.year }}年度辅助评分</h3>
              <strong>{{ scoring.weighted_score ?? '暂无评分证据' }}</strong>
            </div>
            <p class="wb-note">{{ scoring.disclaimer }}</p>
            <article v-for="(dimension, key) in scoring.dimensions" :key="key" class="wb-log">
              <p>
                <strong>{{ CULTIVATION_LABELS[key as CultivationCategory] || key }}</strong
                >：{{ dimension.value ?? '无证据，不评分' }}（权重 {{ dimension.weight }}）
              </p>
              <p v-for="evidence in dimension.evidence" :key="evidence.source_id">
                {{ evidence.period }} / {{ evidence.note || '来源说明待补'
                }}<span class="u-meta"> 来源编号 {{ evidence.source_id }}</span>
              </p>
            </article>
            <p v-for="risk in scoring.risks" :key="risk.source_id" class="field__error">
              {{ risk.risk_note }}（{{ risk.source_id }}）
            </p>
            <p class="u-meta">规则来源：{{ scoring.rule_version }}</p>
          </section>
        </div>
        <div v-else-if="tab === 'transition'" class="wb-stack">
          <p class="wb-note">
            {{
              profile.boundary
            }}
            系统会核对阶段顺序、培养时限和已核验材料。请填写已经形成的组织决定。
          </p>
          <form v-if="canManage && nextStages.length" class="wb-stack" @submit.prevent="transition">
            <div class="wb-grid">
              <label class="wb-field"
                ><span>人工决定的目标阶段</span
                ><select v-model="decision.target_stage" class="select">
                  <option v-for="stage in nextStages" :key="stage" :value="stage">
                    {{ STAGE_LABELS[stage] }}
                  </option>
                </select></label
              >
              <label class="wb-field"
                ><span>组织决定日期</span
                ><input
                  v-model="decision.decision_date"
                  class="input"
                  type="date"
                  :min="profile.stage_joined_on"
                  :max="todayISO()"
                  required
              /></label>
            </div>
            <label class="wb-field"
              ><span>决定依据</span
              ><textarea
                v-model="decision.basis"
                class="textarea"
                rows="3"
                maxlength="2000"
                required
              /></label
            ><label class="wb-field"
              ><span>组织意见</span
              ><textarea v-model="decision.opinion" class="textarea" rows="3" maxlength="2000" />
            </label>
            <label class="wb-check"
              ><input
                v-model="decision.confirmed"
                type="checkbox"
                required
              />我已核对材料、时限及组织决定，确认登记这次人工流转。</label
            >
            <div class="wb-actions">
              <button
                class="btn btn--primary"
                type="submit"
                :disabled="busy || !decision.confirmed || !decision.basis.trim()"
              >
                登记人工决定
              </button>
            </div>
          </form>
          <p v-else class="u-meta">
            {{
              canManage
                ? '当前阶段没有可登记的后续流转。'
                : '当前账号可查看档案；阶段决定由具备权限的组织人员登记。'
            }}
          </p>
          <button
            v-if="canManage"
            class="btn btn--ghost"
            type="button"
            :disabled="busy"
            @click="syncReminders"
          >
            按当前阶段同步提醒
          </button>
        </div>
        <div v-else-if="tab === 'history'" class="wb-stack">
          <p v-if="!profile.stage_history.length" class="wb-empty">尚无人工阶段流转记录。</p>
          <article
            v-for="entry in profile.stage_history"
            :key="entry.id"
            class="wb-section wb-stack"
          >
            <div class="wb-toolbar">
              <strong
                >{{ STAGE_LABELS[entry.from_stage] }} → {{ STAGE_LABELS[entry.to_stage] }}</strong
              ><span class="u-meta">{{ entry.decision_date }}</span>
            </div>
            <p>决定依据：{{ entry.basis }}</p>
            <p>组织意见：{{ entry.opinion || '未填写' }}</p>
            <p class="u-meta">决策人编号：{{ entry.decided_by }}</p>
          </article>
        </div>
        <div v-else-if="tab === 'archive'" class="wb-stack">
          <p class="wb-note">
            逐项填写实际查看的原件内容。留空材料不计为已提供，检查提示不能替代人工档案审核。
          </p>
          <form v-if="canManage" class="wb-stack" @submit.prevent="archiveCheck">
            <div v-for="(row, index) in checkRows" :key="index" class="wb-section wb-stack">
              <label class="wb-field"
                ><span>材料名称</span
                ><input v-model="row.name" class="input" maxlength="100" /></label
              ><label class="wb-field"
                ><span>原件核验摘录</span
                ><textarea v-model="row.text" class="textarea" rows="3" maxlength="10000" />
              </label>
            </div>
            <div class="wb-actions">
              <button
                class="btn btn--ghost"
                type="button"
                :disabled="busy || checkRows.length >= 300"
                @click="checkRows.push({ name: '', text: '' })"
              >
                添加核验材料</button
              ><button class="btn btn--primary" type="submit" :disabled="busy">运行档案检查</button>
            </div>
          </form>
          <section v-if="check" class="wb-section wb-stack">
            <h3>检查结果</h3>
            <p>{{ check.result.required_for }}</p>
            <p v-for="item in check.result.missing" :key="item" class="field__error">
              缺少材料：{{ item }}
            </p>
            <p
              v-for="item in [...check.result.irregular, ...check.result.risks]"
              :key="item"
              class="field__error"
            >
              {{ item }}
            </p>
            <p
              v-if="
                ![...check.result.missing, ...check.result.irregular, ...check.result.risks].length
              "
            >
              本次规则检查未发现缺项，仍需人工核验原件。
            </p>
            <p class="u-meta">{{ check.checked_at }} / {{ check.rule_version }}</p>
            <p class="wb-note">{{ check.note }}</p>
          </section>
        </div>
      </WorkspaceTabs>
      <p v-if="message" class="wb-success" role="status">{{ message }}</p>
    </template>
    <ActionDialog
      :open="reviewing !== null"
      title="登记材料人工审核"
      :busy="busy"
      @close="reviewing = null"
    >
      <form class="wb-stack" @submit.prevent="reviewMaterial">
        <p>{{ reviewing?.material_type }}</p>
        <label class="wb-field"
          ><span>人工核验结果</span
          ><select v-model="review.review_status" class="select">
            <option value="approved">人工核验通过</option>
            <option value="rejected">退回补正</option>
          </select></label
        ><label class="wb-field"
          ><span>审核意见</span
          ><textarea
            v-model="review.note"
            class="textarea"
            rows="3"
            maxlength="500"
            required
          /></label
        ><label class="wb-field"
          ><span>审核依据 / 理由</span
          ><textarea
            v-model="review.reason"
            class="textarea"
            rows="2"
            maxlength="2000"
            required
          /></label
        ><ErrorState v-if="error" :error="error" /><button
          class="btn btn--primary"
          type="submit"
          :disabled="busy || !review.reason.trim()"
        >
          保存人工审核
        </button>
      </form>
    </ActionDialog>
  </div>
</template>
