<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import {
  getOriginalFile,
  getProcessingStatus,
  processDocument,
  updateDocumentMetadata,
  type DocumentProcessing,
} from '@/api/knowledge'
import {
  DATA_LEVEL_LABELS,
  DOC_AUTHORITY_LABELS,
  DOC_LEVEL_LABELS,
  DOC_VALIDITY_LABELS,
  DOC_VISIBILITY_LABELS,
  type DocAuthority,
  type DocumentResponse,
  type DocValidity,
} from '@/api/types'
import ErrorState from '@/components/ErrorState.vue'
import { session } from '@/stores/session'
import { downloadBlob } from '@/utils/files'

const props = defineProps<{ document: DocumentResponse }>()
const emit = defineEmits<{ updated: [document: DocumentResponse] }>()
const status = ref<DocumentProcessing | null>(null)
const loading = ref(false)
const busy = ref('')
const error = ref<unknown>(null)
const message = ref('')
const revision = ref(1)
const labels = {
  pending: '待处理',
  partial: '部分可检索',
  ready: '可检索',
  failed: '处理失败',
  no_chunks: '没有可处理的正文',
}
const canManage = computed(() => session.can('knowledge.manage'))
const meta = reactive({
  title: '',
  issuer: '',
  doc_number: '',
  level: 'school' as DocumentResponse['level'],
  visibility: 'school' as DocumentResponse['visibility'],
  security_level: 'internal' as DocumentResponse['security_level'],
  authority: 'reference' as DocAuthority,
  validity: 'effective' as DocValidity,
  effective_date: '',
  expiration_date: '',
  tags: '',
  summary: '',
  reason: '',
})
let sequence = 0

async function loadStatus(): Promise<void> {
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const response = await getProcessingStatus(props.document.doc_id)
    if (current === sequence) status.value = response
  } catch (err) {
    if (current === sequence) error.value = err
  } finally {
    if (current === sequence) loading.value = false
  }
}

watch(
  () => props.document,
  (doc, previous) => {
    Object.assign(meta, {
      ...doc,
      doc_number: doc.doc_number || '',
      effective_date: doc.effective_date || '',
      expiration_date: doc.expiration_date || '',
      tags: doc.tags.join('，'),
      summary: doc.summary || '',
      reason: '',
    })
    revision.value = doc.content_revision ?? 1
    status.value = null
    if (
      !previous ||
      doc.doc_id !== previous.doc_id ||
      doc.content_revision !== previous.content_revision
    )
      message.value = ''
    void loadStatus()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  sequence += 1
})

async function run(action: string, fn: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = action
  error.value = null
  message.value = ''
  try {
    await fn()
  } catch (err) {
    error.value = err
  } finally {
    busy.value = ''
  }
}

async function process(): Promise<void> {
  await run('process', async () => {
    const response = await processDocument(props.document.doc_id)
    await loadStatus()
    message.value = `本次处理 ${response.embedded_count} 个片段，检索状态已刷新。`
  })
}

async function download(): Promise<void> {
  await run('download', async () => {
    const file = await getOriginalFile(props.document.doc_id, revision.value)
    downloadBlob(file, props.document.file_name)
    message.value = `已下载第 ${revision.value} 版原件。`
  })
}

async function save(): Promise<void> {
  await run('metadata', async () => {
    const doc = await updateDocumentMetadata(props.document.doc_id, {
      title: meta.title.trim(),
      issuer: meta.issuer.trim(),
      doc_number: meta.doc_number.trim() || null,
      level: meta.level,
      visibility: meta.visibility,
      security_level: meta.security_level,
      authority: meta.authority,
      validity: meta.validity,
      effective_date: meta.effective_date,
      expiration_date: meta.expiration_date || null,
      tags: meta.tags.trim(),
      summary: meta.summary.trim() || null,
      reason: meta.reason.trim(),
    })
    emit('updated', doc)
    message.value = '元数据已保存，变更理由已留存。'
  })
}
</script>

<template>
  <div class="wb-stack document-tools" :aria-busy="busy !== ''">
    <section class="wb-section wb-stack">
      <div class="wb-toolbar">
        <h3>处理与原件</h3>
        <button
          class="btn btn--quiet btn--sm"
          type="button"
          :disabled="loading || !!busy"
          @click="loadStatus"
        >
          刷新状态
        </button>
      </div>
      <p v-if="loading" class="u-meta" role="status">正在查询处理状态…</p>
      <template v-else-if="status">
        <div class="wb-toolbar">
          <span class="badge" :class="status.status === 'ready' ? 'badge--ok' : 'badge--warn'">{{
            labels[status.status]
          }}</span
          ><span class="u-meta">正文版本 {{ status.content_revision }}</span>
        </div>
        <dl class="wb-facts">
          <div>
            <dt>正文片段</dt>
            <dd>{{ status.total_chunks }}</dd>
          </div>
          <div>
            <dt>已处理</dt>
            <dd>{{ status.embedded_chunks }}</dd>
          </div>
          <div>
            <dt>待处理</dt>
            <dd>{{ status.pending_chunks }}</dd>
          </div>
        </dl>
        <p v-if="status.error" class="field__error">{{ status.error }}</p>
        <div v-if="canManage && status.retry_endpoint" class="wb-actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="!!busy || document.security_level === 'classified'"
            @click="process"
          >
            {{
              busy === 'process'
                ? '处理中…'
                : status.status === 'failed'
                  ? '重试处理'
                  : '处理待检索片段'
            }}
          </button>
        </div>
        <p v-if="document.security_level === 'classified'" class="u-meta">
          涉密资料不提供在线向量处理。
        </p>
      </template>
      <div class="wb-actions">
        <label class="wb-field"
          ><span>原件版本</span
          ><input
            v-model.number="revision"
            class="input"
            type="number"
            min="1"
            :max="document.content_revision ?? 1"
            step="1"
        /></label>
        <button
          class="btn btn--ghost"
          type="button"
          :disabled="
            !!busy ||
            !Number.isInteger(revision) ||
            revision < 1 ||
            revision > (document.content_revision ?? 1)
          "
          @click="download"
        >
          {{ busy === 'download' ? '下载中…' : '下载原件' }}
        </button>
      </div>
      <p class="u-meta">历史原件按当前权限检查；早期未留存的版本会提示无法下载。</p>
    </section>
    <details v-if="canManage" class="wb-disclosure">
      <summary>修正文档元数据</summary>
      <form class="wb-stack" @submit.prevent="save">
        <div class="wb-grid">
          <label class="wb-field"
            ><span>文件标题</span
            ><input v-model="meta.title" class="input" maxlength="500" required
          /></label>
          <label class="wb-field"
            ><span>发文机关</span
            ><input v-model="meta.issuer" class="input" maxlength="200" required
          /></label>
          <label class="wb-field"
            ><span>文号</span><input v-model="meta.doc_number" class="input" maxlength="100"
          /></label>
          <label class="wb-field"
            ><span>制度层级</span
            ><select v-model="meta.level" class="select">
              <option v-for="(label, key) in DOC_LEVEL_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>可见范围</span
            ><select v-model="meta.visibility" class="select">
              <option v-for="(label, key) in DOC_VISIBILITY_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>数据分级</span
            ><select v-model="meta.security_level" class="select">
              <option v-for="(label, key) in DATA_LEVEL_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>权威来源</span
            ><select v-model="meta.authority" class="select">
              <option v-for="(label, key) in DOC_AUTHORITY_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>效力状态</span
            ><select v-model="meta.validity" class="select">
              <option v-for="(label, key) in DOC_VALIDITY_LABELS" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          >
          <label class="wb-field"
            ><span>生效日期</span
            ><input v-model="meta.effective_date" class="input" type="date" required
          /></label>
          <label class="wb-field"
            ><span>失效日期（可留空）</span
            ><input
              v-model="meta.expiration_date"
              class="input"
              type="date"
              :min="meta.effective_date || undefined"
          /></label>
        </div>
        <label class="wb-field"
          ><span>标签（用逗号分隔）</span
          ><input v-model="meta.tags" class="input" maxlength="500" required
        /></label>
        <label class="wb-field"
          ><span>摘要</span
          ><textarea v-model="meta.summary" class="textarea" rows="3" maxlength="2000" />
        </label>
        <label class="wb-field"
          ><span>修正理由</span
          ><textarea v-model="meta.reason" class="textarea" rows="2" maxlength="2000" required />
        </label>
        <p class="u-meta">
          公共库、组织范围和密级变更会再次核验权限与正文分级；参考资料与非现行有效内容不会被问答当作依据。
        </p>
        <div class="wb-actions">
          <button class="btn btn--primary" type="submit" :disabled="!!busy || !meta.reason.trim()">
            {{ busy === 'metadata' ? '保存中…' : '保存元数据' }}
          </button>
        </div>
      </form>
    </details>
    <ErrorState v-if="error" :error="error" />
    <p v-if="message" class="wb-success" role="status">{{ message }}</p>
  </div>
</template>

<style scoped>
.document-tools {
  padding: var(--space-5);
  border-top: var(--border);
}
.document-tools .wb-actions .wb-field {
  max-width: 140px;
}
</style>
