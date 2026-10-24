<script setup lang="ts">
import { computed } from 'vue'

import type { Citation } from '@/api/types'

/**
 * 引用溯源卡。
 *
 * 这是本产品最核心的视觉元素：每一条回答里的 [n] 角标，都对应一张
 * 可核验的来源卡。因此卡片的信息层级严格按"核验顺序"排列：
 *   1. 出处主体（发文机关 + 文号）—— 先确认"谁说的"
 *   2. 具体位置（条款）
 *   3. 原文片段 —— 再确认"说了什么"
 *   4. 相关度 —— 最后才是机器打分，弱化展示避免误导
 *
 * 相关度刻意不做成进度条/环形图：检索分数不是"可信度百分比"，
 * 用图形强化会让人误读为结论强度。仅以文字+等宽数字呈现。
 */

const props = defineProps<{ citation: Citation; index: number }>()

/** 后端检索分数量纲不统一，统一裁剪到两位小数展示 */
const scoreText = computed(() => {
  const s = props.citation.score
  if (typeof s !== 'number' || Number.isNaN(s)) return ''
  return s.toFixed(2)
})

/** 相关度分档：仅用于文字描述，不用于着色断言 */
const scoreBand = computed(() => {
  const s = props.citation.score
  if (typeof s !== 'number' || Number.isNaN(s)) return ''
  if (s >= 0.8) return '高度匹配'
  if (s >= 0.5) return '较相关'
  return '相关度偏低'
})

const anchorId = computed(() => `cite-${props.index}`)
</script>

<template>
  <article :id="anchorId" class="cite">
    <span class="cite__marker" aria-hidden="true">{{ index }}</span>

    <div class="cite__body">
      <header class="cite__head">
        <h3 class="cite__title">{{ citation.title }}</h3>
      </header>

      <dl class="cite__facts">
        <div class="cite__fact"><dt>文档编号</dt><dd class="u-mono">{{ citation.doc_id }}</dd></div>
        <div v-if="citation.file_name" class="cite__fact"><dt>文件名</dt><dd>{{ citation.file_name }}</dd></div>
        <div v-if="citation.effective_date" class="cite__fact"><dt>生效日期</dt><dd>{{ citation.effective_date }}</dd></div>
        <div class="cite__fact">
          <dt>发文机关</dt>
          <dd>{{ citation.issuer }}</dd>
        </div>
        <div v-if="citation.doc_number" class="cite__fact">
          <dt>文号</dt>
          <dd class="u-mono">{{ citation.doc_number }}</dd>
        </div>
        <div v-if="citation.article" class="cite__fact">
          <dt>条款</dt>
          <dd>{{ citation.article }}</dd>
        </div>
      </dl>

      <blockquote class="cite__excerpt">
        <p>{{ citation.content }}</p>
      </blockquote>

      <footer v-if="scoreText" class="cite__foot">
        <span class="u-meta">检索相关度</span>
        <span class="u-mono cite__score">{{ scoreText }}</span>
        <span class="u-meta">{{ scoreBand }}</span>
        <span class="cite__foot-hint u-meta">相关度为机器检索排序依据，不作为结论强度</span>
      </footer>
    </div>
  </article>
</template>

<style scoped>
.cite {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
  scroll-margin-top: calc(var(--nav-h) + var(--space-4));
  transition: border-color var(--dur) var(--ease);
}

.cite:hover {
  border-color: var(--rule-strong);
}

/* 角标：与正文中的 [n] 视觉同源，形成"点这里回原文"的直觉 */
.cite__marker {
  display: grid;
  place-items: center;
  flex: none;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  font-weight: 600;
  color: var(--accent-deep);
  background: var(--accent-wash);
  border: 1px solid var(--accent-edge);
  border-radius: var(--radius-xs);
}

.cite__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.cite__title {
  font-family: var(--font-serif);
  font-size: var(--text-md);
  font-weight: 600;
  line-height: var(--leading-snug);
  color: var(--ink);
}

.cite__facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.cite__fact {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.cite__fact dt {
  font-size: var(--text-xs);
  color: var(--ink-faint);
}

.cite__fact dd {
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

/* 原文片段：用左侧竖线而非整块灰底，保持纸面感 */
.cite__excerpt {
  padding-left: var(--space-3);
  border-left: 2px solid var(--rule);
}

.cite__excerpt p {
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

.cite__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  padding-top: var(--space-1);
}

.cite__score {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink-soft);
}

.cite__foot-hint {
  flex-basis: 100%;
  font-size: var(--text-2xs);
  color: var(--ink-faint);
}

@media (max-width: 560px) {
  .cite {
    padding: var(--space-3);
  }

  .cite__facts {
    flex-direction: column;
    gap: var(--space-1);
  }
}
</style>
