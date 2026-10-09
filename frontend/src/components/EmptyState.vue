<script setup lang="ts">
/**
 * 空态。
 *
 * 空态必须回答三个问题，否则就是"死胡同"：
 *   1. 为什么这里是空的（title）
 *   2. 我能做什么（body + 可选操作槽）
 *
 * 图形使用线框方块而非插画：编辑式调性下，插画会立刻把页面拉向营销风格。
 */
import AppIcon, { type IconName } from '@/components/AppIcon.vue'

withDefaults(
  defineProps<{
    title: string
    body?: string
    icon?: IconName
  }>(),
  { body: '', icon: 'empty' },
)
</script>

<template>
  <div class="state">
    <span class="state__glyph">
      <AppIcon :name="icon" :size="18" />
    </span>
    <p class="state__title">{{ title }}</p>
    <p v-if="body" class="state__body">{{ body }}</p>
    <div v-if="$slots.default" class="state__slot">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.state__slot {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
