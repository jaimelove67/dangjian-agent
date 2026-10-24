<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getOwnArchive, listOwnMaterials, submitOwnMaterial, downloadMaterial, formatFileSize, MATERIAL_CATEGORIES, type MaterialCategory, type MaterialList, type PersonalArchive, type PersonalMaterial } from '@/api/member-self'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { uuid } from '@/utils/uuid'

const archive = ref<PersonalArchive | null>(null)
const list = ref<MaterialList | null>(null)
const page = ref(1)
const loading = ref(true)
const error = ref<unknown>(null)
const submissionError = ref<unknown>(null)
const success = ref('')
const submitting = ref(false)
const downloading = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)
let submissionKey = uuid()
const form = reactive({ title: '', category: 'thought_report' as MaterialCategory, description: '', file: null as File | null })
watch(() => [form.title, form.category, form.description, form.file], () => { submissionKey = uuid() })
const limit = computed(() => archive.value?.max_upload_size ?? 10 * 1024 * 1024)
const tooLarge = computed(() => !!form.file && form.file.size > limit.value)
const valid = computed(() => !!archive.value?.profile && !!form.title.trim() && !!form.file?.size && !tooLarge.value)
async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try { [archive.value, list.value] = await Promise.all([getOwnArchive(), listOwnMaterials(page.value)]) }
  catch (err) { error.value = err }
  finally { loading.value = false }
}
function chooseFile(event: Event): void { form.file = (event.target as HTMLInputElement).files?.[0] ?? null }
async function submit(): Promise<void> {
  if (!valid.value || submitting.value || !form.file) return
  submitting.value = true
  submissionError.value = null
  success.value = ''
  try {
    await submitOwnMaterial({ ...form, title: form.title.trim(), file: form.file, submission_key: submissionKey })
    submissionKey = uuid()
    success.value = '材料已提交，待组织核验。'
    Object.assign(form, { title: '', description: '', file: null })
    if (input.value) input.value.value = ''
    page.value = 1
    await load()
  } catch (err) { submissionError.value = err }
  finally { submitting.value = false }
}
async function download(material: PersonalMaterial): Promise<void> {
  if (downloading.value) return
  downloading.value = material.id
  submissionError.value = null
  try { await downloadMaterial(material) }
  catch (err) { submissionError.value = err }
  finally { downloading.value = null }
}
function turnPage(delta: number): void { page.value += delta; void load() }
onMounted(load)
</script>

<template>
  <div class="materials">
    <PageHeader title="个人材料" description="提交本人材料，并查看已提交记录。原件仅向本人及授权组织人员提供。" />
    <p v-if="success" role="status" class="badge badge--ok">{{ success }}</p>
    <ErrorState v-if="submissionError" :error="submissionError" />
    <LoadingBlock v-if="loading" variant="list" :rows="4" />
    <ErrorState v-else-if="error" :error="error"><button class="btn btn--ghost" @click="load">重试</button></ErrorState>
    <template v-else>
      <EmptyState v-if="!archive?.profile" icon="people" title="尚未关联本人档案" body="请联系组织管理员关联本人档案后提交材料。" />
      <form v-else class="u-card materials__form" @submit.prevent="submit">
        <h2>提交材料</h2>
        <div class="field"><label for="material-title">材料标题</label><input id="material-title" v-model="form.title" class="input" maxlength="200" required :disabled="submitting" /></div>
        <div class="field"><label for="material-category">材料类型</label><select id="material-category" v-model="form.category" class="select" :disabled="submitting"><option v-for="(label, value) in MATERIAL_CATEGORIES" :key="value" :value="value">{{ label }}</option></select></div>
        <div class="field"><label for="material-description">材料说明（选填）</label><textarea id="material-description" v-model="form.description" class="textarea" rows="3" maxlength="2000" :disabled="submitting"></textarea></div>
        <div class="field"><label for="material-file">材料文件</label><input id="material-file" ref="input" type="file" accept=".pdf,.PDF,.docx,.DOCX,.txt,.TXT,.md,.MD,.png,.PNG,.jpg,.JPG,.jpeg,.JPEG" required :disabled="submitting" @change="chooseFile" /><p class="u-meta">支持 PDF、DOCX、文本、PNG、JPG；单个文件不超过 {{ formatFileSize(limit) }}。</p><p v-if="tooLarge" role="alert">文件超过大小限制，请重新选择。</p></div>
        <p class="u-meta">提交记录不等于审核通过，不会自动修改本人阶段或组织登记的材料清单。</p>
        <button class="btn btn--primary" :disabled="!valid || submitting">{{ submitting ? '提交中' : '提交材料' }}</button>
      </form>
      <section class="u-card materials__records">
        <h2>已提交材料 <span class="u-meta">{{ list?.total ?? 0 }} 项</span></h2>
        <p v-if="!list?.items.length" class="u-meta">暂无提交记录。</p>
        <article v-for="material in list?.items" :key="material.id" class="materials__item">
          <div><h3>{{ material.title }}</h3><p class="u-meta">{{ MATERIAL_CATEGORIES[material.category] }} · {{ material.file_name }} · {{ formatFileSize(material.file_size) }}</p><p v-if="material.description">{{ material.description }}</p><time class="u-meta">{{ material.created_at.replace('T', ' ').slice(0, 19) }}</time></div>
          <span class="badge">已提交，待组织核验</span>
          <button class="btn btn--ghost" :disabled="downloading !== null" @click="download(material)">下载原件</button>
        </article>
        <div v-if="list && list.total > 20" class="materials__paging"><button class="btn btn--ghost" :disabled="page === 1" @click="turnPage(-1)">上一页</button><span>第 {{ page }} 页</span><button class="btn btn--ghost" :disabled="page * 20 >= list.total" @click="turnPage(1)">下一页</button></div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.materials { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6); min-width: 0; }
.materials__form, .materials__records { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5); }
.materials__form > .btn { align-self: flex-start; }
.materials__item { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); border-top: var(--border); padding-top: var(--space-4); }
.materials__item > div { flex: 1; min-width: min(240px, 100%); overflow-wrap: anywhere; }
.materials__item p { margin-top: var(--space-1); }
.materials__paging { display: flex; align-items: center; gap: var(--space-3); }
input[type=file] { max-width: 100%; }
</style>
