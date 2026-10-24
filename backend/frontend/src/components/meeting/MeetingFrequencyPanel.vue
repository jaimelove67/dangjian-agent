<script setup lang="ts">
import { computed } from 'vue'

import type { MeetingFrequency, MeetingFrequencyRow, FrequencyState } from '@/api/meeting'

/**
 * 组织生活频次合规提醒面板（三会一课 + 组织生活会）。
 *
 * 只在「年度统计」工作区里出现，数据来自 `/meeting/frequency`。三块内容按使用者
 * 关心的顺序排：先是要动手的（本周期提醒），再是全景（逐支部逐类型），最后是
 * 已无法改变的（已结束周期缺口）。缺口必须与当前周期提醒分开，否则支部书记会
 * 把"上季度没达标"当成"这季度再补一次就行"。
 */
const props = withDefaults(defineProps<{ frequency: MeetingFrequency | null }>(), {
  frequency: null,
})

const STATE_LABELS: Record<FrequencyState, string> = {
  met: '已达要求',
  awaiting_review: '已召开待审核',
  open: '本周期未达标',
}
const STATE_TONES: Record<FrequencyState, string> = {
  met: 'badge badge--ok',
  awaiting_review: 'badge badge--warn',
  open: 'badge badge--bad',
}

// 同一类型在多支部下会重复出现，依据只需展示一次
const bases = computed(() => {
  const seen = new Map<string, MeetingFrequencyRow>()
  for (const row of props.frequency?.rows ?? []) {
    if (!seen.has(row.activity_type)) seen.set(row.activity_type, row)
  }
  return [...seen.values()]
})

const showOrg = computed(() => (props.frequency?.branch_count ?? 0) > 1)

function gapText(row: MeetingFrequencyRow): string {
  if (row.state === 'met') return '—'
  // 已召开未过审：缺口来自"没审"，写明究竟几次待审，而不是笼统一句"差 1 次"
  if (row.state === 'awaiting_review') return `待审核 ${row.awaiting_review} 次`
  const parts: string[] = [`差 ${row.missing} 次`]
  if (row.scheduled) parts.push(`已安排 ${row.scheduled} 次`)
  return parts.join('，')
}
</script>

<template>
  <section v-if="frequency" class="meeting-frequency wb-stack">
    <div class="wb-toolbar">
      <h2>组织生活频次合规</h2>
      <span class="u-meta">截至 {{ frequency.as_of }} · {{ frequency.branch_count }} 个支部</span>
    </div>
    <p class="wb-note">{{ frequency.calculation_rule }}</p>

    <div class="wb-section">
      <h3>本周期需处理（{{ frequency.reminders.length }}）</h3>
      <ul v-if="frequency.reminders.length" class="meeting-frequency__todo">
        <li v-for="item in frequency.reminders" :key="`${item.org_unit_id}-${item.activity_type}`">
          <span class="badge" :class="STATE_TONES[item.state]">{{ STATE_LABELS[item.state] }}</span>
          <span>{{ item.org_unit_name }} · {{ item.reminder }}</span>
        </li>
      </ul>
      <p v-else-if="!frequency.branch_count" class="wb-note">
        当前范围内没有可提示的支部；组织生活按支部计算，请选择或补充支部组织。
      </p>
      <p v-else class="wb-note">本周期各支部组织生活均已达标。</p>
    </div>

    <div v-if="frequency.rows.length" class="wb-table-wrap">
      <table class="wb-table">
        <caption class="u-meta">
          本周期口径；"已通过"只统计已召开且人工审核通过的记录
        </caption>
        <thead>
          <tr>
            <th v-if="showOrg">支部</th>
            <th>活动类型</th>
            <th>本周期</th>
            <th>周期要求</th>
            <th>已通过</th>
            <th>待审核</th>
            <th>缺口</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in frequency.rows" :key="`${row.org_unit_id}-${row.activity_type}`">
            <td v-if="showOrg">{{ row.org_unit_name }}</td>
            <td>{{ row.activity_type_label }}</td>
            <td>{{ row.period_label }}</td>
            <td>
              {{ row.period_text }}
              <span class="u-meta">（年度 {{ row.annual_required }} 次）</span>
            </td>
            <td>{{ row.performed }}</td>
            <td>{{ row.awaiting_review }}</td>
            <td>{{ gapText(row) }}</td>
            <td>
              <span :class="STATE_TONES[row.state]">{{ STATE_LABELS[row.state] }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <details v-if="frequency.gaps.length" class="wb-disclosure">
      <summary>已结束周期缺口（{{ frequency.gaps.length }}）</summary>
      <p class="wb-note">
        已结束的周期无法补记：缺口不会因为之后多开一次而消失，请在台账中说明原因。
      </p>
      <ul class="meeting-frequency__gaps">
        <li v-for="gap in frequency.gaps" :key="`${gap.org_unit_id}-${gap.activity_type}`">
          {{ gap.text }}
        </li>
      </ul>
    </details>

    <details class="wb-disclosure">
      <summary>频次依据</summary>
      <ul class="meeting-frequency__bases">
        <li v-for="row in bases" :key="row.activity_type">
          {{ row.activity_type_label }}：{{ row.basis }}
        </li>
      </ul>
    </details>

    <p v-for="item in frequency.missing" :key="item" class="field__error">{{ item }}</p>
    <p class="wb-note">{{ frequency.notice }}</p>
  </section>
</template>

<style scoped>
/* 全局把 ul 的间距清零了，这里自己给回列表项之间的呼吸位 */
.meeting-frequency__todo,
.meeting-frequency__gaps,
.meeting-frequency__bases {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.meeting-frequency__todo li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

/* 状态标签不能被长文案挤压变形 */
.meeting-frequency__todo .badge {
  flex: none;
}

.meeting-frequency__gaps {
  margin-top: var(--space-3);
}

.meeting-frequency__bases li {
  color: var(--ink-muted);
}
</style>
