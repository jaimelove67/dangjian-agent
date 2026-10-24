<script setup lang="ts">
import { RouterLink } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
</script>

<template>
  <div class="nf">
    <span class="u-eyebrow">错误 404</span>
    <h1 class="nf__title">这个页面不存在</h1>
    <p class="nf__text">
      地址可能有误，或者该页面已被调整。可以返回问答界面继续使用。
    </p>
    <RouterLink to="/ask" class="btn btn--primary">
      <AppIcon name="ask" :size="15" />
      <span>返回制度问答</span>
    </RouterLink>
  </div>
</template>

<style scoped>
.nf {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-4);
  justify-content: center;
  min-height: 100dvh;
  max-width: 52ch;
  margin: 0 auto;
  padding: var(--space-10) var(--space-6);
}

.nf__title {
  font-family: var(--font-serif);
  font-size: var(--text-2xl);
  font-weight: 600;
  letter-spacing: var(--tracking-tight);
  color: var(--ink);
}

.nf__text {
  font-size: var(--text-md);
  line-height: var(--leading-loose);
  color: var(--ink-muted);
}
</style>
