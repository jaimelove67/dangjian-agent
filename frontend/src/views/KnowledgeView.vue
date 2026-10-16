<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import { confirmDocumentMaintenance, createDocument, deleteDocument, listDocuments, reviewDocument, updateDocumentStatus, replaceDocumentContent } from '@/api/knowledge'
import { ApiError } from '@/api/http'
import type {
  DocumentResponse,
  DocAuthority,
  DocLevel,
  DocReviewStatus,
  DocStatus,
  DocValidity,
  DataLevel,
} from '@/api/types'
import {
  DATA_LEVEL_LABELS,
  DOC_AUTHORITY_LABELS,
  DOC_LEVEL_LABELS,
  DOC_REVIEW_DUE_LABEL,
  DOC_REVIEW_DUE_TONE,
  DOC_REVIEW_STATUS_LABELS,
  DOC_REVIEW_STATUS_TONE,
  DOC_STATUS_LABELS,
  DOC_STATUS_TONE,
  DOC_VALIDITY_LABELS,
  DOC_VALIDITY_TONE,
  DOC_VISIBILITY_LABELS,
  PERM,
} from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import DocumentTools from '@/components/knowledge/DocumentTools.vue'
import { session } from '@/stores/session'

/**
 * 知识库查询与管理。查询用户只读，维护操作须具备 knowledge.manage 权限。
 *
 * ⚠️ Section 13 边界声明：本页属于 taste-skill 明确不覆盖的「数据表 / 管理面板」
 *    类型。因此本页**不套用**展示型审美规则（大留白、非对称栅格、编辑式标题），
 *    而是采用**保守的数据表设计**：粘性表头、克制行高、密度可切换、右侧详情抽屉。
 *    仅复用设计系统的色彩、字阶与圆角 token，以保证与全站同源。
 *
 * 列表、上传和状态均来自真实接口，查询范围由后端鉴权决定。
 */

type Tab = 'all' | DocStatus

const canManage = computed(() => session.can(PERM.KNOWLEDGE_MANAGE))
const canReview = computed(() => session.can(PERM.KNOWLEDGE_REVIEW))
const docs = ref<DocumentResponse[]>([])
const loading = ref(true)
const error = ref<unknown>(null)
const tab = ref<Tab>('all')
const keyword = ref('')
const levelFilter = ref<DocLevel | 'all'>('all')
/** 审核状态筛选：仅具备 knowledge.review 的管理员使用，默认不附加筛选 */
const reviewFilter = ref<DocReviewStatus | 'all'>('all')
/** 复核期限筛选（T-KB-13）：只看已到复核期限的条目，默认不附加筛选 */
const dueFilter = ref<'all' | 'due'>('all')
const compact = ref(false)
const selected = ref<DocumentResponse | null>(null)
const detail = ref<HTMLElement | null>(null)
const statusBusy = ref<string | null>(null)
const uploadOpen = ref(false)
const replacement = ref<File | null>(null)
const replacementBusy = ref(false)
const replacementMessage = ref('')
watch(selected, () => { replacement.value = null; replacementMessage.value = '' })

function chooseReplacement(event: Event): void {
  if (!canManage.value) return
  replacement.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function replaceContent(): Promise<void> {
  if (!canManage.value || !selected.value || !replacement.value) return
  replacementBusy.value = true
  try {
    const response = await replaceDocumentContent(selected.value, replacement.value)
    selected.value = response.document
    await load()
    replacementMessage.value = '文件已更新，新片段需重新向量化。'
  } catch (err) {
    replacementMessage.value = err instanceof ApiError ? err.message : '文件更新失败'
  } finally {
    replacementBusy.value = false
  }
}
const page = ref(1)
const total = ref(0)
const pageSize = 40
const counts = ref<Record<Tab, number>>({ all: 0, effective: 0, expired: 0, abolished: 0 })
let requestSequence = 0

async function load(): Promise<void> {
  const sequence = ++requestSequence
  loading.value = true
  error.value = null
  try {
    const response = await listDocuments({
      page: page.value, page_size: pageSize, q: keyword.value.trim() || undefined,
      status: tab.value === 'all' ? undefined : tab.value,
      level: levelFilter.value === 'all' ? undefined : levelFilter.value,
      review_status: reviewFilter.value === 'all' ? undefined : reviewFilter.value,
      due_for_review: dueFilter.value === 'all' ? undefined : true,
    })
    if (sequence !== requestSequence) return
    docs.value = response.items
    total.value = response.total
    counts.value = { all: 0, effective: 0, expired: 0, abolished: 0, ...response.counts }
  } catch (err) {
    if (sequence === requestSequence) error.value = err
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

onMounted(load)

const filtered = computed(() => docs.value)

/**
 * 是否由用户主动设置了筛选。
 *
 * 空列表有两种完全不同的成因：筛掉了，或当前账号的授权范围内本就没有文件。
 * 前者提示"换个关键词"有用，后者只会让人反复尝试——必须分开说明。
 */
const hasActiveFilter = computed(
  () =>
    keyword.value.trim() !== '' ||
    levelFilter.value !== 'all' ||
    tab.value !== 'all' ||
    reviewFilter.value !== 'all' ||
    dueFilter.value !== 'all',
)

/**
 * 授权范围为空时的说明。
 *
 * 申请人的可见范围按需求 §4.1 只有"公开"一级，制度目录天然为空——这时必须
 * 直接讲清限制来自角色，否则用户只会反复换关键词找一个不可能出现的结果。
 */
const emptyScopeBody = computed(() =>
  session.state.user?.role === 'applicant'
    ? '按权限设定，申请人只能查阅公开制度，当前尚未上传公开制度。如需查阅某项制度，请联系所在党支部或院系管理员。'
    : '可查阅范围由你的角色与所属组织决定；如需查阅某项制度，请联系所在党支部或院系管理员。',
)
let searchTimer: number | undefined
watch([tab, keyword, levelFilter, reviewFilter, dueFilter], () => {
  page.value = 1
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void load() }, 200)
})
function turnPage(delta: number): void {
  page.value += delta
  void load()
}

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'effective', label: '有效' },
  { key: 'expired', label: '已失效' },
  { key: 'abolished', label: '已废止' },
]

function statusTone(s: DocStatus): string {
  return `badge--${DOC_STATUS_TONE[s]}`
}

/** 效力状态徽标：只有"现行有效"可以单独作为问答依据（T-DATA-05） */
function validityTone(v: DocValidity): string {
  return `badge--${DOC_VALIDITY_TONE[v]}`
}

/** 权威来源徽标：参考资料不能作为唯一依据 */
function authorityTone(a: DocAuthority): string {
  return a === 'reference' ? 'badge--warn' : 'badge--ok'
}

function reviewTone(s: DocReviewStatus): string {
  return `badge--${DOC_REVIEW_STATUS_TONE[s]}`
}

/** 时效提醒：距失效不足 30 天时提示，与后端 retrieval_strategy 的告警窗口一致 */
function expiringSoon(d: DocumentResponse): boolean {
  if (!d.expiration_date || d.status !== 'effective') return false
  const end = new Date(d.expiration_date).getTime()
  if (Number.isNaN(end)) return false
  const days = (end - Date.now()) / 86400000
  return days >= 0 && days <= 30
}

async function changeStatus(doc: DocumentResponse, status: DocStatus): Promise<void> {
  if (!canManage.value) return
  statusBusy.value = doc.doc_id
  try {
    await updateDocumentStatus(doc.doc_id, status)
    // 接口成功后再改本地视图，避免"看起来成功但后端没落库"
    doc.status = status
    await load()
  } catch (err) {
    error.value = err
  } finally {
    statusBusy.value = null
  }
}

/** 待移除文件；用站内确认弹窗替代 window.confirm，保持设计语言一致 */
const removing = ref<DocumentResponse | null>(null)

function askRemove(doc: DocumentResponse): void {
  if (!canManage.value) return
  removing.value = doc
}

async function confirmRemove(): Promise<void> {
  const doc = removing.value
  if (!doc) return
  statusBusy.value = doc.doc_id
  try {
    await deleteDocument(doc.doc_id)
    if (selected.value?.doc_id === doc.doc_id) selected.value = null
    if (docs.value.length === 1 && page.value > 1) page.value -= 1
    removing.value = null
    await load()
  } catch (err) {
    error.value = err
  } finally {
    statusBusy.value = null
  }
}

async function selectDocument(doc: DocumentResponse): Promise<void> {
  selected.value = doc
  await nextTick()
  detail.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/**
 * 元数据修正后同步表格行与详情面板。
 *
 * 接口已返回最新文档，无需重新拉列表；只更新对应行，避免整页重载导致
 * 详情面板被重新挂载、用户填写的表单状态丢失。
 */
function onDocumentUpdated(doc: DocumentResponse): void {
  const index = docs.value.findIndex((item) => item.doc_id === doc.doc_id)
  if (index >= 0) docs.value[index] = doc
  selected.value = doc
}

/* ---------------------------- 公共库审核 ------------------------------ */

/**
 * 公共可见内容入库后处于待审状态，批准后才进入检索与问答依据（T-KB-12）。
 * 这里只做入口显隐，服务端仍按 knowledge.review 逐次校验。
 */
const reviewing = ref<DocumentResponse | null>(null)
const reviewDecision = ref<'approve' | 'reject'>('approve')
const reviewNote = ref('')
const reviewBusy = ref(false)
const reviewError = ref('')

const reviewTitle = computed(() =>
  reviewDecision.value === 'approve' ? '确认批准发布' : '确认退回修正',
)

function askReview(doc: DocumentResponse, decision: 'approve' | 'reject'): void {
  if (!canReview.value) return
  reviewing.value = doc
  reviewDecision.value = decision
  reviewNote.value = ''
  reviewError.value = ''
}

async function confirmReview(): Promise<void> {
  const doc = reviewing.value
  if (!doc) return
  reviewBusy.value = true
  reviewError.value = ''
  try {
    const updated = await reviewDocument(
      doc.doc_id,
      reviewDecision.value,
      reviewNote.value.trim() || undefined,
    )
    onDocumentUpdated(updated)
    reviewing.value = null
    await load()
  } catch (err) {
    reviewError.value = err instanceof ApiError ? err.message : '审核失败，请重试'
  } finally {
    reviewBusy.value = false
  }
}

/* ---------------------------- 供给复核确认 ------------------------------ */

/**
 * 学校「供给机制」按权威来源给出责任部门、责任人与更新周期；条目到达期限后
 * 需要供给方核对是否仍然现行有效或已随法规修订更新（T-KB-13）。复核确认把
 * 日程重排到「确认时间 + 更新周期」，到期提醒因此不会被无限拖延。
 */
const maintaining = ref<DocumentResponse | null>(null)
const maintenanceNote = ref('')
const maintenanceBusy = ref(false)
const maintenanceError = ref('')

function reviewDueText(doc: DocumentResponse): string {
  if (!doc.next_review_at) return '未排定复核日程（学校尚未登记该类别的供给机制）'
  return doc.review_due
    ? `已到复核期限（${doc.next_review_at}）`
    : `下次复核 ${doc.next_review_at}`
}

function askMaintenance(doc: DocumentResponse): void {
  if (!canManage.value) return
  maintaining.value = doc
  maintenanceNote.value = ''
  maintenanceError.value = ''
}

async function confirmMaintenance(): Promise<void> {
  const doc = maintaining.value
  if (!doc) return
  maintenanceBusy.value = true
  maintenanceError.value = ''
  try {
    const updated = await confirmDocumentMaintenance(doc.doc_id, maintenanceNote.value.trim() || undefined)
    onDocumentUpdated(updated)
    maintaining.value = null
    await load()
  } catch (err) {
    maintenanceError.value = err instanceof ApiError ? err.message : '复核登记失败，请重试'
  } finally {
    maintenanceBusy.value = false
  }
}

/* ---------------------------- 上传表单 ------------------------------ */

const upload = reactive({
  file: null as File | null,
  doc_id: '',
  title: '',
  issuer: '',
  doc_number: '',
  level: 'school' as DocLevel,
  visibility: 'school' as DocumentResponse['visibility'],
  effective_date: '',
  expiration_date: '',
  security_level: 'internal' as DataLevel,
  /** 空值表示按制度层级自动推定权威来源（后端 default_authority） */
  authority: '' as DocAuthority | '',
  validity: 'effective' as DocValidity,
  tags: '',
  summary: '',
})

const uploadSubmitting = ref(false)
const uploadError = ref('')
const uploadDone = ref('')

const MAX_UPLOAD = 10 * 1024 * 1024 // 与 settings.MAX_UPLOAD_SIZE 一致

const uploadValid = computed(
  () =>
    upload.file !== null &&
    upload.doc_id.trim().length > 0 &&
    upload.title.trim().length > 0 &&
    upload.issuer.trim().length > 0 &&
    upload.effective_date.length > 0 &&
    upload.file.size <= MAX_UPLOAD,
)

function onFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0] ?? null
  upload.file = f
  if (f && !upload.title) {
    upload.title = f.name.replace(/\.[^.]+$/, '')
  }
  if (f && !upload.doc_id) {
    upload.doc_id = `DOC-${Date.now().toString().slice(-8)}`
  }
}

function resetUpload(): void {
  Object.assign(upload, {
    file: null,
    doc_id: '',
    title: '',
    issuer: '',
    doc_number: '',
    level: 'school',
    visibility: 'school',
    effective_date: '',
    expiration_date: '',
    security_level: 'internal',
    authority: '',
    validity: 'effective',
    tags: '',
    summary: '',
  })
  uploadError.value = ''
  uploadDone.value = ''
}

async function submitUpload(): Promise<void> {
  if (!canManage.value || !uploadValid.value || !upload.file) return

  uploadSubmitting.value = true
  uploadError.value = ''
  uploadDone.value = ''

  try {
    const res = await createDocument({
      file: upload.file,
      doc_id: upload.doc_id.trim(),
      file_name: upload.file.name,
      title: upload.title.trim(),
      issuer: upload.issuer.trim(),
      level: upload.level,
      visibility: upload.visibility,
      effective_date: upload.effective_date,
      security_level: upload.security_level,
      tags: upload.tags.trim(),
      doc_number: upload.doc_number.trim() || undefined,
      summary: upload.summary.trim() || undefined,
      expiration_date: upload.expiration_date || undefined,
      authority: upload.authority || undefined,
      validity: upload.validity,
    })
    uploadDone.value =
      upload.visibility === 'public'
        ? `已入库并提交审核：${res.document.title}，切分为 ${res.chunk_count} 个片段。批准发布前不会作为问答依据。`
        : `已入库：${res.document.title}，切分为 ${res.chunk_count} 个片段。`
    resetUpload()
    uploadOpen.value = false
    page.value = 1
    await load()
  } catch (err) {
    uploadError.value = err instanceof ApiError ? err.message : '上传失败，请重试'
  } finally {
    uploadSubmitting.value = false
  }
}
</script>

<template>
  <div class="kb" :data-density="compact ? 'compact' : undefined">
    <PageHeader
      title="知识库"
      :description="canManage ? '维护用于检索的制度文件。文件的有效状态直接决定它是否会被问答环节引用。' : '查阅授权范围内的制度目录、文件信息与摘要，可按关键词、层级和有效状态筛选。'"
    >
      <template #actions>
        <button class="btn btn--ghost" type="button" @click="compact = !compact">
          <AppIcon name="layout" :size="14" />
          <span>{{ compact ? '舒适' : '紧凑' }}</span>
        </button>
        <button v-if="canManage" class="btn btn--primary" type="button" @click="uploadOpen = !uploadOpen">
          <AppIcon name="upload" :size="14" />
          <span>上传文件</span>
        </button>
      </template>
    </PageHeader>

    <!-- ---------------------------- 上传面板 ---------------------------- -->
    <section v-if="canManage && uploadOpen" class="upload u-card">
      <header class="u-panel-head">
        <h2 class="upload__title">上传制度文件</h2>
        <button class="btn btn--quiet" type="button" @click="uploadOpen = false">
          <AppIcon name="close" :size="14" />
          <span>收起</span>
        </button>
      </header>

      <div class="upload__body">
        <div class="upload__file">
          <label class="dropzone">
            <input
              class="u-sr"
              type="file"
              accept=".pdf,.docx,.doc,.wps,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff,.xls,.xlsx"
              @change="onFileChange"
            />
            <AppIcon name="upload" :size="20" />
            <span class="dropzone__title">
              {{ upload.file ? upload.file.name : '选择文件' }}
            </span>
            <span class="dropzone__hint">
              支持 PDF、Word、TXT、Markdown，单个文件不超过 10 MB
            </span>
            <span class="dropzone__hint is-warn">
              扫描件（图片型 PDF）与照片没有文字层，系统读不出正文；请上传带文字层的
              PDF，或把正文另存为 .docx / .txt 后上传
            </span>
          </label>
          <p
            v-if="upload.file && upload.file.size > MAX_UPLOAD"
            class="field__error"
          >
            <AppIcon name="alert" :size="13" />
            文件超过 10 MB，后端会拒绝接收
          </p>
        </div>

        <div class="upload__grid">
          <div class="field">
            <label class="field__label" for="u-docid">文档编号</label>
            <input id="u-docid" v-model="upload.doc_id" class="input" type="text" />
            <p class="field__hint">入库后作为唯一标识，一经创建不可修改</p>
          </div>
          <div class="field">
            <label class="field__label" for="u-title">标题</label>
            <input id="u-title" v-model="upload.title" class="input" type="text" />
          </div>
          <div class="field">
            <label class="field__label" for="u-issuer">发文机关</label>
            <input id="u-issuer" v-model="upload.issuer" class="input" type="text" />
          </div>
          <div class="field">
            <label class="field__label" for="u-num">文号</label>
            <input id="u-num" v-model="upload.doc_number" class="input" type="text" />
            <p class="field__hint">选填</p>
          </div>
          <div class="field">
            <label class="field__label" for="u-level">效力层级</label>
            <select id="u-level" v-model="upload.level" class="select">
              <option v-for="(l, k) in DOC_LEVEL_LABELS" :key="k" :value="k">{{ l }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="u-vis">可见范围</label>
            <select id="u-vis" v-model="upload.visibility" class="select">
              <option v-for="(l, k) in DOC_VISIBILITY_LABELS" :key="k" :value="k">{{ l }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="u-sec">数据分级</label>
            <select id="u-sec" v-model="upload.security_level" class="select">
              <option v-for="(l, k) in DATA_LEVEL_LABELS" :key="k" :value="k">{{ l }}</option>
            </select>
            <p v-if="upload.security_level !== 'public'" class="field__hint">
              内部内容仅供获准云端服务处理；敏感与涉密内容不参与云端 AI 处理
            </p>
          </div>
          <div class="field">
            <label class="field__label" for="u-auth">权威来源</label>
            <select id="u-auth" v-model="upload.authority" class="select">
              <option value="">按层级自动推定</option>
              <option v-for="(l, k) in DOC_AUTHORITY_LABELS" :key="k" :value="k">{{ l }}</option>
            </select>
            <p class="field__hint">参考资料不会被问答当作依据</p>
          </div>
          <div class="field">
            <label class="field__label" for="u-val">效力状态</label>
            <select id="u-val" v-model="upload.validity" class="select">
              <option v-for="(l, k) in DOC_VALIDITY_LABELS" :key="k" :value="k">{{ l }}</option>
            </select>
            <p v-if="upload.visibility === 'public'" class="field__hint">
              公开内容入库后为"待审核"，批准后才进入检索范围
            </p>
          </div>
          <div class="field">
            <label class="field__label" for="u-eff">生效日期</label>
            <input id="u-eff" v-model="upload.effective_date" class="input" type="date" />
          </div>
          <div class="field">
            <label class="field__label" for="u-exp">失效日期</label>
            <input id="u-exp" v-model="upload.expiration_date" class="input" type="date" />
            <p class="field__hint">选填，留空表示长期有效</p>
          </div>
          <div class="field">
            <label class="field__label" for="u-tags">标签</label>
            <input id="u-tags" v-model="upload.tags" class="input" type="text" placeholder="逗号分隔" />
          </div>
        </div>

        <div class="field">
          <label class="field__label" for="u-sum">摘要</label>
          <textarea id="u-sum" v-model="upload.summary" class="textarea" rows="2"></textarea>
          <p class="field__hint">选填，用于列表预览与人工快速判断收录价值</p>
        </div>

        <div v-if="uploadError" class="upload__msg is-bad" role="alert">
          <AppIcon name="error" :size="14" />
          <span>{{ uploadError }}</span>
        </div>

        <footer class="upload__foot">
          <p class="upload__warn">
            <AppIcon name="shield" :size="14" />
            <span>上传前请确认文件已获准在本系统留存，且分级标注准确。</span>
          </p>
          <div class="upload__actions">
            <button class="btn btn--ghost" type="button" @click="resetUpload">重置</button>
            <button
              class="btn btn--primary"
              type="button"
              :disabled="!uploadValid || uploadSubmitting"
              @click="submitUpload"
            >
              {{ uploadSubmitting ? '正在入库' : '确认入库' }}
            </button>
          </div>
        </footer>
      </div>
    </section>

    <!-- ---------------------------- 筛选条 ---------------------------- -->
    <div class="filters">
      <div class="tabs" role="tablist">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="tab"
          :class="{ 'is-active': tab === t.key }"
          type="button"
          role="tab"
          :aria-selected="tab === t.key"
          @click="tab = t.key"
        >
          {{ t.label }}
          <span class="tab__count u-num">{{ counts[t.key] }}</span>
        </button>
      </div>

      <div class="filters__right">
        <div class="search">
          <AppIcon name="search" :size="14" class="search__icon" />
          <input
            v-model="keyword"
            class="input search__input"
            type="search"
            placeholder="按标题、发文机关、文号或标签搜索"
          />
        </div>
        <select v-model="levelFilter" class="select filters__level">
          <option value="all">全部层级</option>
          <option v-for="(l, k) in DOC_LEVEL_LABELS" :key="k" :value="k">{{ l }}</option>
        </select>
        <select v-if="canReview" v-model="reviewFilter" class="select filters__level" aria-label="审核状态">
          <option value="all">全部审核状态</option>
          <option v-for="(l, k) in DOC_REVIEW_STATUS_LABELS" :key="k" :value="k">{{ l }}</option>
        </select>
        <select v-if="canManage" v-model="dueFilter" class="select filters__level" aria-label="复核状态">
          <option value="all">全部复核状态</option>
          <option value="due">待复核</option>
        </select>
      </div>
    </div>

    <!-- ---------------------------- 表格 ---------------------------- -->
    <p v-if="!loading && !error && filtered.length" class="u-meta table-hint">
      选择任意行可在下方查看完整信息、下载原件{{ canManage ? '、修正元数据与更新正文' : '' }}。
    </p>

    <LoadingBlock v-if="loading" variant="table" :rows="6" />

    <ErrorState v-else-if="error" :error="error">
      <button class="btn btn--ghost" type="button" @click="load">重新加载</button>
    </ErrorState>

    <EmptyState
      v-else-if="!filtered.length"
      icon="search"
      :title="hasActiveFilter ? '没有匹配的文件' : '授权范围内暂无可读文件'"
      :body="hasActiveFilter ? '换个关键词，或清除筛选条件后重试。' : emptyScopeBody"
    >
      <button
        v-if="hasActiveFilter"
        class="btn btn--ghost"
        type="button"
        @click="((keyword = ''), (levelFilter = 'all'), (tab = 'all'))"
      >
        清除筛选
      </button>
    </EmptyState>

    <div v-else class="table-wrap u-card">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">标题</th>
            <th scope="col">发文机关</th>
            <th scope="col">层级</th>
            <th scope="col">可见范围</th>
            <th scope="col">权威来源</th>
            <th scope="col">生效</th>
            <th scope="col">失效</th>
            <th scope="col">状态</th>
            <th v-if="canManage" scope="col" class="td-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="d in filtered"
            :key="d.doc_id"
            :aria-selected="selected?.doc_id === d.doc_id"
            @click="selectDocument(d)"
          >
            <td>
              <div class="cell-title">
                <span class="table__primary">{{ d.title }}</span>
                <span class="u-mono cell-title__id">{{ d.doc_id }}</span>
              </div>
            </td>
            <td>{{ d.issuer }}</td>
            <td><span class="badge">{{ DOC_LEVEL_LABELS[d.level] }}</span></td>
            <td>{{ DOC_VISIBILITY_LABELS[d.visibility] }}</td>
            <td>
              <span class="badge" :class="authorityTone(d.authority)">
                {{ DOC_AUTHORITY_LABELS[d.authority] }}
              </span>
            </td>
            <td class="u-mono">{{ d.effective_date ?? '未标注' }}</td>
            <td>
              <span v-if="d.expiration_date" class="u-mono">{{ d.expiration_date }}</span>
              <span v-else class="u-faint">长期</span>
            </td>
            <td>
              <span class="badge" :class="statusTone(d.status)">
                {{ DOC_STATUS_LABELS[d.status] }}
              </span>
              <span
                v-if="d.validity !== 'effective'"
                class="badge cell-expiring"
                :class="validityTone(d.validity)"
              >
                {{ DOC_VALIDITY_LABELS[d.validity] }}
              </span>
              <span
                v-if="d.review_status !== 'published'"
                class="badge cell-expiring"
                :class="reviewTone(d.review_status)"
              >
                {{ DOC_REVIEW_STATUS_LABELS[d.review_status] }}
              </span>
              <span v-if="expiringSoon(d)" class="badge badge--warn cell-expiring">即将到期</span>
              <span
                v-if="d.review_due"
                class="badge cell-expiring"
                :class="`badge--${DOC_REVIEW_DUE_TONE}`"
              >
                {{ DOC_REVIEW_DUE_LABEL }}
              </span>
            </td>
            <td v-if="canManage" class="td-right" @click.stop>
              <template v-if="canReview && d.review_status === 'pending'">
                <button
                  class="btn btn--quiet"
                  type="button"
                  :disabled="statusBusy === d.doc_id || reviewBusy"
                  @click="askReview(d, 'approve')"
                >
                  批准
                </button>
                <button
                  class="btn btn--quiet"
                  type="button"
                  :disabled="statusBusy === d.doc_id || reviewBusy"
                  @click="askReview(d, 'reject')"
                >
                  退回
                </button>
              </template>
              <button
                v-else-if="d.status === 'effective'"
                class="btn btn--quiet"
                type="button"
                :disabled="statusBusy === d.doc_id"
                @click="changeStatus(d, 'abolished')"
              >
                废止
              </button>
              <button
                v-else
                class="btn btn--quiet"
                type="button"
                :disabled="statusBusy === d.doc_id"
                @click="changeStatus(d, 'effective')"
              >
                恢复生效
              </button>
              <button v-if="d.review_due" class="btn btn--quiet" type="button" :disabled="statusBusy === d.doc_id || reviewBusy || maintenanceBusy" @click="askMaintenance(d)">复核</button>
              <button class="btn btn--quiet" type="button" :disabled="statusBusy !== null || replacementBusy" @click="askRemove(d)">移除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="!loading && !error && filtered.length" class="table-foot u-meta">
      共 {{ total }} 条，第 {{ page }} 页。
    </p>
    <div v-if="!loading && !error && total > pageSize" class="table-foot">
      <button class="btn btn--ghost" :disabled="page <= 1" @click="turnPage(-1)">上一页</button>
      <button class="btn btn--ghost" :disabled="page * pageSize >= total" @click="turnPage(1)">下一页</button>
    </div>

    <!-- ---------------------------- 详情抽屉 ---------------------------- -->
    <aside v-if="selected" ref="detail" class="detail u-card">
      <header class="u-panel-head">
        <h2 class="detail__title">文件详情</h2>
        <button class="btn btn--quiet" type="button" @click="selected = null">
          <AppIcon name="close" :size="14" />
          <span>关闭</span>
        </button>
      </header>
      <dl class="detail__list">
        <div class="detail__row">
          <dt>标题</dt>
          <dd>{{ selected.title }}</dd>
        </div>
        <div class="detail__row">
          <dt>文档编号</dt>
          <dd class="u-mono">{{ selected.doc_id }}</dd>
        </div>
        <div class="detail__row">
          <dt>文件名</dt>
          <dd class="u-mono detail__file">{{ selected.file_name }}</dd>
        </div>
        <div class="detail__row">
          <dt>发文机关</dt>
          <dd>{{ selected.issuer }}</dd>
        </div>
        <div class="detail__row">
          <dt>文号</dt>
          <dd>{{ selected.doc_number ?? '未标注' }}</dd>
        </div>
        <div class="detail__row">
          <dt>数据分级</dt>
          <dd>{{ DATA_LEVEL_LABELS[selected.security_level] }}</dd>
        </div>
        <div class="detail__row">
          <dt>权威来源</dt>
          <dd>
            <span class="badge" :class="authorityTone(selected.authority)">
              {{ DOC_AUTHORITY_LABELS[selected.authority] }}
            </span>
            <span v-if="selected.authority === 'reference'" class="u-meta">
              参考资料不会被问答当作依据
            </span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>效力状态</dt>
          <dd>
            <span class="badge" :class="validityTone(selected.validity)">
              {{ DOC_VALIDITY_LABELS[selected.validity] }}
            </span>
            <span v-if="selected.validity !== 'effective'" class="u-meta">
              非现行有效内容不会被问答当作依据
            </span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>审核状态</dt>
          <dd>
            <span class="badge" :class="reviewTone(selected.review_status)">
              {{ DOC_REVIEW_STATUS_LABELS[selected.review_status] }}
            </span>
            <span v-if="selected.reviewed_at" class="u-meta">
              审核于 {{ selected.reviewed_at }}
              <template v-if="selected.review_note">· {{ selected.review_note }}</template>
            </span>
            <span
              v-else-if="selected.visibility === 'public'"
              class="u-meta"
            >
              待审核，批准后才进入检索范围
            </span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>供给责任</dt>
          <dd>
            <template v-if="selected.owner_unit || selected.owner_name">
              {{ selected.owner_unit ?? '未登记部门' }}
              <span v-if="selected.owner_name">· {{ selected.owner_name }}</span>
            </template>
            <span v-else class="u-meta">学校尚未为该权威来源登记供给机制</span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>复核周期</dt>
          <dd>
            <span v-if="selected.review_cycle_days" class="u-num">
              每 {{ selected.review_cycle_days }} 天
            </span>
            <span v-else class="u-faint">未设定</span>
            <span class="u-meta">{{ reviewDueText(selected) }}</span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>最近复核</dt>
          <dd>{{ selected.maintained_at ?? '尚无复核记录' }}</dd>
        </div>
        <div class="detail__row">
          <dt>标签</dt>
          <dd>
            <span v-if="!selected.tags.length" class="u-faint">无</span>
            <span v-for="t in selected.tags" :key="t" class="badge detail__tag">{{ t }}</span>
          </dd>
        </div>
        <div class="detail__row">
          <dt>页数</dt>
          <dd class="u-num">{{ selected.page_count ?? '未知' }}</dd>
        </div>
        <div class="detail__row">
          <dt>摘要</dt>
          <dd class="detail__summary">{{ selected.summary ?? '未填写' }}</dd>
        </div>
      </dl>

      <!-- 公共库审核入口：待审内容不进入检索，批准后立即生效（T-KB-12） -->
      <div v-if="canReview && selected.review_status === 'pending'" class="detail__review">
        <p class="u-meta">
          该项为公共可见内容，尚未进入检索与问答依据。批准后立即生效；退回须写明意见。
        </p>
        <div class="wb-actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="reviewBusy"
            @click="askReview(selected, 'approve')"
          >
            批准发布
          </button>
          <button
            class="btn btn--ghost"
            type="button"
            :disabled="reviewBusy"
            @click="askReview(selected, 'reject')"
          >
            退回修正
          </button>
        </div>
      </div>

      <!-- 供给复核确认：到期后由供给方核对是否仍现行有效或已随法规修订更新（T-KB-13） -->
      <div v-if="canManage" class="detail__review">
        <p class="u-meta">
          复核确认后，下次复核日期按学校供给机制的更新周期重排：更新正文同样视为一次
          复核，日程以本次更新为基准。
        </p>
        <div class="wb-actions">
          <button
            class="btn"
            :class="selected.review_due ? 'btn--primary' : 'btn--quiet'"
            type="button"
            :disabled="maintenanceBusy || reviewBusy"
            @click="askMaintenance(selected)"
          >
            {{ selected.review_due ? '登记复核（已到期）' : '登记复核' }}
          </button>
        </div>
      </div>

      <!-- 处理状态、原件下载与元数据修正。此前该组件已实现但没有任何页面引用，
           导致后端能力齐备而用户拿不到原件；这里把它接回详情面板。 -->
      <DocumentTools :document="selected" @updated="onDocumentUpdated" />

      <footer v-if="canManage" class="detail__foot">
        <p class="u-meta">状态变更会直接影响该文件是否被问答环节检索到。</p>
        <p class="u-meta">
          更新内容同样必须是可复制的文字：扫描件请先导出带文字层的 PDF，或把正文另存为
          .docx / .txt 后上传（替换失败时会说明原因与出路）。
        </p>
        <label class="field">
          <span>更新文件内容（当前版本 {{ selected.content_revision ?? 1 }}）</span>
          <input
            :key="selected.id + ':' + selected.content_revision"
            type="file"
            accept=".txt,.md,.pdf,.docx,.doc,.wps,.png,.jpg,.jpeg,.webp,.tif,.tiff"
            @change="chooseReplacement"
          />
        </label>
        <button class="btn btn--ghost" type="button" :disabled="!replacement || replacementBusy" @click="replaceContent">
          {{ replacementBusy ? '保存中' : '保存新版本' }}
        </button>
        <p v-if="replacementMessage" class="replacement__msg" role="status">{{ replacementMessage }}</p>
      </footer>
    </aside>

    <!-- 公共库审核确认：批准/退回均留痕，退回须写明意见（T-KB-12） -->
    <ActionDialog
      :open="Boolean(reviewing)"
      :title="reviewTitle"
      :busy="reviewBusy"
      @close="reviewing = null"
    >
      <p class="remove-confirm">{{ reviewing?.title }}（{{ reviewing?.doc_id }}）</p>
      <ul class="remove-confirm__list">
        <li v-if="reviewDecision === 'approve'">
          批准后该内容立即进入检索范围，可作为制度问答依据。
        </li>
        <li v-else>退回后该内容保持不参与检索，维护人员修正后可再次提交审核。</li>
        <li>审核人、审核时间与审核意见会写入审计记录。</li>
      </ul>
      <label class="field">
        <span>审核意见{{ reviewDecision === 'reject' ? '（退回必填）' : '（选填）' }}</span>
        <textarea v-model="reviewNote" class="textarea" rows="2" maxlength="500" />
      </label>
      <p v-if="reviewError" class="field__error" role="alert">{{ reviewError }}</p>
      <div class="remove-confirm__actions">
        <button class="btn btn--quiet" type="button" :disabled="reviewBusy" @click="reviewing = null">
          取消
        </button>
        <button
          class="btn btn--primary"
          type="button"
          :disabled="reviewBusy || (reviewDecision === 'reject' && !reviewNote.trim())"
          @click="confirmReview"
        >
          {{
            reviewBusy ? '提交中…' : reviewDecision === 'approve' ? '确认批准' : '确认退回'
          }}
        </button>
      </div>
    </ActionDialog>

    <!-- 供给复核确认：核对仍现行有效或已随法规修订更新，确认后重排下次复核日程（T-KB-13） -->
    <ActionDialog
      :open="Boolean(maintaining)"
      title="登记供给复核确认"
      :busy="maintenanceBusy"
      @close="maintaining = null"
    >
      <p class="remove-confirm">{{ maintaining?.title }}（{{ maintaining?.doc_id }}）</p>
      <ul class="remove-confirm__list">
        <li>确认人已核对本条目仍是现行有效版本，或已随法规修订同步更新。</li>
        <li>
          确认后按学校供给机制重排下次复核日期{{
            maintaining?.review_cycle_days ? `（每 ${maintaining.review_cycle_days} 天）` : ''
          }}；需要对制度本身作出效力变更，请改用元数据修正或状态变更。
        </li>
        <li>复核人、时间与说明写入审计记录。</li>
      </ul>
      <label class="field">
        <span>复核说明（选填）</span>
        <textarea v-model="maintenanceNote" class="textarea" rows="2" maxlength="500" />
      </label>
      <p v-if="maintenanceError" class="field__error" role="alert">{{ maintenanceError }}</p>
      <div class="remove-confirm__actions">
        <button class="btn btn--quiet" type="button" :disabled="maintenanceBusy" @click="maintaining = null">
          取消
        </button>
        <button
          class="btn btn--primary"
          type="button"
          :disabled="maintenanceBusy"
          @click="confirmMaintenance"
        >
          {{ maintenanceBusy ? '提交中…' : '确认复核' }}
        </button>
      </div>
    </ActionDialog>

    <!-- 移除确认：站内弹窗，替代原生 window.confirm -->
    <ActionDialog
      :open="Boolean(removing)"
      title="确认移除制度文件"
      :busy="statusBusy !== null"
      @close="removing = null"
    >
      <p class="remove-confirm">
        确认移除《{{ removing?.title }}》？
      </p>
      <ul class="remove-confirm__list">
        <li>移除后该文件不再参与制度问答检索。</li>
        <li>历史问答记录与审计记录保留，不会被删除。</li>
        <li>如只是文件失效，请改用"废止"，保留可追溯性。</li>
      </ul>
      <div class="remove-confirm__actions">
        <button class="btn btn--quiet" type="button" :disabled="statusBusy !== null" @click="removing = null">
          取消
        </button>
        <button class="btn btn--primary" type="button" :disabled="statusBusy !== null" @click="confirmRemove">
          {{ statusBusy !== null ? '移除中…' : '确认移除' }}
        </button>
      </div>
    </ActionDialog>
  </div>
</template>

<style scoped>
.kb {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6) var(--space-6) var(--space-10);
  width: 100%;
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

/* ---------------------------- 上传 -------------------------------- */
.upload__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.upload__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-5);
}

.upload__file {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-6);
  border: 1px dashed var(--rule-strong);
  border-radius: var(--radius-md);
  background: var(--paper-dim);
  color: var(--ink-muted);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.dropzone:hover {
  border-color: var(--accent-edge);
  background: var(--accent-wash);
}

.dropzone__title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink);
  word-break: break-all;
  text-align: center;
}

.dropzone__hint {
  font-size: var(--text-xs);
  color: var(--ink-faint);
}

.upload__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}

.upload__msg {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  /* T-WF01-04：解析失败的提示带 ①②③ 分步说明，必须按行显示，不能挤成一段 */
  white-space: pre-line;
}

.upload__msg svg {
  flex: none;
  margin-top: 2px;
}

/* 替换正文的失败提示同样带分步说明（T-WF01-04） */
.replacement__msg {
  white-space: pre-line;
}

.dropzone__hint.is-warn {
  color: var(--warn-ink);
}

.upload__msg.is-bad {
  color: var(--bad-ink);
  background: var(--bad-wash);
  border: 1px solid var(--bad-edge);
}

.upload__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-top: var(--space-4);
  border-top: var(--border);
}

.upload__warn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

.upload__actions {
  display: flex;
  gap: var(--space-2);
  flex: none;
}

/* ---------------------------- 筛选 -------------------------------- */
.filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.tabs {
  display: flex;
  gap: var(--space-1);
  padding: 2px;
  background: var(--paper-dim);
  border: var(--border);
  border-radius: var(--radius-sm);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 28px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-xs);
  font-size: var(--text-sm);
  color: var(--ink-muted);
  transition: background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.tab:hover {
  color: var(--ink);
}

.tab.is-active {
  background: var(--paper-raised);
  color: var(--ink);
  font-weight: 600;
  box-shadow: 0 1px 2px rgb(28 27 25 / 0.06);
}

.tab__count {
  font-size: var(--text-2xs);
  color: var(--ink-faint);
}

.tab.is-active .tab__count {
  color: var(--ink-muted);
}

.filters__right {
  display: flex;
  gap: var(--space-2);
  flex: none;
}

.search {
  position: relative;
  display: flex;
  align-items: center;
}

.search__icon {
  position: absolute;
  left: var(--space-3);
  color: var(--ink-faint);
  pointer-events: none;
}

.search__input {
  width: 268px;
  padding-left: 32px;
}

.filters__level {
  width: auto;
}

/* ---------------------------- 表格 -------------------------------- */
/* 用 max-height 把表格限制在一屏内（表头粘性），但必须允许滚动：此前写成
   overflow: hidden，条目超过容器高度后多出来的行既没有滚动条也无法用滚轮到达，
   用户会以为列表只有这么多条。窄屏下同一处还依赖滚动才能看到右侧的「操作」列。 */
.table-wrap {
  overflow: auto;
  max-height: calc(100dvh - 320px);
}

.cell-title {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.cell-title__id {
  font-size: var(--text-2xs);
  color: var(--ink-faint);
}

.cell-expiring {
  margin-left: var(--space-2);
}

.table-foot {
  padding-left: 2px;
}

.table-hint {
  padding-left: 2px;
}

/* ---------------------------- 移除确认 ---------------------------- */
.remove-confirm {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--ink);
}

.remove-confirm__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-3);
  padding-left: var(--space-5);
  list-style: disc;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.remove-confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-5);
}

/* ---------------------------- 详情 -------------------------------- */
.detail {
  overflow: hidden;
  /* 从表格点选后会被滚动定位到这里，给粘性顶栏留出安全距离 */
  scroll-margin-top: calc(var(--nav-h) + var(--space-4));
}

.detail__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.detail__list {
  display: flex;
  flex-direction: column;
}

.detail__row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border);
}

.detail__row:last-child {
  border-bottom: 0;
}

.detail__row dt {
  font-size: var(--text-xs);
  color: var(--ink-faint);
}

.detail__row dd {
  font-size: var(--text-sm);
  color: var(--ink-soft);
  word-break: break-word;
}

.detail__file {
  font-size: var(--text-xs);
}

.detail__tag {
  margin-right: var(--space-1);
}

.detail__summary {
  line-height: var(--leading-normal);
}

.detail__foot {
  padding: var(--space-3) var(--space-4);
  background: var(--paper-dim);
  border-top: var(--border);
}

/* 公共库待审提示：用强调底色与其它只读信息区分（T-KB-12） */
.detail__review {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--paper-dim);
  border-top: var(--border);
}

@media (max-width: 900px) {
  .kb {
    padding: var(--space-4) var(--space-4) var(--space-10);
  }

  .filters {
    flex-direction: column;
    align-items: stretch;
  }

  .filters__right {
    flex-direction: column;
  }

  .search__input {
    width: 100%;
  }

  .table-wrap {
    max-height: none;
  }

  .upload__foot {
    flex-direction: column;
    align-items: stretch;
  }

  .upload__actions {
    justify-content: flex-end;
  }
}
</style>
