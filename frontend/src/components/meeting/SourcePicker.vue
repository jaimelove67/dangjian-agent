<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

import { listDocuments } from '@/api/knowledge'
import type { MeetingSource } from '@/api/meeting'
import { DOC_LEVEL_LABELS, type DocumentResponse } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'

const props = withDefaults(
  defineProps<{ modelValue: string[]; sources?: MeetingSource[]; readonly?: boolean }>(),
  { sources: () => [], readonly: false },
)
const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()
const open = ref(false)
const loading = ref(false)
const error = ref<unknown>(null)
const docs = ref<DocumentResponse[]>([])
const titles = ref<Record<string, string>>({})
const q = ref('')
const page = ref(1)
const total = ref(0)
let sequence = 0
async function load(): Promise<void> {
  const current = ++sequence
  loading.value = true
  error.value = null
  try {
    const result = await listDocuments({
      q: q.value.trim() || undefined,
      status: 'effective',
      page: page.value,
      page_size: 15,
    })
    if (current !== sequence) return
    docs.value = result.items
    total.value = result.total
    for (const doc of result.items) titles.value[doc.doc_id] = doc.title
  } catch (err) {
    if (current === sequence) error.value = err
  } finally {
    if (current === sequence) loading.value = false
  }
}
onBeforeUnmount(() => {
  sequence += 1
})
function toggle(doc: DocumentResponse): void {
  const exists = props.modelValue.includes(doc.doc_id)
  emit(
    'update:modelValue',
    exists ? props.modelValue.filter((id) => id !== doc.doc_id) : [...props.modelValue, doc.doc_id],
  )
}
function openPicker(): void {
  open.value = true
  void load()
}
function search(): void {
  page.value = 1
  void load()
}
function changePage(delta: number): void {
  page.value += delta
  void load()
}
</script>

<template>
  <div class="wb-stack">
    <div class="wb-toolbar">
      <h3>参考资料（{{ modelValue.length }} / 20）</h3>
      <button
        v-if="!readonly"
        class="btn btn--ghost btn--sm"
        type="button"
        @click="openPicker"
      >
        从知识库选择
      </button>
    </div>
    <div v-for="id in modelValue" :key="id" class="wb-toolbar">
      <span>{{ sources.find((source) => source.doc_id === id)?.title || titles[id] || id }}</span
      ><button
        v-if="!readonly"
        class="btn btn--quiet btn--sm"
        type="button"
        @click="
          emit(
            'update:modelValue',
            modelValue.filter((value) => value !== id),
          )
        "
      >
        移除资料
      </button>
    </div>
    <p v-if="!modelValue.length" class="u-meta">
      未选择资料。生成有依据的议程前，请选择当前可访问的制度文件。
    </p>
    <p v-if="sources.length" class="u-meta">
      既有正文仍保留其来源权限依据，移除资料选择不会解除原文访问限制。
    </p>
    <ActionDialog :open="open" title="选择参考制度文件" wide @close="open = false">
      <div class="wb-stack">
        <form class="wb-actions" @submit.prevent="search">
          <label class="wb-field"
            ><span>文件标题、机关或标签</span
            ><input v-model="q" class="input" type="search" /></label
          ><button class="btn btn--ghost" type="submit" :disabled="loading">查询文件</button>
        </form>
        <LoadingBlock v-if="loading" variant="list" :rows="3" /><ErrorState
          v-else-if="error"
          :error="error"
        />
        <div v-else-if="docs.length" class="wb-table-wrap">
          <table class="wb-table">
            <thead>
              <tr>
                <th>文件</th>
                <th>层级 / 生效</th>
                <th>选择</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in docs" :key="doc.doc_id">
                <td>
                  {{ doc.title }}
                  <p class="u-meta">{{ doc.issuer }}</p>
                </td>
                <td>{{ DOC_LEVEL_LABELS[doc.level] }} / {{ doc.effective_date || '未标注' }}</td>
                <td>
                  <button
                    class="btn btn--ghost btn--sm"
                    type="button"
                    :disabled="modelValue.length >= 20 && !modelValue.includes(doc.doc_id)"
                    :aria-pressed="modelValue.includes(doc.doc_id)"
                    @click="toggle(doc)"
                  >
                    {{ modelValue.includes(doc.doc_id) ? '已选，点击移除' : '选择文件' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="wb-empty">没有可访问的匹配文件。</p>
        <div class="wb-pager">
          <button
            class="btn btn--quiet"
            type="button"
            :disabled="loading || page <= 1"
            @click="changePage(-1)"
          >
            上一页文件</button
          ><span>第 {{ page }} 页，共 {{ total }} 条</span
          ><button
            class="btn btn--quiet"
            type="button"
            :disabled="loading || page * 15 >= total"
            @click="changePage(1)"
          >
            下一页文件</button
          ><button class="btn btn--primary" type="button" @click="open = false">完成选择</button>
        </div>
      </div>
    </ActionDialog>
  </div>
</template>
