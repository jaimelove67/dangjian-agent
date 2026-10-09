<script setup lang="ts">
/**
 * 页面头。
 *
 * 编辑式排版的关键：标题与说明左对齐成栏，右侧留给操作，中间用一条
 * 极细分隔线与内容区断开。不使用居中大标题（那是落地页的做法）。
 *
 * EYEBROW RESTRAINT：eyebrow 为可选项，调用方自行控制使用频率。
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    eyebrow?: string
  }>(),
  { description: '', eyebrow: '' },
)
</script>

<template>
  <header class="page-head">
    <div class="page-head__text">
      <span v-if="eyebrow" class="u-eyebrow page-head__eyebrow">{{ eyebrow }}</span>
      <h1 class="u-title-page">{{ title }}</h1>
      <p v-if="description" class="page-head__desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-head__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-6);
  padding-bottom: var(--space-5);
  border-bottom: var(--border);
}

.page-head__text {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 62ch;
}

.page-head__eyebrow {
  margin-bottom: var(--space-1);
}

.page-head__desc {
  font-size: var(--text-md);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.page-head__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
    gap: var(--space-4);
  }

  .page-head__actions {
    width: 100%;
  }
}
</style>
