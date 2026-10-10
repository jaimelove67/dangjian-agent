<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { checkQualification, createMember, getTodoSuggestions, getTransitionSuggestion, listRoster } from '@/api/member'
import { ApiError } from '@/api/http'
import { MOCK_TODOS } from '@/api/mock'
import type {
  MemberRosterItem,
  MemberStage,
  QualificationResult,
  TodoItem,
  TodoSuggestionsResponse,
  TransitionSuggestion,
} from '@/api/types'
import { STAGE_LABELS, STAGE_ORDER, TODO_CATEGORY_LABELS } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'

/**
 * 党员发展。
 *
 * 本页是全项目**合规红线最密集**的界面，因此版面也最克制：
 *   - 顶部常驻决策边界声明（对应 app/schemas/member.py::DECISION_BOUNDARY_NOTE 的语义）
 *   - 所有校验结果都标注为"建议 / 待人工确认"，绝不出现"通过""不通过"这类结论性动词
 *   - 阶段性动作按钮一律不可用，只给"生成建议"，把操作权明确留在人工途径
 *
 * 名册与三块分析（资格校验 / 流转建议 / 待办建议）均为**真实接口调用**。
 */

type PanelTab = 'qualification' | 'transition' | 'todo'

const members = ref<MemberRosterItem[]>([])
const loading = ref(true)
const loadError = ref<unknown>(null)
const selectedId = ref<string | null>(null)
const panelTab = ref<PanelTab>('qualification')

const qualification = ref<QualificationResult | null>(null)
const transition = ref<TransitionSuggestion | null>(null)
const todos = ref<TodoSuggestionsResponse | null>(null)

const busy = ref<null | PanelTab>(null)
const panelError = ref<unknown>(null)

/** 校验用输入，跟随选中成员初始化，允许人工调整 */
const form = reactive({
  target_stage: 'candidate' as MemberStage,
  days_in_stage: 0,
  materials: [] as string[],
})

const MATERIAL_POOL = [
  '入党申请书',
  '党组织谈话记录',
  '思想汇报',
  '培养考察记录',
  '群众评议材料',
  '党课培训证明',
  '政治审查材料',
  '公示情况报告',
  '支部大会决议',
  '上级审批意见',
  '转正申请书',
  '预备期考察记录',
]

const selected = computed(() => members.value.find((m) => m.id === selectedId.value) ?? null)

/** 可选目标阶段：只允许流程中的下一步，避免出现"跳级"这种不存在的情形 */
const targetOptions = computed(() => {
  const cur = selected.value?.stage
  if (!cur) return []
  const i = STAGE_ORDER.indexOf(cur)
  if (i < 0) return []
  return STAGE_ORDER.slice(i + 1).map((s) => ({ value: s, label: STAGE_LABELS[s] }))
})

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const { items } = await listRoster()
    members.value = items
    selectedId.value = null
    if (members.value.length) select(members.value[0]!.id)
  } catch (err) {
    loadError.value = err
    members.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)

/* ---------------------------- 新增培养对象 ------------------------------ */

const createOpen = ref(false)
const createSubmitting = ref(false)
const createError = ref('')

/** 起始阶段候选（不含"退回"，新增对象从正常流程起点开始） */
const CREATE_STAGES: MemberStage[] = ['applicant', 'activist', 'candidate', 'probationary', 'member']

const create = reactive({
  name: '',
  org_name: '',
  current_stage: 'applicant' as MemberStage,
  stage_joined_on: new Date().toISOString().slice(0, 10),
  materials: [] as string[],
  pending: 0,
})

const createValid = computed(
  () => create.name.trim().length > 0 && create.org_name.trim().length > 0,
)

function toggleCreateMaterial(name: string): void {
  const i = create.materials.indexOf(name)
  if (i >= 0) create.materials.splice(i, 1)
  else create.materials.push(name)
}

function resetCreate(): void {
  create.name = ''
  create.org_name = ''
  create.current_stage = 'applicant'
  create.stage_joined_on = new Date().toISOString().slice(0, 10)
  create.materials = []
  create.pending = 0
  createError.value = ''
}

async function submitCreate(): Promise<void> {
  if (!createValid.value) return
  createSubmitting.value = true
  createError.value = ''
  try {
    const item = await createMember({
      name: create.name.trim(),
      org_name: create.org_name.trim(),
      current_stage: create.current_stage,
      stage_joined_on: create.stage_joined_on || undefined,
      materials: [...create.materials],
      pending: create.pending,
    })
    members.value = [item, ...members.value]
    select(item.id)
    createOpen.value = false
    resetCreate()
  } catch (err) {
    createError.value = err instanceof ApiError ? err.message : '新增失败，请重试'
  } finally {
    createSubmitting.value = false
  }
}

function select(id: string): void {
  selectedId.value = id
  qualification.value = null
  transition.value = null
  todos.value = null
  panelError.value = null

  const m = members.value.find((x) => x.id === id)
  if (!m) return

  form.days_in_stage = m.days_in_stage
  form.materials = [...m.materials]
  const opts = STAGE_ORDER.indexOf(m.stage)
  const next = opts >= 0 ? STAGE_ORDER[opts + 1] : undefined
  if (next) form.target_stage = next
}

function toggleMaterial(name: string): void {
  const i = form.materials.indexOf(name)
  if (i >= 0) form.materials.splice(i, 1)
  else form.materials.push(name)
}

async function runQualification(): Promise<void> {
  if (!selected.value) return
  busy.value = 'qualification'
  panelError.value = null
  try {
    qualification.value = await checkQualification({
      current_stage: selected.value.stage,
      target_stage: form.target_stage,
      materials: [...form.materials],
      days_in_stage: form.days_in_stage,
    })
  } catch (err) {
    panelError.value = err
  } finally {
    busy.value = null
  }
}

async function runTransition(): Promise<void> {
  if (!selected.value) return
  busy.value = 'transition'
  panelError.value = null
  try {
    transition.value = await getTransitionSuggestion({
      current_stage: selected.value.stage,
      target_stage: form.target_stage,
      materials: [...form.materials],
      days_in_stage: form.days_in_stage,
    })
  } catch (err) {
    panelError.value = err
  } finally {
    busy.value = null
  }
}

async function runTodos(): Promise<void> {
  if (!selected.value) return
  busy.value = 'todo'
  panelError.value = null
  try {
    todos.value = await getTodoSuggestions({ current_stage: selected.value.stage })
  } catch (err) {
    panelError.value = err
  } finally {
    busy.value = null
  }
}

/** 天数进度：用于把"还差多少天"可视化，比纯数字更容易判断紧迫度 */
function dayRatio(minDays: number, days: number): number {
  if (minDays <= 0) return 1
  return Math.min(1, days / minDays)
}

const PANEL_TABS: { key: PanelTab; label: string; icon: 'check' | 'arrow-right' | 'clock' }[] = [
  { key: 'qualification', label: '资格校验', icon: 'check' },
  { key: 'transition', label: '流转建议', icon: 'arrow-right' },
  { key: 'todo', label: '待办建议', icon: 'clock' },
]

const todoTone: Record<TodoItem['category'], string> = {
  material: 'badge--warn',
  meeting: 'badge--accent',
  reminder: 'badge',
}
</script>

<template>
  <div class="mem">
    <PageHeader
      title="党员发展"
      description="对照各阶段材料与时限要求，辅助核对培养进度。所有结果均为待人工确认的提示。"
    >
      <template #actions>
        <button class="btn btn--primary" type="button" @click="createOpen = !createOpen">
          <AppIcon name="plus" :size="14" />
          <span>新增培养对象</span>
        </button>
        <button class="btn btn--quiet" type="button" @click="load">
          <AppIcon name="pulse" :size="14" />
          <span>刷新</span>
        </button>
      </template>
    </PageHeader>

    <!-- 决策边界声明：本页最高优先级的文字，必须在任何操作之前出现 -->
    <section class="boundary" role="note">
      <AppIcon name="shield" :size="17" />
      <div>
        <p class="boundary__title">决策边界</p>
        <p class="boundary__text">
          阶段流转仅可通过人工接口，由具备权限的组织人员依规操作；本页结果不构成任何组织认定或选拔结论。
        </p>
      </div>
    </section>

    <!-- ---------------------------- 新增培养对象 ---------------------------- -->
    <section v-if="createOpen" class="create u-card">
      <header class="u-panel-head">
        <h2 class="create__title">新增培养对象</h2>
        <button class="btn btn--quiet" type="button" @click="createOpen = false">
          <AppIcon name="close" :size="14" />
          <span>收起</span>
        </button>
      </header>

      <div class="create__body">
        <div class="form-grid">
          <div class="field">
            <label class="field__label" for="c-name">姓名</label>
            <input id="c-name" v-model="create.name" class="input" type="text" maxlength="50" />
          </div>
          <div class="field">
            <label class="field__label" for="c-org">组织全名</label>
            <input
              id="c-org"
              v-model="create.org_name"
              class="input"
              type="text"
              placeholder="如：计算机学院党委 · 本科生第一党支部"
            />
          </div>
          <div class="field">
            <label class="field__label" for="c-stage">起始阶段</label>
            <select id="c-stage" v-model="create.current_stage" class="select">
              <option v-for="s in CREATE_STAGES" :key="s" :value="s">{{ STAGE_LABELS[s] }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="c-joined">进入阶段日期</label>
            <input id="c-joined" v-model="create.stage_joined_on" class="input" type="date" />
          </div>
          <div class="field">
            <label class="field__label" for="c-pending">待办数</label>
            <input id="c-pending" v-model.number="create.pending" class="input" type="number" min="0" />
          </div>
        </div>

        <div class="field">
          <span class="field__label">已具备材料</span>
          <div class="chips">
            <button
              v-for="mat in MATERIAL_POOL"
              :key="mat"
              class="chip"
              :class="{ 'is-on': create.materials.includes(mat) }"
              type="button"
              :aria-pressed="create.materials.includes(mat)"
              @click="toggleCreateMaterial(mat)"
            >
              <AppIcon :name="create.materials.includes(mat) ? 'check' : 'plus'" :size="12" />
              <span>{{ mat }}</span>
            </button>
          </div>
        </div>

        <div v-if="createError" class="create__error" role="alert">
          <AppIcon name="alert" :size="14" />
          <span>{{ createError }}</span>
        </div>

        <footer class="create__foot">
          <p class="create__hint">
            <AppIcon name="shield" :size="14" />
            <span>此处为培养对象登记，不构成任何组织认定；阶段流转仍仅通过人工途径操作。</span>
          </p>
          <div class="create__actions">
            <button class="btn btn--ghost" type="button" @click="resetCreate">重置</button>
            <button
              class="btn btn--primary"
              type="button"
              :disabled="!createValid || createSubmitting"
              @click="submitCreate"
            >
              {{ createSubmitting ? '提交中' : '确认新增' }}
            </button>
          </div>
        </footer>
      </div>
    </section>

    <div class="mem__grid">
      <!-- ---------------------------- 名册 ---------------------------- -->
      <section class="roster u-card">
        <header class="u-panel-head">
          <h2 class="roster__title">培养对象</h2>
          <span class="badge">{{ members.length }}</span>
        </header>

        <LoadingBlock v-if="loading" variant="list" :rows="5" />

        <ErrorState v-else-if="loadError" :error="loadError">
          <button class="btn btn--ghost" type="button" @click="load">重新加载</button>
        </ErrorState>

        <div v-else-if="!members.length" class="roster__body">
          <EmptyState icon="people" title="暂无培养对象" body="当前租户下暂无可展示的培养对象。" />
        </div>

        <ul v-else class="roster__list">
          <li v-for="m in members" :key="m.id">
            <button
              class="roster__item"
              :class="{ 'is-active': selectedId === m.id }"
              type="button"
              :aria-pressed="selectedId === m.id"
              @click="select(m.id)"
            >
              <span class="roster__row">
                <span class="roster__name">{{ m.name }}</span>
                <span class="badge">{{ STAGE_LABELS[m.stage] }}</span>
              </span>
              <span class="roster__org">{{ m.org_name }}</span>
              <span class="roster__meta">
                <span class="u-meta">在阶段 {{ m.days_in_stage }} 天</span>
                <span v-if="m.pending" class="badge badge--warn">待办 {{ m.pending }}</span>
              </span>
            </button>
          </li>
        </ul>
      </section>

      <!-- ---------------------------- 工作区 ---------------------------- -->
      <section class="work u-card">
        <div v-if="!selected" class="work__empty">
          <EmptyState
            icon="people"
            title="请选择一名培养对象"
            body="选中左侧名册中的对象后，可对其当前阶段与目标阶段进行材料与时限核对。"
          />
        </div>

        <template v-else>
          <!-- 对象概要 -->
          <header class="work__head">
            <div class="work__who">
              <span class="work__avatar" aria-hidden="true">{{ selected.name.slice(0, 1) }}</span>
              <div>
                <p class="work__name">{{ selected.name }}</p>
                <p class="work__org">{{ selected.org_name }}</p>
              </div>
            </div>

            <!-- 阶段步骤条：纯展示，不可点击——不提供任何"推进"入口 -->
            <ol class="steps">
              <li
                v-for="(s, i) in STAGE_ORDER"
                :key="s"
                class="steps__item"
                :class="{
                  'is-done': STAGE_ORDER.indexOf(selected.stage) > i,
                  'is-current': s === selected.stage,
                }"
              >
                <span class="steps__dot" aria-hidden="true"></span>
                <span class="steps__label">{{ STAGE_LABELS[s] }}</span>
              </li>
            </ol>
          </header>

          <!-- 校验输入 -->
          <div class="form-grid">
            <div class="field">
              <label class="field__label" for="cur">当前阶段</label>
              <input id="cur" class="input" type="text" :value="STAGE_LABELS[selected.stage]" disabled />
            </div>
            <div class="field">
              <label class="field__label" for="tgt">目标阶段</label>
              <select id="tgt" v-model="form.target_stage" class="select">
                <option v-for="o in targetOptions" :key="o.value" :value="o.value">
                  {{ o.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label class="field__label" for="days">在阶段天数</label>
              <input id="days" v-model.number="form.days_in_stage" class="input" type="number" min="0" />
            </div>
          </div>

          <div class="field">
            <span class="field__label">已具备材料</span>
            <div class="chips">
              <button
                v-for="mat in MATERIAL_POOL"
                :key="mat"
                class="chip"
                :class="{ 'is-on': form.materials.includes(mat) }"
                type="button"
                :aria-pressed="form.materials.includes(mat)"
                @click="toggleMaterial(mat)"
              >
                <AppIcon :name="form.materials.includes(mat) ? 'check' : 'plus'" :size="12" />
                <span>{{ mat }}</span>
              </button>
            </div>
          </div>

          <!-- 分析面板 -->
          <div class="panel">
            <div class="panel__tabs" role="tablist">
              <button
                v-for="t in PANEL_TABS"
                :key="t.key"
                class="panel__tab"
                :class="{ 'is-active': panelTab === t.key }"
                type="button"
                role="tab"
                :aria-selected="panelTab === t.key"
                @click="panelTab = t.key"
              >
                {{ t.label }}
              </button>
            </div>

            <div class="panel__body">
              <ErrorState v-if="panelError" :error="panelError">
                <button
                  class="btn btn--ghost"
                  type="button"
                  @click="
                    panelTab === 'qualification'
                      ? runQualification()
                      : panelTab === 'transition'
                        ? runTransition()
                        : runTodos()
                  "
                >
                  重试
                </button>
              </ErrorState>

              <LoadingBlock v-else-if="busy === panelTab" variant="list" :rows="3" />

              <!-- 资格校验 -->
              <template v-else-if="panelTab === 'qualification'">
                <div v-if="!qualification" class="panel__idle">
                  <p>核对当前材料与在阶段天数是否满足目标阶段的入门要求。</p>
                  <button class="btn btn--primary" type="button" @click="runQualification">
                    执行资格校验
                  </button>
                </div>

                <div v-else class="result">
                  <div class="result__banner" :class="qualification.eligible ? 'is-ok' : 'is-warn'">
                    <AppIcon :name="qualification.eligible ? 'check' : 'alert'" :size="16" />
                    <div>
                      <p class="result__verdict">
                        {{ qualification.eligible ? '材料与时限已齐备' : '尚不满足条件' }}
                      </p>
                      <p class="result__sub">
                        此为机器核对结果，是否具备资格须由党组织依规认定。
                      </p>
                    </div>
                  </div>

                  <!-- 天数进度 -->
                  <div class="gauge">
                    <div class="gauge__head">
                      <span class="u-label">在阶段天数</span>
                      <span class="u-mono gauge__nums">
                        {{ qualification.days_in_stage }} / {{ qualification.min_days }} 天
                      </span>
                    </div>
                    <div class="gauge__track">
                      <div
                        class="gauge__fill"
                        :class="{ 'is-ok': qualification.days_in_stage >= qualification.min_days }"
                        :style="{
                          width: `${dayRatio(qualification.min_days, qualification.days_in_stage) * 100}%`,
                        }"
                      ></div>
                    </div>
                    <p class="u-meta gauge__note">
                      <template v-if="qualification.days_in_stage >= qualification.min_days">
                        已满最低时限要求。
                      </template>
                      <template v-else>
                        距最低时限尚差
                        {{ qualification.min_days - qualification.days_in_stage }} 天。
                      </template>
                    </p>
                  </div>

                  <div class="lists">
                    <div class="list-block">
                      <h4 class="list-block__title">
                        缺失材料
                        <span class="u-num list-block__n">{{ qualification.missing_materials.length }}</span>
                      </h4>
                      <ul v-if="qualification.missing_materials.length" class="list-block__items">
                        <li v-for="m in qualification.missing_materials" :key="m" class="list-block__item is-missing">
                          <AppIcon name="close" :size="13" />
                          <span>{{ m }}</span>
                        </li>
                      </ul>
                      <p v-else class="list-block__none">无</p>
                    </div>

                    <div class="list-block">
                      <h4 class="list-block__title">
                        已具备材料
                        <span class="u-num list-block__n">{{ qualification.present_materials.length }}</span>
                      </h4>
                      <ul v-if="qualification.present_materials.length" class="list-block__items">
                        <li v-for="m in qualification.present_materials" :key="m" class="list-block__item">
                          <AppIcon name="check" :size="13" />
                          <span>{{ m }}</span>
                        </li>
                      </ul>
                      <p v-else class="list-block__none">无</p>
                    </div>
                  </div>

                  <div v-if="qualification.blockers.length" class="blockers">
                    <h4 class="blockers__title">待人工确认事项</h4>
                    <ul>
                      <li v-for="(b, i) in qualification.blockers" :key="i">{{ b }}</li>
                    </ul>
                  </div>
                </div>
              </template>

              <!-- 流转建议 -->
              <template v-else-if="panelTab === 'transition'">
                <div v-if="!transition" class="panel__idle">
                  <p>根据当前阶段生成可能的后续阶段与应走的程序清单。</p>
                  <button class="btn btn--primary" type="button" @click="runTransition">
                    生成流转建议
                  </button>
                </div>

                <div v-else class="result">
                  <dl class="facts">
                    <div class="facts__row">
                      <dt>当前阶段</dt>
                      <dd>{{ STAGE_LABELS[transition.current_stage] }}</dd>
                    </div>
                    <div class="facts__row">
                      <dt>建议目标</dt>
                      <dd>
                        <span v-if="transition.suggested_target" class="badge badge--accent">
                          {{ STAGE_LABELS[transition.suggested_target] }}
                        </span>
                        <span v-else class="u-faint">暂不建议流转</span>
                      </dd>
                    </div>
                    <div class="facts__row">
                      <dt>条件判断</dt>
                      <dd>{{ transition.eligible ? '材料已齐备' : '材料尚有欠缺' }}</dd>
                    </div>
                  </dl>

                  <div class="list-block">
                    <h4 class="list-block__title">应走程序</h4>
                    <ol v-if="transition.procedures.length" class="proc">
                      <li v-for="(p, i) in transition.procedures" :key="i" class="proc__item">
                        <span class="proc__idx u-mono">{{ i + 1 }}</span>
                        <span>{{ p }}</span>
                      </li>
                    </ol>
                    <p v-else class="list-block__none">无明确程序项</p>
                  </div>

                  <div v-if="transition.blockers.length" class="blockers">
                    <h4 class="blockers__title">待人工确认事项</h4>
                    <ul>
                      <li v-for="(b, i) in transition.blockers" :key="i">{{ b }}</li>
                    </ul>
                  </div>

                  <p class="note">
                    <AppIcon name="info" :size="14" />
                    <span>{{ transition.note }}</span>
                  </p>
                </div>
              </template>

              <!-- 待办建议 -->
              <template v-else>
                <div v-if="!todos" class="panel__idle">
                  <p>汇总该对象当前阶段下值得关注的材料、会议与提醒事项。</p>
                  <div class="panel__idle-actions">
                    <button class="btn btn--primary" type="button" @click="runTodos">
                      生成待办建议
                    </button>
                    <button class="btn btn--quiet" type="button" @click="todos = { todos: MOCK_TODOS, note: '以下为离线示例，未取自后端计算' }">
                      查看示例
                    </button>
                  </div>
                </div>

                <div v-else class="result">
                  <ul class="todos">
                    <li v-for="(t, i) in todos.todos" :key="i" class="todos__item">
                      <span class="badge" :class="todoTone[t.category]">
                        {{ TODO_CATEGORY_LABELS[t.category] }}
                      </span>
                      <span class="todos__text">{{ t.content }}</span>
                    </li>
                  </ul>
                  <p class="note">
                    <AppIcon name="info" :size="14" />
                    <span>{{ todos.note }}</span>
                  </p>
                </div>
              </template>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.mem {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6) var(--space-6) var(--space-10);
  width: 100%;
}

/* ---------------------------- 边界声明 ---------------------------- */
.boundary {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--accent-wash);
  border: 1px solid var(--accent-edge);
  border-left-width: 3px;
  border-radius: var(--radius-sm);
  color: var(--accent-deep);
}

.boundary__title {
  font-size: var(--text-sm);
  font-weight: 700;
  letter-spacing: 0.02em;
}

.boundary__text {
  margin-top: 2px;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

/* ---------------------------- 新增培养对象 ---------------------------- */
.create {
  overflow: hidden;
}

.create__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.create__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-5);
}

.create__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  color: var(--bad-ink);
  background: var(--bad-wash);
  border: 1px solid var(--bad-edge);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.create__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-top: var(--space-4);
  border-top: var(--border);
}

.create__hint {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

.create__actions {
  display: flex;
  gap: var(--space-2);
  flex: none;
}

/* ---------------------------- 布局 -------------------------------- */
.mem__grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}

/* ---------------------------- 名册 -------------------------------- */
.roster {
  overflow: hidden;
}

.roster__title {
  font-size: var(--text-sm);
  font-weight: 600;
}

.roster__list {
  max-height: calc(100dvh - 280px);
  overflow-y: auto;
}

.roster__item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border);
  text-align: left;
  transition: background-color var(--dur-fast) var(--ease);
}

.roster__item:hover {
  background: var(--paper-dim);
}

.roster__item.is-active {
  background: var(--accent-wash);
  box-shadow: inset 2px 0 0 var(--accent);
}

.roster__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.roster__name {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
}

.roster__org {
  font-size: var(--text-xs);
  color: var(--ink-muted);
  line-height: var(--leading-snug);
}

.roster__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 2px;
}

/* ---------------------------- 工作区 ------------------------------ */
.work {
  min-width: 0;
  overflow: hidden;
}

.work__empty {
  padding: var(--space-6);
}

.work__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  flex-wrap: wrap;
  padding: var(--space-4) var(--space-5);
  background: var(--paper-dim);
  border-bottom: var(--border);
}

.work__who {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.work__avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  font-family: var(--font-serif);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--accent-deep);
  background: var(--paper-raised);
  border: 1px solid var(--accent-edge);
  border-radius: var(--radius-full);
}

.work__name {
  font-family: var(--font-serif);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ink);
}

.work__org {
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

/* 步骤条：展示型，无交互 */
.steps {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.steps__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-faint);
}

.steps__dot {
  width: 7px;
  height: 7px;
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-full);
  background: var(--paper-raised);
}

.steps__item.is-done {
  color: var(--ink-muted);
}

.steps__item.is-done .steps__dot {
  background: var(--rule-strong);
  border-color: var(--rule-strong);
}

.steps__item.is-current {
  color: var(--accent-deep);
  font-weight: 600;
}

.steps__item.is-current .steps__dot {
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-wash);
}

/* ---------------------------- 表单 -------------------------------- */
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5) 0;
}

.work > .field,
.work .form-grid + .field {
  padding-inline: var(--space-5);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 26px;
  padding: 0 var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-full);
  background: var(--paper-raised);
  font-size: var(--text-xs);
  color: var(--ink-muted);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.chip:hover {
  border-color: var(--ink-faint);
  color: var(--ink);
}

.chip.is-on {
  background: var(--accent-wash);
  border-color: var(--accent-edge);
  color: var(--accent-deep);
  font-weight: 500;
}

/* ---------------------------- 面板 -------------------------------- */
.panel {
  margin-top: var(--space-5);
  border-top: var(--border);
}

.panel__tabs {
  display: flex;
  gap: var(--space-5);
  padding: 0 var(--space-5);
  border-bottom: var(--border);
}

.panel__tab {
  position: relative;
  padding: var(--space-3) 0;
  font-size: var(--text-base);
  color: var(--ink-muted);
  transition: color var(--dur-fast) var(--ease);
}

.panel__tab:hover {
  color: var(--ink);
}

.panel__tab.is-active {
  color: var(--ink);
  font-weight: 600;
}

.panel__tab.is-active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--accent);
  border-radius: var(--radius-full);
}

.panel__body {
  padding: var(--space-5);
}

.panel__idle {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--paper-dim);
  border: 1px dashed var(--rule-strong);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--ink-muted);
}

.panel__idle-actions {
  display: flex;
  gap: var(--space-2);
}

/* ---------------------------- 结果 -------------------------------- */
.result {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.result__banner {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  border: 1px solid var(--warn-edge);
  background: var(--warn-wash);
  color: var(--warn-ink);
}

.result__banner.is-ok {
  border-color: var(--ok-edge);
  background: var(--ok-wash);
  color: var(--ok-ink);
}

.result__verdict {
  font-size: var(--text-base);
  font-weight: 600;
}

.result__sub {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

/* 天数进度条 */
.gauge {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.gauge__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
}

.gauge__nums {
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

.gauge__track {
  height: 5px;
  background: var(--paper-sunken);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.gauge__fill {
  height: 100%;
  background: var(--warn-ink);
  border-radius: var(--radius-full);
  transition: width var(--dur) var(--ease);
}

.gauge__fill.is-ok {
  background: var(--ok-ink);
}

.gauge__note {
  font-size: var(--text-xs);
}

/* 材料清单 */
.lists {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-5);
}

.list-block__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.list-block__n {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  font-size: var(--text-2xs);
  color: var(--ink-muted);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-xs);
}

.list-block__items {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.list-block__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: var(--border);
  border-radius: var(--radius-sm);
  background: var(--paper-raised);
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

.list-block__item.is-missing {
  color: var(--bad-ink);
  background: var(--bad-wash);
  border-color: var(--bad-edge);
}

.list-block__none {
  font-size: var(--text-sm);
  color: var(--ink-faint);
}

/* 程序清单 */
.proc {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.proc__item {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: var(--border);
  border-radius: var(--radius-sm);
  background: var(--paper-raised);
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

.proc__idx {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  flex: none;
  font-size: var(--text-2xs);
  font-weight: 600;
  color: var(--ink-muted);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-xs);
  transform: translateY(1px);
}

/* 待人工确认 */
.blockers {
  padding: var(--space-3) var(--space-4);
  background: var(--warn-wash);
  border: 1px solid var(--warn-edge);
  border-radius: var(--radius-sm);
}

.blockers__title {
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--warn-ink);
}

.blockers ul {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-left: var(--space-4);
  list-style: disc;
}

.blockers li {
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

/* 事实表 */
.facts {
  display: flex;
  flex-direction: column;
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.facts__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border);
  background: var(--paper-raised);
}

.facts__row:last-child {
  border-bottom: 0;
}

.facts__row dt {
  font-size: var(--text-sm);
  color: var(--ink-muted);
}

.facts__row dd {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
}

/* 待办 */
.todos {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.todos__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: var(--border);
  border-radius: var(--radius-sm);
  background: var(--paper-raised);
}

.todos__text {
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

.note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

/* ---------------------------- 响应式 ------------------------------ */
@media (max-width: 1000px) {
  .mem__grid {
    grid-template-columns: 1fr;
  }

  .roster__list {
    max-height: 300px;
  }
}

@media (max-width: 720px) {
  .mem {
    padding: var(--space-4) var(--space-4) var(--space-10);
  }

  .work__head {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-4);
  }

  .panel__tabs {
    gap: var(--space-4);
    overflow-x: auto;
  }

  .panel__body {
    padding: var(--space-4);
  }
}
</style>
