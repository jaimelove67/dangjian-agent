<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

/**
 * 核验警告清单。
 *
 * 语义：这些是**引用核验器**（app/rag/verifier.py）产出的机器提示，包含
 * 三类完全不同的严重度，界面必须区分，不能一律染黄：
 *
 *   - 引用被移除（引用[n]不存在，已从答案中移除）→ 危险，答案已被改写
 *   - 条款不符（提及的条款在被引片段中不存在）    → 需人工复核
 *   - 时效提醒（已失效 / 即将失效 / 已废止）      → 注意
 *   - 未标注来源（长回答无任何来源）              → 需人工复核
 *
 * 分档规则基于提示文案的关键词。这是脆弱的字符串匹配，但后端目前不返回
 * 结构化的严重度字段；一旦后端补充该字段，应立刻替换此处实现。
 */

const props = defineProps<{ warnings: string[] }>()

type Tone = 'bad' | 'warn'

interface GradedWarning {
  text: string
  tone: Tone
}

const SEVERE_PATTERNS = [/从答案中移除/, /不存在/, /未标注任何来源/]

function grade(warnings: string[]): GradedWarning[] {
  return warnings.map((text) => ({
    text,
    tone: SEVERE_PATTERNS.some((re) => re.test(text)) ? 'bad' : 'warn',
  }))
}

const graded = computed(() => grade(props.warnings))
</script>

<template>
  <section v-if="graded.length" class="warns" aria-label="引用核验提示">
    <header class="warns__head">
      <AppIcon name="alert" :size="15" />
      <h2 class="warns__title">
        引用核验提示
        <span class="u-num warns__count">{{ graded.length }}</span>
      </h2>
    </header>

    <ul class="warns__list">
      <li v-for="(w, i) in graded" :key="i" class="warns__item" :class="`is-${w.tone}`">
        <span class="badge" :class="w.tone === 'bad' ? 'badge--bad' : 'badge--warn'">
          {{ w.tone === 'bad' ? '需复核' : '时效' }}
        </span>
        <p class="warns__text">{{ w.text }}</p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.warns {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
}

.warns__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--warn-ink);
}

.warns__title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
}

.warns__count {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  margin-left: var(--space-1);
  padding: 0 4px;
  font-size: var(--text-2xs);
  color: var(--ink-muted);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-xs);
}

.warns__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.warns__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border-left: 2px solid var(--warn-edge);
  background: var(--warn-wash);
}

.warns__item.is-bad {
  border-left-color: var(--bad-edge);
  background: var(--bad-wash);
}

.warns__text {
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

@media (max-width: 560px) {
  .warns__item {
    flex-direction: column;
    gap: var(--space-2);
  }
}
</style>
