<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { createDocument, deleteKnowledgeDocument, listKnowledgeDocuments, updateDocumentStatus } from '@/api/knowledge'
import { ApiError } from '@/api/http'
import type { DocumentResponse, DocLevel, DocStatus, DataLevel } from '@/api/types'
import {
  DATA_LEVEL_LABELS,
  DOC_LEVEL_LABELS,
  DOC_STATUS_LABELS,
  DOC_STATUS_TONE,
  DOC_VISIBILITY_LABELS,
} from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'

/**
 * 知识库管理。
 *
 * ⚠️ Section 13 边界声明：本页属于 taste-skill 明确不覆盖的「数据表 / 管理面板」
 *    类型。因此本页**不套用**展示型审美规则（大留白、非对称栅格、编辑式标题），
 *    而是采用**保守的数据表设计**：粘性表头、克制行高、密度可切换、右侧详情抽屉。
 *    仅复用设计系统的色彩、字阶与圆角 token，以保证与全站同源。
 *
 * 列表 / 删除 / 改状态 / 上传均走真实接口；接口失败会如实报错。
 */

type Tab = 'all' | DocStatus

const docs = ref<DocumentResponse[]>([])
const loading = ref(true)
const error = ref<unknown>(null)
const tab = ref<Tab>('all')
const keyword = ref('')
const levelFilter = ref<DocLevel | 'all'>('all')
const compact = ref(false)
const selected = ref<DocumentResponse | null>(null)
const statusBusy = ref<string | null>(null)
const deleteArmed = ref<string | null>(null)
const uploadOpen = ref(false)

/** 从后端拉取文件列表（保留骨架屏/错误态处理） */
async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const { items } = await listKnowledgeDocuments({ page_size: 100 })
    docs.value = items
  } catch (err) {
    error.value = err
  } finally {
    loading.value = false
  }
}

onMounted(load)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return docs.value.filter((d) => {
    if (tab.value !== 'all' && d.status !== tab.value) return false
    if (levelFilter.value !== 'all' && d.level !== levelFilter.value) return false
    if (!kw) return true
    return (
      d.title.toLowerCase().includes(kw) ||
      d.issuer.toLowerCase().includes(kw) ||
      d.doc_id.toLowerCase().includes(kw) ||
      (d.doc_number ?? '').toLowerCase().includes(kw) ||
      d.tags.some((t) => t.toLowerCase().includes(kw))
    )
  })
})

const counts = computed(() => ({
  all: docs.value.length,
  effective: docs.value.filter((d) => d.status === 'effective').length,
  expired: docs.value.filter((d) => d.status === 'expired').length,
  abolished: docs.value.filter((d) => d.status === 'abolished').length,
}))

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'effective', label: '有效' },
  { key: 'expired', label: '已失效' },
  { key: 'abolished', label: '已废止' },
]

function statusTone(s: DocStatus): string {
  return `badge--${DOC_STATUS_TONE[s]}`
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
  statusBusy.value = doc.doc_id
  try {
    await updateDocumentStatus(doc.doc_id, status)
    // 接口成功后再改本地视图，避免"看起来成功但后端没落库"
    doc.status = status
  } catch (err) {
    error.value = err
  } finally {
    statusBusy.value = null
  }
}

/** 两步确认的软删除：第一次点击进入确认态（4 秒未确认自动复位），第二次执行 */
async function removeDocument(doc: DocumentResponse): Promise<void> {
  if (deleteArmed.value !== doc.doc_id) {
    deleteArmed.value = doc.doc_id
    window.setTimeout(() => {
      if (deleteArmed.value === doc.doc_id) deleteArmed.value = null
    }, 4000)
    return
  }
  deleteArmed.value = null
  try {
    await deleteKnowledgeDocument(doc.doc_id)
    docs.value = docs.value.filter((d) => d.doc_id !== doc.doc_id)
    if (selected.value?.doc_id === doc.doc_id) selected.value = null
  } catch (err) {
    error.value = err
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
    tags: '',
    summary: '',
  })
  uploadError.value = ''
  uploadDone.value = ''
}

async function submitUpload(): Promise<void> {
  if (!uploadValid.value || !upload.file) return

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
    })
    uploadDone.value = `已入库：${res.document.title}，切分为 ${res.chunk_count} 个片段。`
    docs.value = [res.document, ...docs.value]
    resetUpload()
    uploadOpen.value = false
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
      description="维护用于检索的制度文件。文件的有效状态直接决定它是否会被问答环节引用。"
    >
      <template #actions>
        <button class="btn btn--ghost" type="button" @click="compact = !compact">
          <AppIcon name="layout" :size="14" />
          <span>{{ compact ? '舒适' : '紧凑' }}</span>
        </button>
        <button class="btn btn--primary" type="button" @click="uploadOpen = !uploadOpen">
          <AppIcon name="upload" :size="14" />
          <span>上传文件</span>
        </button>
      </template>
    </PageHeader>

    <!-- ---------------------------- 上传面板 ---------------------------- -->
    <section v-if="uploadOpen" class="upload u-card">
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
            <input class="u-sr" type="file" accept=".pdf,.doc,.docx,.txt,.md" @change="onFileChange" />
            <AppIcon name="upload" :size="20" />
            <span class="dropzone__title">
              {{ upload.file ? upload.file.name : '选择文件' }}
            </span>
            <span class="dropzone__hint">
              支持 PDF、Word、TXT、Markdown，单个文件不超过 10 MB
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
              非公开文件仅由本地模型处理
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
      </div>
    </div>

    <!-- ---------------------------- 表格 ---------------------------- -->
    <LoadingBlock v-if="loading" variant="table" :rows="6" />

    <ErrorState v-else-if="error" :error="error">
      <button class="btn btn--ghost" type="button" @click="load">重新加载</button>
    </ErrorState>

    <EmptyState
      v-else-if="!filtered.length"
      icon="search"
      title="没有匹配的文件"
      body="换个关键词，或清除筛选条件后重试。"
    >
      <button class="btn btn--ghost" type="button" @click="((keyword = ''), (levelFilter = 'all'), (tab = 'all'))">
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
            <th scope="col">生效</th>
            <th scope="col">失效</th>
            <th scope="col">状态</th>
            <th scope="col" class="td-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="d in filtered"
            :key="d.doc_id"
            :aria-selected="selected?.doc_id === d.doc_id"
            @click="selected = d"
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
            <td class="u-mono">{{ d.effective_date ?? '未标注' }}</td>
            <td>
              <span v-if="d.expiration_date" class="u-mono">{{ d.expiration_date }}</span>
              <span v-else class="u-faint">长期</span>
            </td>
            <td>
              <span class="badge" :class="statusTone(d.status)">
                {{ DOC_STATUS_LABELS[d.status] }}
              </span>
              <span v-if="expiringSoon(d)" class="badge badge--warn cell-expiring">即将到期</span>
            </td>
            <td class="td-right" @click.stop>
              <button
                v-if="d.status === 'effective'"
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
              <button
                class="btn btn--quiet btn--danger"
                type="button"
                :disabled="deleteArmed !== null && deleteArmed !== d.doc_id"
                @click="removeDocument(d)"
              >
                {{ deleteArmed === d.doc_id ? '确认删除' : '删除' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="!loading && !error && filtered.length" class="table-foot u-meta">
      共 {{ filtered.length }} 条。选择行可在右侧查看完整信息。
    </p>

    <!-- ---------------------------- 详情抽屉 ---------------------------- -->
    <aside v-if="selected" class="detail u-card">
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
      <footer class="detail__foot">
        <p class="u-meta">状态变更会直接影响该文件是否被问答环节检索到。</p>
      </footer>
    </aside>
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

.btn--danger {
  color: var(--bad-ink);
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
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
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
.table-wrap {
  overflow: hidden;
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

/* ---------------------------- 详情 -------------------------------- */
.detail {
  overflow: hidden;
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
