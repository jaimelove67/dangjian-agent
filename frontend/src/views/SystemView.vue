<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { checkHealth, checkReady } from '@/api/qa'
import { API_SURFACE } from '@/api/surface'
import { ROLE_LABELS, DATA_LEVEL_LABELS, DATA_LEVEL_ROUTE } from '@/api/types'
import type { HealthResponse, DataLevel } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

/**
 * 系统状态。
 *
 * 三重职责：
 *   1. 后端连通性与就绪状态（真实接口 /health 与 /health/ready）
 *   2. 当前账号的身份与权限码一览，便于自查"为什么看不到某个菜单"
 *   3. **接口能力矩阵**：把后端"已具备 / 未提供"的接口如实列出来。
 *      这不是开发文档，而是使用者的必要认知：界面上标注"示例数据"的地方，
 *      对应的接口就在这张表里显示为未提供。
 */

const route = useRoute()
const deniedPath = computed(() => (typeof route.query.denied === 'string' ? route.query.denied : ''))

interface Probe {
  label: string
  run: () => Promise<HealthResponse>
}

const probes: Probe[] = [
  { label: '基础健康检查', run: checkHealth },
  { label: '就绪检查', run: checkReady },
]

interface ProbeResult {
  label: string
  loading: boolean
  data: HealthResponse | null
  error: unknown
}

const results = ref<ProbeResult[]>(
  probes.map((p) => ({ label: p.label, loading: true, data: null, error: null })),
)

async function runAll(): Promise<void> {
  await Promise.all(
    probes.map(async (p, i) => {
      const slot = results.value[i]!
      slot.loading = true
      slot.error = null
      try {
        slot.data = await p.run()
      } catch (err) {
        slot.error = err
        slot.data = null
      } finally {
        slot.loading = false
      }
    }),
  )
}

onMounted(runAll)

const user = computed(() => session.state.user)
const roleLabel = computed(() => (user.value ? ROLE_LABELS[user.value.role] : ''))

const DATA_LEVELS: DataLevel[] = ['public', 'internal', 'sensitive', 'classified']

const missingCount = computed(() => API_SURFACE.filter((s) => !s.available).length)
</script>

<template>
  <div class="sys">
    <PageHeader
      title="系统状态"
      description="查看后端连通情况、当前账号权限，以及各接口的接入状态。"
    >
      <template #actions>
        <button class="btn btn--ghost" type="button" @click="runAll">
          <AppIcon name="pulse" :size="14" />
          <span>重新检测</span>
        </button>
      </template>
    </PageHeader>

    <!-- 权限不足提示：被路由守卫拦下来时给出可执行的解释 -->
    <section v-if="deniedPath" class="denied" role="alert">
      <AppIcon name="shield" :size="16" />
      <div>
        <p class="denied__title">无法访问该页面</p>
        <p class="denied__text">
          当前账号缺少访问 <code class="u-mono">{{ deniedPath }}</code> 所需的权限。
          如需开通，请联系本单位组织部门管理员。
        </p>
      </div>
    </section>

    <div class="sys__grid">
      <!-- ---------------------------- 连通性 ---------------------------- -->
      <section class="u-card">
        <header class="u-panel-head">
          <h2 class="card__title">服务连通性</h2>
          <span class="u-meta">开发代理 /api → localhost:8000/api/v1</span>
        </header>

        <ul class="probes">
          <li v-for="(r, i) in results" :key="i" class="probe">
            <div class="probe__head">
              <span class="u-label">{{ r.label }}</span>
              <span v-if="r.loading" class="badge">检测中</span>
              <span v-else-if="r.error" class="badge badge--bad">
                <span class="dot"></span>
                不可用
              </span>
              <span v-else class="badge badge--ok">
                <span class="dot"></span>
                正常
              </span>
            </div>

            <LoadingBlock v-if="r.loading" variant="list" :rows="1" />

            <div v-else-if="r.error" class="probe__err">
              <ErrorState :error="r.error">
                <button class="btn btn--ghost" type="button" @click="runAll">重试</button>
              </ErrorState>
            </div>

            <dl v-else-if="r.data" class="facts">
              <div class="facts__row">
                <dt>状态</dt>
                <dd>{{ r.data.status }}</dd>
              </div>
              <div class="facts__row">
                <dt>服务名</dt>
                <dd>{{ r.data.service }}</dd>
              </div>
              <div class="facts__row">
                <dt>版本</dt>
                <dd class="u-mono">{{ r.data.version }}</dd>
              </div>
              <div class="facts__row">
                <dt>运行环境</dt>
                <dd class="u-mono">{{ r.data.environment }}</dd>
              </div>
            </dl>
          </li>
        </ul>
      </section>

      <!-- ---------------------------- 账号 ------------------------------ -->
      <section class="u-card">
        <header class="u-panel-head">
          <h2 class="card__title">当前账号</h2>
        </header>

        <template v-if="user">
          <dl class="facts">
            <div class="facts__row">
              <dt>姓名</dt>
              <dd>{{ user.name }}</dd>
            </div>
            <div class="facts__row">
              <dt>用户名</dt>
              <dd class="u-mono">{{ user.username }}</dd>
            </div>
            <div class="facts__row">
              <dt>角色</dt>
              <dd>{{ roleLabel }}</dd>
            </div>
            <div class="facts__row">
              <dt>所属组织</dt>
              <dd class="u-mono">{{ user.org_unit_id ?? '未分配' }}</dd>
            </div>
            <div class="facts__row">
              <dt>租户</dt>
              <dd class="u-mono">{{ user.tenant_id }}</dd>
            </div>
            <div class="facts__row">
              <dt>邮箱</dt>
              <dd>{{ user.email ?? '未填写' }}</dd>
            </div>
            <div class="facts__row">
              <dt>手机</dt>
              <dd>{{ user.phone ?? '未填写' }}</dd>
            </div>
          </dl>

          <div class="perm">
            <h3 class="perm__title">
              权限码
              <span class="u-num perm__n">{{ session.state.permissions.length }}</span>
            </h3>
            <p class="perm__hint">
              侧栏菜单按权限码显隐。此处为空或缺少某项时，对应入口不会出现。
            </p>
            <ul v-if="session.state.permissions.length" class="perm__list">
              <li v-for="p in session.state.permissions" :key="p" class="badge badge--accent u-mono">
                {{ p }}
              </li>
            </ul>
            <p v-else class="perm__none">未获取到任何权限码</p>
          </div>
        </template>

        <div v-else class="card__pad">
          <p class="u-muted">未登录。</p>
        </div>
      </section>

      <!-- ---------------------------- 数据分级 -------------------------- -->
      <section class="u-card">
        <header class="u-panel-head">
          <h2 class="card__title">数据分级与模型走向</h2>
        </header>
        <p class="card__lead">
          提问前选择的数据分级决定内容会被送往哪一类模型。公开级可走外部模型，
          其余级别一律由本地模型处理，该限制在服务端强制校验，前端无法绕过。
        </p>
        <ul class="levels">
          <li v-for="lv in DATA_LEVELS" :key="lv" class="levels__row">
            <span class="badge" :class="lv === 'public' ? 'badge--ok' : 'badge--warn'">
              {{ DATA_LEVEL_LABELS[lv] }}
            </span>
            <span class="levels__route">{{ DATA_LEVEL_ROUTE[lv] }}</span>
            <code class="u-mono levels__code">{{ lv }}</code>
          </li>
        </ul>
      </section>
    </div>

    <!-- ---------------------------- 接口矩阵 ------------------------------ -->
    <section class="u-card">
      <header class="u-panel-head">
        <h2 class="card__title">接口接入状态</h2>
        <span class="badge badge--warn">未提供 {{ missingCount }} 项</span>
      </header>

      <p class="card__lead">
        下表如实反映后端当前的接口能力。标注为「未提供」的接口，其对应界面使用示例数据，
        并以徽标提示，不作为真实业务依据。
      </p>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">能力</th>
              <th scope="col">接口</th>
              <th scope="col">方法</th>
              <th scope="col">用途</th>
              <th scope="col">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in API_SURFACE" :key="s.label">
              <td class="table__primary">{{ s.label }}</td>
              <td class="u-mono surface__path">{{ s.path }}</td>
              <td><span class="badge u-mono">{{ s.method }}</span></td>
              <td class="surface__use">{{ s.purpose }}</td>
              <td>
                <span class="badge" :class="s.available ? 'badge--ok' : 'badge--warn'">
                  <span class="dot"></span>
                  {{ s.available ? '已接入' : '未提供' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sys {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6) var(--space-6) var(--space-10);
  width: 100%;
}

.denied {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--warn-wash);
  border: 1px solid var(--warn-edge);
  border-left-width: 3px;
  border-radius: var(--radius-sm);
  color: var(--warn-ink);
}

.denied__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.denied__text {
  margin-top: 2px;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

.denied code {
  color: var(--ink);
}

.sys__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--space-5);
  align-items: start;
}

.card__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.card__lead {
  padding: var(--space-4) var(--space-4) 0;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.card__pad {
  padding: var(--space-4);
}

/* ---------------------------- 探测 -------------------------------- */
.probes {
  display: flex;
  flex-direction: column;
}

.probe {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: var(--border);
}

.probe:last-child {
  border-bottom: 0;
}

.probe__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.probe__err :deep(.state) {
  padding: var(--space-4) 0;
  align-items: flex-start;
  text-align: left;
}

/* ---------------------------- 事实表 ------------------------------ */
.facts {
  display: flex;
  flex-direction: column;
  border: var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.facts__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-bottom: var(--border);
  background: var(--paper-raised);
}

.facts__row:last-child {
  border-bottom: 0;
}

.facts__row dt {
  font-size: var(--text-xs);
  color: var(--ink-faint);
  white-space: nowrap;
}

.facts__row dd {
  font-size: var(--text-sm);
  color: var(--ink-soft);
  text-align: right;
  word-break: break-word;
}

/* ---------------------------- 权限 -------------------------------- */
.perm {
  padding: var(--space-4);
}

.perm__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
}

.perm__n {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  font-size: var(--text-2xs);
  color: var(--ink-muted);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-xs);
}

.perm__hint {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.perm__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.perm__none {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--ink-faint);
}

/* ---------------------------- 分级 -------------------------------- */
.levels {
  display: flex;
  flex-direction: column;
  padding: var(--space-2) var(--space-4) var(--space-4);
}

.levels__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: var(--border);
}

.levels__row:last-child {
  border-bottom: 0;
}

.levels__route {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

.levels__code {
  font-size: var(--text-xs);
  color: var(--ink-faint);
}

/* ---------------------------- 矩阵 -------------------------------- */
.surface__path {
  font-size: var(--text-xs);
  color: var(--ink-muted);
  white-space: nowrap;
}

.surface__use {
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}

@media (max-width: 720px) {
  .sys {
    padding: var(--space-4) var(--space-4) var(--space-10);
  }
}
</style>
