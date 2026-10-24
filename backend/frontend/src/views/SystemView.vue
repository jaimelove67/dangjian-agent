<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { checkHealth, checkReady } from '@/api/qa'
import { API_SURFACE } from '@/api/surface'
import { ROLE_LABELS, DATA_LEVEL_LABELS, DATA_LEVEL_ROUTE } from '@/api/types'
import type { HealthResponse, ReadyResponse, DataLevel } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

/**
 * 系统状态。
 *
 * 三重职责：
 *   1. 后端连通性与就绪状态（管理员接口 /admin/health 与 /admin/health/ready）
 *   2. 当前账号的身份与权限码一览，便于自查"为什么看不到某个菜单"
 *   3. **接口能力矩阵**：把后端"已具备 / 未提供"的接口如实列出来。
 *      仅平台管理员可查看，用于维护与排查问题。
 */

interface Probe {
  label: string
  run: () => Promise<HealthResponse | ReadyResponse>
}

const probes: Probe[] = [
  { label: '基础健康检查', run: checkHealth },
  { label: '就绪检查', run: checkReady },
]

interface ProbeResult {
  label: string
  loading: boolean
  data: HealthResponse | ReadyResponse | null
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
const CHECK_LABELS: Record<string, string> = {
  database: '数据库',
  redis: '会话存储',
  schema: '业务结构',
  models: '模型配置',
  model_warm: '模型连通性（15 分钟内调用）',
}
const CHECK_STATUS: Record<string, string> = {
  healthy: '正常',
  unhealthy: '连接失败',
  migration_required: '需要迁移',
  configuration_required: '尚未配置',
  unverified: '未验证（不影响就绪）',
  unknown: '未确认',
}
/** 开发代理目标：以实际启动参数为准，避免界面写死一个可能已被占用的端口 */
const proxyTarget = `${import.meta.env.VITE_API_TARGET ?? 'http://localhost:8000'}/api/v1`
</script>

<template>
  <div class="sys">
    <PageHeader
      title="系统状态"
      description="查看后端连通情况、就绪状态与当前账号权限。"
    >
      <template #actions>
        <button class="btn btn--ghost" type="button" @click="runAll">
          <AppIcon name="pulse" :size="14" />
          <span>重新检测</span>
        </button>
      </template>
    </PageHeader>

    <div class="sys__grid">
      <!-- ---------------------------- 连通性 ---------------------------- -->
      <section class="u-card">
        <header class="u-panel-head">
          <h2 class="card__title">服务连通性</h2>
          <span class="u-meta">开发代理 /api → {{ proxyTarget }}</span>
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
              <span v-else-if="r.data?.status === 'not_ready'" class="badge badge--warn">尚未就绪</span>
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
              <div v-if="'service' in r.data" class="facts__row">
                <dt>服务名</dt>
                <dd>{{ r.data.service }}</dd>
              </div>
              <div v-if="'version' in r.data" class="facts__row">
                <dt>版本</dt>
                <dd class="u-mono">{{ r.data.version }}</dd>
              </div>
              <div v-if="'environment' in r.data" class="facts__row">
                <dt>运行环境</dt>
                <dd class="u-mono">{{ r.data.environment }}</dd>
              </div>
              <template v-if="'checks' in r.data">
                <div v-for="(status, key) in r.data.checks" :key="key" class="facts__row">
                  <dt>{{ CHECK_LABELS[key] ?? key }}</dt>
                  <dd>{{ CHECK_STATUS[status] ?? status }}</dd>
                </div>
                <div class="facts__row">
                  <dt>模型配置</dt>
                  <dd>聊天：{{ r.data.model_capabilities.llm }}；向量：{{ r.data.model_capabilities.embedding }}；重排：{{ r.data.model_capabilities.reranker }}</dd>
                </div>
              </template>
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
          角色权限决定可访问的资料范围。服务端按问题和所用文档分级：公开与获准的内部内容
          可使用云端模型，敏感与涉密内容禁止调用云端模型。所选分级只能提高限制。
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
        <h2 class="card__title">接口接入诊断（开发与验收用）</h2>
        <span class="badge" :class="missingCount ? 'badge--warn' : 'badge--ok'">未提供 {{ missingCount }} 项</span>
      </header>

      <p class="card__lead">
        这是给维护与验收使用的后端能力清单，日常业务判断不需要看。展开后可按接口核对
        各能力是否已接入；标注为「未提供」的接口，其对应界面使用示例数据，不作为真实业务依据。
      </p>

      <details class="surface">
        <summary>展开接口能力清单（{{ API_SURFACE.length }} 项）</summary>
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
      </details>
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
.surface {
  padding: var(--space-4);
}

.surface summary {
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--ink-soft);
}

.surface summary:hover {
  color: var(--ink);
}

.surface .table-wrap {
  margin-top: var(--space-4);
}

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
