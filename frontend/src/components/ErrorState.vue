<script setup lang="ts">
import { computed } from 'vue'

import { ApiError } from '@/api/http'
import AppIcon from '@/components/AppIcon.vue'

/**
 * 错误态。
 *
 * 关键要求：错误必须可排障。因此除了一句人话解释，还要：
 *   - 按错误类型给出**可操作**的下一步（不是笼统的"请重试"）
 *   - 展示 trace_id，让用户能直接粘贴给后端排查（后端全链路透传 X-Request-ID）
 *   - 承载服务端返回的原始 message，不吞掉
 */
const props = defineProps<{ error: unknown }>()

const asApiError = computed(() =>
  props.error instanceof ApiError ? props.error : null,
)

const title = computed(() => {
  const e = asApiError.value
  if (!e) return '加载失败'
  if (e.isAuthError) return '登录状态已失效'
  if (e.isTenantIsolation) return '数据范围校验未通过'
  if (e.code === 40301) return '权限不足'
  if (e.code === 42901) return '请求过于频繁'
  if (e.code === 50301) return '依赖服务暂不可用'
  if (e.httpStatus === undefined) return '无法连接到服务'
  return '请求未成功'
})

const body = computed(() => {
  const e = asApiError.value
  return e?.message ?? '发生了未预期的错误，请重试。'
})

const hint = computed(() => {
  const e = asApiError.value
  if (!e) return ''
  if (e.isAuthError) return '请重新登录后继续操作。'
  if (e.isTenantIsolation) {
    return '当前账号所属组织无权访问该数据。请确认查询对象是否在本组织范围内。'
  }
  if (e.httpStatus === undefined) {
    return '请确认后端服务已在 8000 端口启动，或检查开发代理是否生效。'
  }
  if (e.code === 50301) return '通常是向量库或大模型服务未就绪，请检查 /api/v1/health/ready。'
  if (e.code === 42901) return '稍候片刻再试；同一问题的重复提问会命中缓存。'
  return ''
})

const traceId = computed(() => asApiError.value?.traceId ?? '')
</script>

<template>
  <div class="state err" role="alert">
    <span class="state__glyph err__glyph">
      <AppIcon name="error" :size="18" />
    </span>
    <p class="state__title">{{ title }}</p>
    <p class="state__body">{{ body }}</p>
    <p v-if="hint" class="err__hint">{{ hint }}</p>

    <div v-if="traceId" class="err__trace">
      <span class="u-meta">请求标识</span>
      <code class="u-mono">{{ traceId }}</code>
      <span class="u-meta">（反馈问题时请提供此标识）</span>
    </div>

    <div v-if="$slots.default" class="err__actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.err__glyph {
  color: var(--bad-ink);
  border-color: var(--bad-edge);
  background: var(--bad-wash);
}

.err__hint {
  max-width: 46ch;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

.err__trace {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
}

.err__trace code {
  color: var(--ink-soft);
}

.err__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
