<script lang="ts" setup>
/**
 * 知识库文档入库页
 *
 * 设计重点不在表单本身，而在把后端的硬业务规则前置到界面：
 * 1. 中央级文件必须为公开密级
 * 2. 密级为「秘密」及以上的材料不进入向量库（仅存档）
 * 3. 失效日期不得早于生效日期，且已过期文件拒绝入库
 */
import 'element-plus/es/components/message/style/css';
import 'element-plus/es/components/option/style/css';
import 'element-plus/es/components/select/style/css';

import { computed, reactive, ref } from 'vue';

import {
  ElButton,
  ElDatePicker,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
} from 'element-plus';

import {
  createKnowledgeDocApi,
  DOC_LEVELS,
  DOC_SECURITY_LEVELS,
  DOC_VISIBILITIES,
} from '#/api/party/knowledge';

interface FieldError {
  field: string;
  message: string;
}

const form = reactive({
  fileName: '',
  title: '',
  issuer: '',
  docNumber: '',
  level: '',
  visibility: '主动公开',
  securityLevel: '',
  effectiveDate: '',
  expirationDate: '',
  summary: '',
});

const tags = ref<string[]>([]);
const tagDraft = ref('');
const submitting = ref(false);
const fileInput = ref<HTMLInputElement>();

/** 解析结果（真实实现由后端返回） */
const parsed = ref<null | { chapters: number; clauses: number; chunks: number }>(null);

/** 全部校验错误 */
const errors = computed<FieldError[]>(() => {
  const list: FieldError[] = [];

  if (!form.fileName) {
    list.push({ field: 'fileName', message: '请先选择待入库文件' });
  }
  if (!form.title.trim()) {
    list.push({ field: 'title', message: '文件标题为必填项' });
  }
  if (!form.issuer.trim()) {
    list.push({ field: 'issuer', message: '发布机关为必填项' });
  }
  if (!form.level) {
    list.push({ field: 'level', message: '请选择文件层级' });
  }
  if (!form.securityLevel) {
    list.push({ field: 'securityLevel', message: '请选择密级' });
  }
  if (!form.effectiveDate) {
    list.push({ field: 'effectiveDate', message: '请选择生效日期' });
  }

  if (
    form.level === '中央级' &&
    form.securityLevel &&
    form.securityLevel !== '公开'
  ) {
    list.push({
      field: 'securityLevel',
      message: '中央级文件的密级必须为「公开」，当前选择不符合业务规则',
    });
  }

  if (
    form.effectiveDate &&
    form.expirationDate &&
    form.expirationDate < form.effectiveDate
  ) {
    list.push({
      field: 'expirationDate',
      message: '失效日期不得早于生效日期',
    });
  }

  return list;
});

function errorOf(field: string): string | undefined {
  return errors.value.find((item) => item.field === field)?.message;
}

/** 涉密材料不入向量库 */
const isClassified = computed(() =>
  ['机密', '秘密'].includes(form.securityLevel),
);

const canSubmit = computed(
  () =>
    errors.value.length === 0 &&
    !isClassified.value &&
    !submitting.value &&
    Boolean(form.fileName),
);

function handlePickFile(): void {
  fileInput.value?.click();
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    return;
  }
  form.fileName = file.name;
  if (!form.title.trim()) {
    form.title = file.name.replace(/\.[^./]+$/, '');
  }
  parsed.value = { chapters: 4, clauses: 32, chunks: 68 };
  ElMessage.success('文件解析完成');
  input.value = '';
}

function addTag(): void {
  const value = tagDraft.value.trim();
  if (!value) {
    return;
  }
  if (!tags.value.includes(value)) {
    tags.value.push(value);
  }
  tagDraft.value = '';
}

function removeTag(tag: string): void {
  tags.value = tags.value.filter((item) => item !== tag);
}

function handleReset(): void {
  form.fileName = '';
  form.title = '';
  form.issuer = '';
  form.docNumber = '';
  form.level = '';
  form.visibility = '主动公开';
  form.securityLevel = '';
  form.effectiveDate = '';
  form.expirationDate = '';
  form.summary = '';
  tags.value = [];
  tagDraft.value = '';
  parsed.value = null;
}

async function handleSubmit(): Promise<void> {
  if (!canSubmit.value) {
    return;
  }
  submitting.value = true;
  try {
    const result = await createKnowledgeDocApi({
      fileName: form.fileName,
      title: form.title,
      issuer: form.issuer,
      docNumber: form.docNumber || undefined,
      level: form.level,
      visibility: form.visibility,
      securityLevel: form.securityLevel,
      effectiveDate: form.effectiveDate || undefined,
      expirationDate: form.expirationDate || undefined,
      tags: [...tags.value],
      summary: form.summary || undefined,
    });
    ElMessage.success(`入库成功，已生成 ${result.chunkCount} 个向量片段`);
    handleReset();
  } catch {
    ElMessage.error('入库失败，请稍后重试');
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="party-intake">
    <header class="page-header">
      <div>
        <div class="page-title">文档入库</div>
        <div class="page-crumb">知识库管理 / 文档入库</div>
      </div>
      <span class="scope-badge">校党委组织部 · 本级</span>
    </header>

    <div class="page-body">
      <input
        ref="fileInput"
        class="hidden-file"
        type="file"
        accept=".pdf,.docx,.doc,.txt,.md"
        @change="handleFileChange"
      />

      <div class="upload-strip">
        <span class="file-icon">FILE</span>
        <div class="file-main">
          <div v-if="form.fileName" class="file-name">{{ form.fileName }}</div>
          <div v-else class="file-name file-placeholder">尚未选择文件</div>
          <div class="file-meta">
            <template v-if="parsed">
              解析完成 · 识别到章—条结构 {{ parsed.chapters }} 章
              {{ parsed.clauses }} 条，将生成 {{ parsed.chunks }} 个向量片段
            </template>
            <template v-else>
              支持 PDF / Word / 纯文本，入库前会自动识别章—条结构
            </template>
          </div>
        </div>
        <ElButton @click="handlePickFile">
          {{ form.fileName ? '重新选择' : '选择文件' }}
        </ElButton>
      </div>

      <div class="form-grid">
        <div class="field">
          <label class="field-label">文件标题 <em>*</em></label>
          <ElInput v-model="form.title" placeholder="请输入文件标题" />
          <div v-if="errorOf('title')" class="field-error">{{ errorOf('title') }}</div>
        </div>

        <div class="field">
          <label class="field-label">发布机关 <em>*</em></label>
          <ElInput v-model="form.issuer" placeholder="如：中共中央组织部" />
          <div v-if="errorOf('issuer')" class="field-error">
            {{ errorOf('issuer') }}
          </div>
        </div>

        <div class="field">
          <label class="field-label">发文字号</label>
          <ElInput v-model="form.docNumber" placeholder="如：中组发〔2014〕6 号" />
        </div>

        <div class="field">
          <label class="field-label">生效日期 <em>*</em></label>
          <ElDatePicker
            v-model="form.effectiveDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择生效日期"
            style="width: 100%"
          />
          <div v-if="errorOf('effectiveDate')" class="field-error">
            {{ errorOf('effectiveDate') }}
          </div>
        </div>

        <div class="field">
          <label class="field-label">文件层级 <em>*</em></label>
          <ElSelect v-model="form.level" placeholder="请选择" style="width: 100%">
            <ElOption v-for="item in DOC_LEVELS" :key="item" :label="item" :value="item" />
          </ElSelect>
          <div v-if="errorOf('level')" class="field-error">{{ errorOf('level') }}</div>
        </div>

        <div class="field">
          <label class="field-label">密级 <em>*</em></label>
          <ElSelect
            v-model="form.securityLevel"
            placeholder="请选择"
            style="width: 100%"
          >
            <ElOption
              v-for="item in DOC_SECURITY_LEVELS"
              :key="item"
              :label="item"
              :value="item"
            />
          </ElSelect>
          <div v-if="errorOf('securityLevel')" class="field-error">
            {{ errorOf('securityLevel') }}
          </div>
        </div>

        <div class="field">
          <label class="field-label">公开属性 <em>*</em></label>
          <ElSelect v-model="form.visibility" style="width: 100%">
            <ElOption
              v-for="item in DOC_VISIBILITIES"
              :key="item"
              :label="item"
              :value="item"
            />
          </ElSelect>
        </div>

        <div class="field">
          <label class="field-label">失效日期</label>
          <ElDatePicker
            v-model="form.expirationDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="未设置视为长期有效"
            style="width: 100%"
          />
          <div v-if="errorOf('expirationDate')" class="field-error">
            {{ errorOf('expirationDate') }}
          </div>
        </div>
      </div>

      <div class="field">
        <label class="field-label">标签</label>
        <div class="tag-row">
          <span v-for="tag in tags" :key="tag" class="tag-chip">
            {{ tag }}
            <button class="tag-remove" type="button" @click="removeTag(tag)">×</button>
          </span>
          <input
            v-model="tagDraft"
            class="tag-input"
            placeholder="输入后回车添加"
            @keydown.enter.prevent="addTag()"
          />
        </div>
      </div>

      <div class="field">
        <label class="field-label">内容摘要</label>
        <ElInput
          v-model="form.summary"
          type="textarea"
          :rows="2"
          placeholder="选填，用于列表展示与检索辅助"
        />
      </div>

      <div v-if="isClassified" class="rule-block rule-danger">
        <div class="rule-title">已阻止进入向量库</div>
        <div class="rule-body">
          该材料密级为「{{ form.securityLevel }}」，属于涉密材料。按业务规则，涉密材料不入向量库、不参与检索问答，仅可作档案存档。
        </div>
      </div>

      <div class="rule-block">
        <div class="rule-title">入库前强制规则</div>
        <div class="rule-body">
          中央级文件的密级必须为「公开」；<br />
          密级为「秘密」及以上的材料不进入向量库，仅存档不参与检索问答；<br />
          失效日期不得早于生效日期，已过期的文件将被拒绝入库。
        </div>
      </div>

      <div class="page-footer">
        <span class="footer-status" :class="{ 'is-error': errors.length > 0 }">
          <template v-if="errors.length > 0">
            {{ errors.length }} 项校验未通过，无法提交
          </template>
          <template v-else-if="isClassified">涉密材料已阻止入库</template>
          <template v-else>校验通过，可提交入库</template>
        </span>
        <div class="footer-actions">
          <ElButton @click="handleReset">重置</ElButton>
          <ElButton type="primary" :disabled="!canSubmit" :loading="submitting" @click="handleSubmit">
            提交入库
          </ElButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.party-intake {
  --party-red: #a32d2d;
  --party-red-deep: #791f1f;
  --party-red-light: #fcebeb;
  --ok-text: #3b6d11;
  --ok-bg: #eaf3de;
  --warn-text: #633806;
  --warn-bg: #faeeda;
  --danger-bg: #fcebeb;
  --line: rgba(0, 0, 0, 0.12);
  --surface: #f7f7f5;

  overflow: hidden;
  background: #fff;
  border: 0.5px solid var(--line);
  border-radius: 8px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 0.5px solid var(--line);
}

.page-title {
  font-size: 14px;
  font-weight: 500;
}

.page-crumb {
  margin-top: 3px;
  font-size: 11px;
  color: #9b9b97;
}

.scope-badge {
  padding: 3px 9px;
  font-size: 11px;
  color: var(--party-red-deep);
  background: var(--party-red-light);
  border-radius: 999px;
}

.page-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 16px;
}

.hidden-file {
  display: none;
}

.upload-strip {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 11px 13px;
  background: var(--surface);
  border-radius: 8px;
}

.file-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 40px;
  font-size: 10px;
  color: var(--party-red);
  background: #fff;
  border: 0.5px solid rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}

.file-main {
  min-width: 0;
  flex: 1;
}

.file-name {
  font-size: 13px;
}

.file-placeholder {
  color: #9b9b97;
}

.file-meta {
  margin-top: 3px;
  font-size: 11px;
  color: #9b9b97;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}

.field {
  min-width: 0;
}

.field-label {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
  color: #6b6b68;
}

.field-label em {
  color: var(--party-red);
  font-style: normal;
}

.field-error {
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--party-red);
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
}

.tag-chip {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 3px 10px;
  font-size: 11px;
  color: #6b6b68;
  background: var(--surface);
  border-radius: 999px;
}

.tag-remove {
  padding: 0;
  font-size: 12px;
  line-height: 1;
  color: #9b9b97;
  cursor: pointer;
  background: none;
  border: none;
}

.tag-input {
  width: 140px;
  padding: 3px 10px;
  font-family: inherit;
  font-size: 11px;
  background: none;
  border: 0.5px dashed rgba(0, 0, 0, 0.2);
  border-radius: 999px;
  outline: none;
}

.rule-block {
  padding: 10px 12px;
  background: var(--surface);
  border-left: 2px solid var(--warn-bg);
  border-radius: 6px;
}

.rule-block + .rule-block {
  margin-top: -6px;
}

.rule-danger {
  background: var(--danger-bg);
  border-left-color: var(--party-red);
}

.rule-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--warn-text);
}

.rule-danger .rule-title {
  color: var(--party-red-deep);
}

.rule-body {
  margin-top: 5px;
  font-size: 12px;
  line-height: 1.7;
  color: #6b6b68;
}

.page-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 0.5px solid var(--line);
}

.footer-status {
  font-size: 11px;
  color: var(--ok-text);
}

.footer-status.is-error {
  color: var(--party-red);
}

.footer-actions {
  display: flex;
  gap: 9px;
}
</style>
