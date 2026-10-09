<script setup lang="ts">
/**
 * 骨架屏。
 *
 * 用骨架条而非转圈（Section 4.5）：加载过程中版面结构保持稳定，
 * 内容落地时不会发生整页跳动。
 *
 * variant 对应本产品的三种真实加载形状，不做通用化。
 */
withDefaults(
  defineProps<{
    variant?: 'answer' | 'table' | 'list'
    rows?: number
  }>(),
  { variant: 'list', rows: 4 },
)
</script>

<template>
  <div class="skel-wrap" aria-busy="true" aria-live="polite">
    <span class="u-sr">内容加载中</span>

    <!-- 回答加载：模仿"答案段 + 来源卡"的真实结构 -->
    <template v-if="variant === 'answer'">
      <div class="skel-answer">
        <div class="skel skel-line" style="width: 32%"></div>
        <div class="skel skel-line" style="width: 100%"></div>
        <div class="skel skel-line" style="width: 96%"></div>
        <div class="skel skel-line" style="width: 88%"></div>
        <div class="skel skel-line" style="width: 64%; margin-bottom: var(--space-3)"></div>
        <div class="skel skel-line" style="width: 92%"></div>
        <div class="skel skel-line" style="width: 78%"></div>
      </div>
    </template>

    <!-- 表格加载：整行骨架，列宽与真实表格对齐 -->
    <template v-else-if="variant === 'table'">
      <div class="skel-table">
        <div v-for="i in rows" :key="i" class="skel-row">
          <div class="skel skel-line" style="width: 28%"></div>
          <div class="skel skel-line" style="width: 18%"></div>
          <div class="skel skel-line" style="width: 14%"></div>
          <div class="skel skel-line" style="width: 22%"></div>
          <div class="skel skel-line" style="width: 10%"></div>
        </div>
      </div>
    </template>

    <!-- 列表加载：卡片形状 -->
    <template v-else>
      <div v-for="i in rows" :key="i" class="skel-card">
        <div class="skel skel-line" style="width: 40%"></div>
        <div class="skel skel-line" style="width: 88%"></div>
        <div class="skel skel-line" style="width: 72%"></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.skel-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skel-answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
}

.skel-table {
  display: flex;
  flex-direction: column;
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.skel-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  height: var(--row-h);
  padding: 0 var(--space-3);
  border-bottom: var(--border);
}

.skel-row:last-child {
  border-bottom: 0;
}

.skel-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
}
</style>
