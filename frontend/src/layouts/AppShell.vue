<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { PERM, ROLE_LABELS, type PermissionCode } from '@/api/types'
import AppIcon, { type IconName } from '@/components/AppIcon.vue'
import { session } from '@/stores/session'

interface NavItem {
  to: string
  label: string
  icon: IconName
  perm?: PermissionCode
}

interface NavGroup {
  label: string
  items: NavItem[]
}

/**
 * 导航结构。分组而非平铺：本产品的功能边界清晰（问答 / 资料 / 业务 / 系统），
 * 分组能让侧栏在只显示 3-5 项时依然有层次，而不是一串等权重的链接。
 */
const NAV: NavGroup[] = [
  {
    label: '问答',
    items: [{ to: '/ask', label: '制度问答', icon: 'ask', perm: PERM.QA_ASK }],
  },
  {
    label: '资料',
    items: [
      { to: '/knowledge', label: '知识库', icon: 'book', perm: PERM.KNOWLEDGE_MANAGE },
    ],
  },
  {
    label: '业务',
    items: [{ to: '/members', label: '党员发展', icon: 'people', perm: PERM.MEMBER_QUERY }],
  },
  {
    label: '系统',
    items: [{ to: '/system', label: '系统状态', icon: 'pulse' }],
  },
]

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const signOutError = ref('')

const visibleGroups = computed(() =>
  NAV.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.perm || session.can(item.perm)),
  })).filter((group) => group.items.length > 0),
)

const currentTitle = computed(() => route.meta.title ?? '')
const user = computed(() => session.state.user)
const roleLabel = computed(() => (user.value ? ROLE_LABELS[user.value.role] : ''))
const initial = computed(() => user.value?.name?.slice(0, 1) ?? '')

onMounted(() => {
  // 直接进入子页面时也要保证会话已恢复（守卫已处理，这里兜底刷新后的场景）
  void session.restore()
})

function onNavigate(): void {
  menuOpen.value = false
}

async function onSignOut(): Promise<void> {
  signOutError.value = ''
  try {
    await session.signOut()
    void router.push({ name: 'login' })
  } catch (error) {
    signOutError.value = error instanceof Error ? error.message : '退出失败，请重试'
  }
}
</script>

<template>
  <div class="shell">
    <p v-if="signOutError" role="alert">{{ signOutError }}</p>
    <!-- 顶栏：单行，56px。左侧是产品标识与分组名，右侧是身份与操作。 -->
    <header class="topbar">
      <button
        class="topbar__menu"
        type="button"
        :aria-expanded="menuOpen"
        aria-controls="app-rail"
        @click="menuOpen = !menuOpen"
      >
        <AppIcon name="layout" :size="16" />
        <span class="u-sr">切换导航</span>
      </button>

      <RouterLink to="/ask" class="brand" @click="onNavigate">
        <span class="brand__mark" aria-hidden="true">党</span>
        <span class="brand__text">
          <span class="brand__name">党建工作智能体</span>
          <span class="brand__sub">制度问答与依据溯源</span>
        </span>
      </RouterLink>

      <span class="topbar__divider" aria-hidden="true"></span>

      <span class="topbar__crumb">{{ currentTitle }}</span>

      <div class="topbar__spacer"></div>

      <div v-if="user" class="ident">
        <span class="ident__avatar" aria-hidden="true">{{ initial }}</span>
        <span class="ident__text">
          <span class="ident__name">{{ user.name }}</span>
          <span class="ident__role">{{ roleLabel }}</span>
        </span>
        <button class="btn btn--quiet topbar__logout" type="button" @click="onSignOut">
          <AppIcon name="logout" :size="15" />
          <span>退出</span>
        </button>
      </div>
    </header>

    <div class="body">
      <!-- 侧栏：分组导航。移动端折叠为抽屉，不做底部标签栏（项数太少） -->
      <nav
        id="app-rail"
        class="rail"
        :class="{ 'is-open': menuOpen }"
        aria-label="主导航"
      >
        <div v-for="group in visibleGroups" :key="group.label" class="rail__group">
          <span class="rail__group-label">{{ group.label }}</span>
          <ul class="rail__list">
            <li v-for="item in group.items" :key="item.to">
              <RouterLink :to="item.to" class="rail__link" @click="onNavigate">
                <AppIcon :name="item.icon" :size="16" />
                <span>{{ item.label }}</span>
              </RouterLink>
            </li>
          </ul>
        </div>

        <!-- 合规边界的常驻声明。放在侧栏底部而不是弹窗里：
             这条约束是本产品的立身之本，应当随手可见。 -->
        <div class="rail__foot">
          <div class="rail__notice">
            <AppIcon name="shield" :size="15" />
            <p>
              本系统仅提供辅助分析与依据检索。组织认定、选拔结论与阶段流转均由人工依据规定作出。
            </p>
          </div>
        </div>
      </nav>

      <button
        v-if="menuOpen"
        class="scrim"
        type="button"
        aria-label="关闭导航"
        @click="menuOpen = false"
      ></button>

      <main class="main">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
}

/* ------------------------------- 顶栏 -------------------------------- */
.topbar {
  position: sticky;
  top: 0;
  z-index: var(--z-nav);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--nav-h);
  padding: 0 var(--space-4);
  background: color-mix(in srgb, var(--paper) 88%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: var(--border);
}

.topbar__menu {
  display: none;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
}

.topbar__menu:hover {
  background: var(--paper-dim);
  color: var(--ink);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-1);
  border-radius: var(--radius-sm);
}

.brand__mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  font-family: var(--font-serif);
  font-size: var(--text-sm);
  font-weight: 600;
  color: #fff;
  background: var(--accent);
  border-radius: var(--radius-sm);
}

.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.brand__name {
  font-family: var(--font-serif);
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: var(--tracking-tight);
  color: var(--ink);
}

.brand__sub {
  font-size: var(--text-2xs);
  color: var(--ink-faint);
  letter-spacing: 0.02em;
}

.topbar__divider {
  width: 1px;
  height: 18px;
  background: var(--rule);
}

.topbar__crumb {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink-soft);
}

.topbar__spacer {
  flex: 1;
}

.ident {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.ident__avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--accent-deep);
  background: var(--accent-wash);
  border: 1px solid var(--accent-edge);
  border-radius: var(--radius-full);
}

.ident__text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.ident__name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.ident__role {
  font-size: var(--text-2xs);
  color: var(--ink-faint);
}

/* ------------------------------- 主体 -------------------------------- */
.body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.rail {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  width: var(--rail-w);
  flex: none;
  padding: var(--space-5) var(--space-3) var(--space-4);
  border-right: var(--border);
  background: var(--paper);
}

.rail__group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.rail__group-label {
  padding-left: var(--space-2);
  font-size: var(--text-2xs);
  font-weight: 600;
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
  color: var(--ink-faint);
}

.rail__list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rail__link {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: 34px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
  font-size: var(--text-base);
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.rail__link:hover {
  background: var(--paper-dim);
  color: var(--ink);
}

/* 选中态：左侧 2px 实心条 + 浅底，不靠改变字重（避免布局抖动） */
.rail__link.router-link-active {
  background: var(--accent-wash);
  color: var(--accent-deep);
  font-weight: 600;
}

.rail__link.router-link-active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 18px;
  background: var(--accent);
  border-radius: var(--radius-full);
}

.rail__foot {
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: var(--border);
}

.rail__notice {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
}

.rail__notice p {
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.scrim {
  display: none;
}

/* ------------------------------ 响应式 ------------------------------- */
@media (max-width: 900px) {
  .topbar__menu {
    display: inline-flex;
  }

  .brand__sub,
  .ident__text {
    display: none;
  }

  .topbar__divider {
    display: none;
  }

  .rail {
    position: fixed;
    top: var(--nav-h);
    bottom: 0;
    left: 0;
    z-index: var(--z-nav);
    transform: translateX(-100%);
    transition: transform var(--dur) var(--ease);
    box-shadow: var(--shadow-pop);
    overflow-y: auto;
  }

  .rail.is-open {
    transform: translateX(0);
  }

  .scrim {
    display: block;
    position: fixed;
    inset: var(--nav-h) 0 0;
    z-index: calc(var(--z-nav) - 1);
    background: rgb(28 27 25 / 0.24);
    border: 0;
  }
}

@media (max-width: 560px) {
  .topbar__crumb {
    display: none;
  }

  .topbar__logout span {
    display: none;
  }
}
</style>
