<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  checkQualification,
  createMember,
  downloadRoster,
  downloadRosterTemplate,
  getTodoSuggestions,
  getTransitionSuggestion,
  importRoster,
  listMembers,
  listMemberOrganizations,
} from '@/api/member'
import { ApiError } from '@/api/http'
import { memberDevelopmentApi, type RosterStats } from '@/api/member-development'
import { linkMemberAccount, listSubmittedMaterials, downloadMaterial, MATERIAL_CATEGORIES, type MaterialList, type PersonalMaterial } from '@/api/member-self'
import type {
  MemberStage,
  MemberRosterItem,
  MemberOrgOption,
  QualificationResult,
  RosterImportReport,
  TodoItem,
  TodoSuggestionsResponse,
  TransitionSuggestion,
} from '@/api/types'
import { STAGE_LABELS, STAGE_ORDER, TODO_CATEGORY_LABELS, RELATION_STATUS_LABELS, RELATION_STATUS_TONE } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import MemberFilePanel from '@/components/members/MemberFilePanel.vue'
import MemberProcessWorkspace from '@/components/members/MemberProcessWorkspace.vue'
import TransferPanel from '@/components/members/TransferPanel.vue'
import UpperReportPanel from '@/components/members/UpperReportPanel.vue'
import { session } from '@/stores/session'
import { downloadBlob, todayISO } from '@/utils/files'

/**
 * 党员发展。
 *
 * 本页是全项目**合规红线最密集**的界面，因此版面也最克制：
 *   - 顶部常驻决策边界声明（对应 app/schemas/member.py::DECISION_BOUNDARY_NOTE 的语义）
 *   - 所有校验结果都标注为"建议 / 待人工确认"，绝不出现"通过""不通过"这类结论性动词
 *   - 人工办理必须记录依据、日期和意见，规则分析不触发阶段流转
 *
 * 名册与人工登记按登录组织范围查询，规则分析不修改人员阶段。
 */

type PanelTab = 'qualification' | 'transition' | 'todo'

const members = ref<MemberRosterItem[]>([])
const loading = ref(true)
const rosterError = ref<unknown>(null)
const total = ref(0)
const page = ref(1)
const pageSize = 40
const selectedId = ref<string | null>(null)
const workspace = ref('profiles')
const flowBusy = ref(false)
const rosterYear = ref('')
const rosterBatch = ref('')
const rosterOrg = ref('')
const rosterIncludeTransferred = ref(false)
const rosterStats = ref<RosterStats | null>(null)
const rosterStatsError = ref('')
const workspaces = [{ key: 'profiles', label: '人员档案' }, { key: 'transfers', label: '组织关系接转' }, { key: 'upper-reports', label: '上级审批备案' }, { key: 'batches', label: '年度批次' }, { key: 'reminders', label: '提醒待办' }, { key: 'votes', label: '多轮选优' }]
const panelTab = ref<PanelTab>('qualification')

const qualification = ref<QualificationResult | null>(null)
const transition = ref<TransitionSuggestion | null>(null)
const todos = ref<TodoSuggestionsResponse | null>(null)

const busy = ref<null | PanelTab>(null)
const panelError = ref<unknown>(null)
const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const createSuccess = ref('')
const organizations = ref<MemberOrgOption[]>([])
const organizationsLoading = ref(false)
const organizationsError = ref<unknown>(null)
const canCreate = computed(() => session.can('member.stage_transition'))
const registration = reactive({
  name: '', org_unit_id: '', current_stage: 'applicant' as MemberStage,
  stage_joined_on: '', materials: '', pending: 0,
})
const registrationValid = computed(() => registration.name.trim().length > 0 && registration.org_unit_id.length > 0)

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
const personalOpen = ref(false)
const personalBusy = ref(false)
const personalError = ref<unknown>(null)
const personalMessage = ref('')
const accountUsername = ref('')
const submittedMaterials = ref<MaterialList | null>(null)
const materialPage = ref(1)

async function loadSubmitted(): Promise<void> {
  if (!selected.value) return
  personalBusy.value = true
  personalError.value = null
  const id = selected.value.id
  try {
    const data = await listSubmittedMaterials(id, materialPage.value)
    if (selected.value?.id === id) submittedMaterials.value = data
  } catch (error) { if (selected.value?.id === id) personalError.value = error }
  finally { personalBusy.value = false }
}

function openPersonal(): void {
  personalOpen.value = !personalOpen.value
  if (personalOpen.value) void loadSubmitted()
}

async function linkAccount(): Promise<void> {
  if (!selected.value || !accountUsername.value.trim() || personalBusy.value) return
  personalBusy.value = true
  personalError.value = null
  const id = selected.value.id
  try {
    const profile = await linkMemberAccount(id, accountUsername.value.trim())
    const index = members.value.findIndex((member) => member.id === id)
    if (index >= 0) members.value[index] = profile
    if (selected.value?.id === id) personalMessage.value = '账号已关联，党员可登录查看本人档案并提交材料。'
  } catch (error) { if (selected.value?.id === id) personalError.value = error }
  finally { personalBusy.value = false }
}

async function downloadSubmitted(material: PersonalMaterial): Promise<void> {
  if (!selected.value || personalBusy.value) return
  personalBusy.value = true
  personalError.value = null
  try { await downloadMaterial(material, selected.value.id) }
  catch (error) { personalError.value = error }
  finally { personalBusy.value = false }
}

function turnMaterialPage(delta: number): void { materialPage.value += delta; void loadSubmitted() }

/** 可选目标阶段：只允许流程中的下一步，避免出现"跳级"这种不存在的情形 */
const targetOptions = computed(() => {
  const cur = selected.value?.stage
  if (!cur) return []
  const i = STAGE_ORDER.indexOf(cur)
  if (i < 0) return []
  return STAGE_ORDER.slice(i + 1).map((s) => ({ value: s, label: STAGE_LABELS[s] }))
})

let rosterSequence = 0

/** 名册统计：与名册列表同一组筛选（年度 / 批次 / 组织）——两处口径必须一致 */
async function loadStats(): Promise<void> {
  rosterStatsError.value = ''
  try {
    rosterStats.value = await memberDevelopmentApi.stats({
      year: rosterYear.value ? Number(rosterYear.value) : undefined,
      batch_no: rosterBatch.value.trim() || undefined,
      org_unit_id: rosterOrg.value || undefined,
    })
  } catch (error) {
    rosterStats.value = null
    rosterStatsError.value = error instanceof ApiError ? error.message : '名册统计暂时取不到，请稍后重试'
  }
}

const statsStageText = computed(() => {
  const stats = rosterStats.value
  if (!stats) return ''
  const order: MemberStage[] = [...STAGE_ORDER, 'rejected']
  return order
    .filter((stage) => (stats.by_stage[stage] ?? 0) > 0)
    .map((stage) => `${STAGE_LABELS[stage]} ${stats.by_stage[stage]}`)
    .join(' · ')
})

async function load(): Promise<void> {
  const sequence = ++rosterSequence
  loading.value = true
  rosterError.value = null
  try {
    const response = await listMembers({ page: page.value, page_size: pageSize, year: rosterYear.value ? Number(rosterYear.value) : undefined, batch_no: rosterBatch.value.trim() || undefined, org_unit_id: rosterOrg.value || undefined, include_transferred: rosterIncludeTransferred.value || undefined })
    if (sequence !== rosterSequence) return
    members.value = response.items
    total.value = response.total
    const current = members.value.find((member) => member.id === selectedId.value) ?? members.value[0]
    if (current) select(current.id)
    else selectedId.value = null
    void loadStats()
  } catch (error) {
    if (sequence === rosterSequence) rosterError.value = error
  } finally {
    if (sequence === rosterSequence) loading.value = false
  }
}

async function loadOrganizations(): Promise<void> {
  organizationsLoading.value = true
  organizationsError.value = null
  try {
    organizations.value = await listMemberOrganizations()
    registration.org_unit_id = organizations.value.some((org) => org.id === session.state.user?.org_unit_id)
      ? session.state.user!.org_unit_id! : ''
  } catch (error) {
    organizationsError.value = error
  } finally {
    organizationsLoading.value = false
  }
}

onMounted(() => { void load(); void loadOrganizations() })

function turnPage(delta: number): void {
  page.value += delta
  void load()
}

function selectBatch(year: number, batch: string): void {
  rosterYear.value = String(year)
  rosterBatch.value = batch
  page.value = 1
  workspace.value = 'profiles'
  void load()
}

async function registerMember(): Promise<void> {
  if (!registrationValid.value || creating.value) return
  creating.value = true
  createError.value = ''
  createSuccess.value = ''
  try {
    const created = await createMember({
      name: registration.name.trim(), org_unit_id: registration.org_unit_id,
      current_stage: registration.current_stage, stage_joined_on: registration.stage_joined_on || undefined,
      materials: registration.materials.split('\n').map((name) => name.trim()).filter(Boolean),
      pending: registration.pending,
    })
    createSuccess.value = `已登记：${created.name}。规则分析仅提供建议，阶段变更仍须人工确认。`
    Object.assign(registration, { name: '', current_stage: 'applicant', stage_joined_on: '', materials: '', pending: 0 })
    createOpen.value = false
    selectedId.value = created.id
    page.value = 1
    await load()
  } catch (error) {
    createError.value = error instanceof ApiError ? error.message : '登记失败，请重试'
  } finally {
    creating.value = false
  }
}

/* ---------- 名册模板 / 导入 / 导出（T-DATA-06） ---------- */

const rosterIoBusy = ref<'' | 'template' | 'export'>('')
const rosterIoError = ref('')
const importOpen = ref(false)
const importFile = ref<File | null>(null)
const importNote = ref('')
const importing = ref(false)
const importError = ref('')
const importReport = ref<RosterImportReport | null>(null)
const importDone = ref('')

/** 逐行报告最多展示 200 行，其余只计入合计：避免一次导入上千行把页面拖死 */
const REPORT_ROWS = 200
const importVisibleRows = computed(() => (importReport.value ? importReport.value.rows.slice(0, REPORT_ROWS) : []))
const importHiddenRows = computed(() => Math.max(0, (importReport.value?.rows.length ?? 0) - REPORT_ROWS))
const importValid = computed(() => Boolean(importFile.value) && importNote.value.trim().length >= 4)
const canConfirmImport = computed(() => Boolean(importReport.value?.dry_run && importReport.value.created > 0 && !importing.value))

function importStatusLabel(status: RosterImportReport['rows'][number]['status'], dryRun: boolean): string {
  if (status === 'created') return dryRun ? '可登记' : '已登记'
  if (status === 'skipped') return '已存在'
  return '不能导入'
}

async function fetchTemplate(): Promise<void> {
  if (rosterIoBusy.value) return
  rosterIoBusy.value = 'template'
  rosterIoError.value = ''
  try {
    downloadBlob(await downloadRosterTemplate(), '名册导入模板.xlsx')
  } catch (error) {
    rosterIoError.value = error instanceof ApiError ? error.message : '模板下载失败，请重试'
  } finally {
    rosterIoBusy.value = ''
  }
}

async function exportRoster(): Promise<void> {
  if (rosterIoBusy.value) return
  rosterIoBusy.value = 'export'
  rosterIoError.value = ''
  try {
    const blob = await downloadRoster({
      year: rosterYear.value ? Number(rosterYear.value) : undefined,
      batch_no: rosterBatch.value.trim() || undefined,
      org_unit_id: rosterOrg.value || undefined,
      include_transferred: rosterIncludeTransferred.value || undefined,
    })
    const scope = rosterOrg.value || rosterYear.value || rosterBatch.value ? '筛选范围' : '全部'
    downloadBlob(blob, `名册导出-${scope}-${todayISO()}.xlsx`)
  } catch (error) {
    rosterIoError.value = error instanceof ApiError ? error.message : '导出失败，请重试'
  } finally {
    rosterIoBusy.value = ''
  }
}

function chooseImportFile(event: Event): void {
  importFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
  importReport.value = null
  importError.value = ''
  importDone.value = ''
}

async function runImport(dryRun: boolean): Promise<void> {
  if (!importValid.value || importing.value) return
  importing.value = true
  importError.value = ''
  importDone.value = ''
  try {
    const report = await importRoster(importFile.value!, importNote.value.trim(), dryRun)
    importReport.value = report
    if (!dryRun) {
      importDone.value = `本次登记 ${report.created} 人，已存在 ${report.skipped} 人，未导入 ${report.failed} 行。`
      page.value = 1
      await load()
    }
  } catch (error) {
    importError.value = error instanceof ApiError ? error.message : '导入失败，请重试'
  } finally {
    importing.value = false
  }
}

function select(id: string): void {
  personalOpen.value = false
  personalError.value = null
  personalMessage.value = ''
  accountUsername.value = ''
  submittedMaterials.value = null
  materialPage.value = 1
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
    todos.value = await getTodoSuggestions({
      current_stage: selected.value.stage, materials: [...form.materials], days_in_stage: form.days_in_stage,
    })
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
      description="登记年度批次、材料和培养记录，依组织决定完成人工办理。规则建议与评分需人工核对。"
    >
      <template #actions>
        <button v-if="canCreate" class="btn btn--primary" type="button" :disabled="creating || busy !== null" @click="createOpen = !createOpen">
          <AppIcon name="plus" :size="14" /><span>登记培养对象</span>
        </button>
        <button v-if="canCreate" class="btn btn--quiet" type="button" :disabled="rosterIoBusy !== '' || loading || creating || busy !== null" @click="fetchTemplate">
          <AppIcon name="download" :size="14" /><span>{{ rosterIoBusy === 'template' ? '下载中' : '下载模板' }}</span>
        </button>
        <button v-if="canCreate" class="btn btn--quiet" type="button" :disabled="rosterIoBusy !== '' || loading || creating || busy !== null" @click="exportRoster">
          <AppIcon name="download" :size="14" /><span>{{ rosterIoBusy === 'export' ? '导出中' : '导出名册' }}</span>
        </button>
        <button v-if="canCreate" class="btn btn--quiet" type="button" :disabled="creating || busy !== null" @click="importOpen = !importOpen">
          <AppIcon name="upload" :size="14" /><span>导入名册</span>
        </button>
        <button class="btn btn--quiet" type="button" :disabled="loading || creating || busy !== null" @click="load">
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
          阶段决定须由具备权限的组织人员依规登记。规则建议与评分不构成组织认定或选拔结论。
        </p>
      </div>
    </section>

    <WorkspaceTabs v-model="workspace" :items="workspaces" label="党员发展工作区" :disabled="flowBusy || creating || busy !== null">
    <div v-if="workspace === 'profiles'" class="wb-stack">
    <form class="wb-actions" @submit.prevent="page = 1; load()">
      <label class="wb-field"><span id="roster-org-label">支部</span><select id="roster-org" aria-labelledby="roster-org-label" v-model="rosterOrg" class="select" :disabled="organizationsLoading || loading || flowBusy" @change="page = 1; load()"><option value="">全部支部（权限范围内）</option><option v-for="org in organizations" :key="org.id" :value="org.id">{{ org.name }}</option></select></label>
      <label class="wb-field"><span>名册年度</span><input v-model="rosterYear" class="input" type="number" min="2000" max="2100" placeholder="全部年度" /></label>
      <label class="wb-field"><span>批次号</span><input v-model="rosterBatch" class="input" maxlength="20" placeholder="全部批次" /></label>
      <label class="wb-check"><input v-model="rosterIncludeTransferred" type="checkbox" :disabled="loading || flowBusy" @change="page = 1; load()" /><span>含组织关系已转出人员</span></label>
      <button class="btn btn--ghost" type="submit" :disabled="loading || flowBusy">查询名册</button>
      <button v-if="rosterOrg || rosterYear || rosterBatch || rosterIncludeTransferred" class="btn btn--quiet" type="button" :disabled="loading || flowBusy" @click="rosterOrg = ''; rosterYear = ''; rosterBatch = ''; rosterIncludeTransferred = false; page = 1; load()">清除筛选</button>
    </form>
    <p v-if="rosterStats" class="u-meta" role="status">当前筛选共 <strong>{{ rosterStats.total }}</strong> 人<template v-if="statsStageText">：{{ statsStageText }}</template><template v-if="rosterIncludeTransferred">（含组织关系已转出人员）</template></p>
    <p v-else-if="rosterStatsError" class="field__error" role="alert">{{ rosterStatsError }}</p>
    <p v-if="rosterIoError" class="field__error is-preline" role="alert">{{ rosterIoError }}</p>
    <p v-if="createSuccess" role="status">{{ createSuccess }}</p>
    <section v-if="createOpen && canCreate" class="u-card registration">
      <header class="u-panel-head"><h2 class="roster__title">人工登记培养对象</h2></header>
      <form class="registration__body" @submit.prevent="registerMember">
        <div class="form-grid">
          <div class="field"><label for="new-name" class="field__label">姓名</label><input id="new-name" v-model="registration.name" class="input" maxlength="50" required /></div>
          <div class="field">
            <label for="new-org" class="field__label">所属组织</label>
            <select id="new-org" v-model="registration.org_unit_id" class="select" :disabled="organizationsLoading" required>
              <option value="">请选择组织</option><option v-for="org in organizations" :key="org.id" :value="org.id">{{ org.name }}</option>
            </select>
          </div>
          <div class="field"><label for="new-stage" class="field__label">已确认的当前阶段</label><select id="new-stage" v-model="registration.current_stage" class="select"><option v-for="stage in STAGE_ORDER" :key="stage" :value="stage">{{ STAGE_LABELS[stage] }}</option></select></div>
          <div class="field"><label for="new-date" class="field__label">进入阶段日期（留空为今天）</label><input id="new-date" v-model="registration.stage_joined_on" class="input" type="date" /></div>
          <div class="field"><label for="new-pending" class="field__label">待办数</label><input id="new-pending" v-model.number="registration.pending" class="input" type="number" min="0" max="2147483647" /></div>
        </div>
        <div class="field"><label for="new-materials" class="field__label">已具备材料（每行一项）</label><textarea id="new-materials" v-model="registration.materials" class="textarea" rows="3"></textarea></div>
        <ErrorState v-if="organizationsError" :error="organizationsError"><button class="btn btn--ghost" type="button" @click="loadOrganizations">重试组织查询</button></ErrorState>
        <p v-else-if="!organizationsLoading && !organizations.length" role="status">账号没有可登记的有效组织，请联系管理员绑定组织。</p>
        <p v-if="createError" class="field__error" role="alert">{{ createError }}</p>
        <button class="btn btn--primary" type="submit" :disabled="!registrationValid || creating">{{ creating ? '保存中' : '保存登记' }}</button>
      </form>
    </section>

    <!-- 名册批量导入（T-DATA-06）：先预检、再确认落库 -->
    <section v-if="importOpen && canCreate" class="u-card registration">
      <header class="u-panel-head"><h2 class="roster__title">按模板批量导入名册</h2></header>
      <form class="registration__body" @submit.prevent="runImport(true)">
        <p class="u-meta">
          先「下载模板」按列填写，再在这里上传预检：系统逐行报告“可登记 / 已存在 / 不能导入（原因）”，
          确认无误后再落库。导入只登记台账，<strong>不改动已有人员的当前阶段</strong>；阶段变更仍须走人工流转。
        </p>
        <div class="form-grid">
          <div class="field">
            <label for="import-file" class="field__label">名册文件（.xlsx）</label>
            <input id="import-file" class="input" type="file" accept=".xlsx" :disabled="importing" @change="chooseImportFile" />
          </div>
          <div class="field">
            <label for="import-note" class="field__label">名册来源说明（4–200 字，会写入审计记录）</label>
            <input id="import-note" v-model="importNote" class="input" maxlength="200" placeholder="例如：12371 导出 2026-10-16" />
          </div>
        </div>
        <p v-if="importError" class="field__error is-preline" role="alert">{{ importError }}</p>
        <p v-if="importDone" role="status">{{ importDone }}</p>
        <div class="registration__actions">
          <button class="btn btn--ghost" type="submit" :disabled="!importValid || importing">{{ importing ? '处理中' : '预检（不写库）' }}</button>
          <button v-if="canConfirmImport" class="btn btn--primary" type="button" :disabled="!importValid || importing" @click="runImport(false)">
            确认导入 {{ importReport?.created ?? 0 }} 人
          </button>
        </div>
        <div v-if="importReport" class="import-report">
          <p role="status">
            共 {{ importReport.total_rows }} 行：{{ importReport.dry_run ? '可登记' : '已登记' }} {{ importReport.created }}，已存在 {{ importReport.skipped }}，不能导入 {{ importReport.failed }}
          </p>
          <div class="import-report__scroll">
            <table class="import-report__table">
              <thead><tr><th>行</th><th>姓名</th><th>结果</th><th>说明</th></tr></thead>
              <tbody>
                <tr v-for="row in importVisibleRows" :key="row.row">
                  <td>{{ row.row }}</td>
                  <td>{{ row.name || '—' }}</td>
                  <td>{{ importStatusLabel(row.status, importReport.dry_run) }}</td>
                  <td class="import-report__message">{{ row.message || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="importHiddenRows" class="u-meta">另有 {{ importHiddenRows }} 行未逐行显示，已计入上方合计。</p>
          <p class="u-meta">{{ importReport.note }}</p>
        </div>
      </form>
    </section>

    <div class="mem__grid">
      <!-- ---------------------------- 名册 ---------------------------- -->
      <section class="roster u-card">
        <header class="u-panel-head">
          <h2 class="roster__title">培养对象</h2>
          <span class="badge">{{ total }}</span>
        </header>

        <LoadingBlock v-if="loading" variant="list" :rows="5" />

        <ErrorState v-else-if="rosterError" :error="rosterError"><button class="btn btn--ghost" type="button" @click="load">重试名册查询</button></ErrorState>

        <div v-else-if="!members.length" class="roster__body">
          <EmptyState icon="people" title="暂无培养对象" body="当前组织范围内尚无台账，可由具备权限的组织人员登记。" />
        </div>

        <ul v-else class="roster__list">
          <li v-for="m in members" :key="m.id">
            <button
              class="roster__item"
              :class="{ 'is-active': selectedId === m.id }"
              type="button"
              :aria-pressed="selectedId === m.id"
              :disabled="busy !== null || creating || flowBusy"
              @click="select(m.id)"
            >
              <span class="roster__row">
                <span class="roster__name">{{ m.name }}</span>
                <span class="badge">{{ STAGE_LABELS[m.stage] }}</span>
                <span
                  v-if="m.relation_status && m.relation_status !== 'in_place'"
                  class="badge"
                  :class="RELATION_STATUS_TONE[m.relation_status] === 'quiet' ? '' : `badge--${RELATION_STATUS_TONE[m.relation_status]}`"
                  :title="`组织关系：${RELATION_STATUS_LABELS[m.relation_status]}`"
                >{{ RELATION_STATUS_LABELS[m.relation_status] }}</span>
              </span>
              <span class="roster__org">{{ m.org_name }}</span>
              <span class="roster__meta">
                <span class="u-meta">在阶段 {{ m.days_in_stage }} 天</span>
                <span v-if="m.pending" class="badge badge--warn">待办 {{ m.pending }}</span>
              </span>
            </button>
          </li>
        </ul>
        <div v-if="!loading && !rosterError && total > pageSize" class="roster__body">
          <span class="u-meta">第 {{ page }} 页</span>
          <button class="btn btn--quiet" :disabled="page <= 1 || busy !== null || creating" @click="turnPage(-1)">上一页</button>
          <button class="btn btn--quiet" :disabled="page * pageSize >= total || busy !== null || creating" @click="turnPage(1)">下一页</button>
        </div>
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

          <MemberFilePanel :key="selected.id" :profile-id="selected.id" @updated="load" @busy="flowBusy = $event" />
          <details class="wb-disclosure"><summary>材料与时限辅助核对</summary>
          <!-- 校验输入 -->
          <section class="personal-submissions">
            <button class="btn btn--ghost" :aria-expanded="personalOpen" @click="openPersonal">账号与个人提交</button>
            <div v-if="personalOpen" class="personal-submissions__body">
              <h3>本人档案账号关联</h3>
              <p v-if="selected.user_id" class="u-meta">已关联党员登录账号。</p>
              <template v-else-if="canCreate">
                <label class="field" for="account-username">党员登录账号<input id="account-username" v-model="accountUsername" class="input" maxlength="50" placeholder="同一组织内的党员或申请人账号" :disabled="personalBusy" /></label>
                <button class="btn btn--primary" :disabled="!accountUsername.trim() || personalBusy" @click="linkAccount">关联本人档案</button>
              </template>
              <p v-else class="u-meta">尚未关联账号，请联系具备人员维护权限的组织管理员。</p>
              <p v-if="personalMessage" role="status">{{ personalMessage }}</p>
              <ErrorState v-if="personalError" :error="personalError" />
              <h3>党员提交材料</h3>
              <p class="u-meta">提交原件供组织核验，不自动计入已具备材料清单。</p>
              <LoadingBlock v-if="personalBusy" variant="list" :rows="2" />
              <template v-else>
                <p v-if="!submittedMaterials?.items.length" class="u-meta">暂无个人提交材料。</p>
                <article v-for="material in submittedMaterials?.items" :key="material.id">
                  <strong>{{ material.title }}</strong><p class="u-meta">{{ MATERIAL_CATEGORIES[material.category] }} · {{ material.file_name }} · 已提交，待组织核验</p>
                  <p v-if="material.description">{{ material.description }}</p>
                  <button class="btn btn--ghost" @click="downloadSubmitted(material)">下载提交原件</button>
                </article>
                <div v-if="submittedMaterials && submittedMaterials.total > 20">
                  <button class="btn btn--ghost" :disabled="materialPage === 1" @click="turnMaterialPage(-1)">上一页材料</button>
                  <span>第 {{ materialPage }} 页</span>
                  <button class="btn btn--ghost" :disabled="materialPage * 20 >= submittedMaterials.total" @click="turnMaterialPage(1)">下一页材料</button>
                </div>
                <button v-if="personalError" class="btn btn--ghost" @click="loadSubmitted">重试材料查询</button>
              </template>
            </div>
          </section>
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
          </details>
        </template>
      </section>
    </div>
    </div>
    <div v-else-if="workspace === 'transfers'" class="wb-stack">
      <TransferPanel :organizations="organizations" @busy="flowBusy = $event" @changed="load()" />
    </div>
    <div v-else-if="workspace === 'upper-reports'" class="wb-stack">
      <UpperReportPanel @busy="flowBusy = $event" />
    </div>
    <MemberProcessWorkspace v-else :mode="workspace" :organizations="organizations" @select-batch="selectBatch" @busy="flowBusy = $event" />
    </WorkspaceTabs>
  </div>
</template>

<style scoped>
.personal-submissions { padding: var(--space-4); border-bottom: var(--border); }
.personal-submissions__body { display: flex; flex-direction: column; gap: var(--space-3); padding-top: var(--space-4); }
.personal-submissions__body .btn { align-self: flex-start; }
.personal-submissions__body article { padding: var(--space-3); border: var(--border); overflow-wrap: anywhere; }
.registration__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
}

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

.gap-note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
  background: var(--warn-wash);
  border: 1px solid var(--warn-edge);
  border-radius: var(--radius-sm);
}

.gap-note b {
  font-weight: 600;
  color: var(--warn-ink);
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

.work > .wb,
.work > .wb-disclosure {
  padding: var(--space-5);
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

/* ---------------------------- 名册导入报告（T-DATA-06） ---------------------------- */
.registration__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.import-report {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.import-report__scroll {
  max-height: 22rem;
  overflow: auto;
  border: var(--border);
  border-radius: var(--radius-sm);
}

.import-report__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.import-report__table th,
.import-report__table td {
  padding: var(--space-1) var(--space-2);
  border-bottom: var(--border);
  text-align: left;
  vertical-align: top;
}

.import-report__table thead th {
  position: sticky;
  top: 0;
  background: var(--surface-2, #fff);
}

/* 逐行说明可能含“①②③”式多行提示，必须按行显示 */
.import-report__message,
.field__error.is-preline {
  white-space: pre-line;
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
