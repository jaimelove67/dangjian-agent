<script lang="ts" setup>
/**
 * 知识库文档列表页
 *
 * 注意：后端目前只有「创建 / 按 id 查 / 改状态」三个接口，缺少列表分页接口。
 * Mock 模式下列表可用；切换真实接口前需后端补 GET /api/v1/knowledge-docs。
 */
import 'element-plus/es/components/message/style/css';
import 'element-plus/es/components/option/style/css';
import 'element-plus/es/components/pagination/style/css';
import 'element-plus/es/components/select/style/css';
import 'element-plus/es/components/table-column/style/css';
import 'element-plus/es/components/table/style/css';
import 'element-plus/es/components/tag/style/css';

import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import {
  ElButton,
  ElInput,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus';

import {
  DOC_LEVELS,
  listKnowledgeDocsApi,
  updateDocStatusApi,
} from '#/api/party/knowledge';
import type { KnowledgeDoc } from '#/api/party/types';

const router = useRouter();

const loading = ref(false);
const rows = ref<KnowledgeDoc[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(10);
const keyword = ref('');
const levelFilter = ref('');
const statusFilter = ref('');

const STATUS_OPTIONS = [
  { label: '现行有效', value: 'effective' },
  { label: '已失效', value: 'expired' },
  { label: '已废止', value: 'abolished' },
];

function statusLabel(status: KnowledgeDoc['status']): string {
  return STATUS_OPTIONS.find((item) => item.value === status)?.label ?? status;
}

function statusTagType(
  status: KnowledgeDoc['status'],
): 'info' | 'success' | 'warning' {
  if (status === 'effective') {
    return 'success';
  }
  return status === 'expired' ? 'warning' : 'info';
}

function securityTagType(
  securityLevel: string,
): 'danger' | 'info' | 'success' | 'warning' {
  const map: Record<string, 'danger' | 'info' | 'success' | 'warning'> = {
    公开: 'success',
    内部: 'info',
    秘密: 'warning',
    机密: 'danger',
  };
  return map[securityLevel] ?? 'info';
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const result = await listKnowledgeDocsApi({
      page: page.value,
      pageSize: pageSize.value,
      keyword: keyword.value,
      level: levelFilter.value || undefined,
      status: statusFilter.value || undefined,
    });
    rows.value = result.items;
    total.value = result.total;
  } catch {
    ElMessage.error('加载文档列表失败');
  } finally {
    loading.value = false;
  }
}

function handleSearch(): void {
  page.value = 1;
  load();
}

function handleReset(): void {
  keyword.value = '';
  levelFilter.value = '';
  statusFilter.value = '';
  page.value = 1;
  load();
}

async function handleStatusChange(
  row: KnowledgeDoc,
  next: KnowledgeDoc['status'],
): Promise<void> {
  if (next === row.status) {
    return;
  }
  const previous = row.status;
  try {
    await updateDocStatusApi(row.id, next);
    row.status = next;
    ElMessage.success(`已将「${row.title}」变更为${statusLabel(next)}`);
  } catch {
    row.status = previous;
    ElMessage.error('状态变更失败');
  }
}

function goIntake(): void {
  router.push('/party/knowledge-intake');
}

onMounted(load);
</script>

<template>
  <div class="party-doc-list">
    <header class="page-header">
      <div>
        <div class="page-title">知识库文档管理</div>
        <div class="page-crumb">
          共 {{ total }} 篇文档 · 失效与废止文件不会参与检索问答
        </div>
      </div>
      <ElButton type="primary" @click="goIntake">文档入库</ElButton>
    </header>

    <div class="filter-bar">
      <ElInput
        v-model="keyword"
        class="filter-keyword"
        placeholder="搜索文件标题 / 发布机关 / 发文字号"
        clearable
        @keydown.enter="handleSearch"
      />
      <ElSelect
        v-model="levelFilter"
        class="filter-select"
        placeholder="文件层级"
        clearable
      >
        <ElOption v-for="item in DOC_LEVELS" :key="item" :label="item" :value="item" />
      </ElSelect>
      <ElSelect
        v-model="statusFilter"
        class="filter-select"
        placeholder="文件状态"
        clearable
      >
        <ElOption
          v-for="item in STATUS_OPTIONS"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </ElSelect>
      <ElButton type="primary" @click="handleSearch">查询</ElButton>
      <ElButton @click="handleReset">重置</ElButton>
    </div>

    <ElTable
      v-loading="loading"
      :data="rows"
      class="doc-table"
      row-key="id"
      stripe
    >
      <ElTableColumn prop="title" label="文件标题" min-width="220" show-overflow-tooltip />
      <ElTableColumn prop="issuer" label="发布机关" width="150" show-overflow-tooltip />
      <ElTableColumn prop="docNumber" label="发文字号" width="160" show-overflow-tooltip />
      <ElTableColumn prop="level" label="层级" width="90" />
      <ElTableColumn label="密级" width="90">
        <template #default="{ row }">
          <ElTag :type="securityTagType(row.securityLevel)" effect="light" size="small">
            {{ row.securityLevel }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="110">
        <template #default="{ row }">
          <ElTag :type="statusTagType(row.status)" effect="light" size="small">
            {{ statusLabel(row.status) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="effectiveDate" label="生效日期" width="120" />
      <ElTableColumn label="失效日期" width="120">
        <template #default="{ row }">
          {{ row.expirationDate || '长期有效' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="变更状态" width="140" fixed="right">
        <template #default="{ row }">
          <ElSelect
            :model-value="row.status"
            size="small"
            @change="(value) => handleStatusChange(row, value)"
          >
            <ElOption
              v-for="item in STATUS_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </ElSelect>
        </template>
      </ElTableColumn>
    </ElTable>

    <div class="table-footer">
      <ElPagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="handleSearch"
      />
    </div>
  </div>
</template>

<style scoped>
.party-doc-list {
  --line: rgba(0, 0, 0, 0.12);
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

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 0.5px solid var(--line);
}

.filter-keyword {
  width: 260px;
}

.filter-select {
  width: 130px;
}

.doc-table {
  width: 100%;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 0.5px solid var(--line);
}
</style>
