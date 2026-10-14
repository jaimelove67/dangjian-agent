import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { isSessionExpired } from '@/api/http'
import { isSelfServiceRole, MEMBER_FUNCTION_PERMISSIONS, PERM, type PermissionCode, type UserRole } from '@/api/types'
import AppShell from '@/layouts/AppShell.vue'
import { session } from '@/stores/session'

/**
 * 路由表。
 *
 * meta 约定：
 *   - title    页面标题（写入文档 title 与顶栏面包屑）
 *   - group    侧栏分组名
 *   - perm     需要的权限码
 *   - role     限定角色；与权限码同时配置时均须满足
 *   - public   免登录页面
 */

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    group?: string
    perm?: PermissionCode
    role?: UserRole
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: AppShell,
    children: [
      {
        path: 'my-archive',
        name: 'my-archive',
        component: () => import('@/views/MyArchiveView.vue'),
        meta: { title: '本人档案', group: '个人', perm: PERM.SELF_QUERY },
      },
      {
        path: 'my-materials',
        name: 'my-materials',
        component: () => import('@/views/MyMaterialsView.vue'),
        meta: { title: '个人材料', group: '个人', perm: PERM.MATERIAL_SUBMIT },
      },
      {
        path: '',
        redirect: '/ask',
      },
      {
        path: 'ask',
        name: 'ask',
        component: () => import('@/views/AskView.vue'),
        meta: { title: '制度问答', group: '问答', perm: PERM.QA_ASK },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgeView.vue'),
        meta: { title: '知识库', group: '资料', perm: PERM.KNOWLEDGE_QUERY },
      },
      {
        path: 'assessment',
        name: 'assessment',
        component: () => import('@/views/AssessmentView.vue'),
        meta: { title: '年度考核', group: '业务', perm: PERM.ASSESSMENT_QUERY },
      },
      {
        path: 'members',
        name: 'members',
        component: () => import('@/views/MembersView.vue'),
        meta: { title: '党员发展', group: '业务', perm: PERM.MEMBER_QUERY },
      },
      {
        path: 'study',
        name: 'study',
        component: () => import('@/views/StudyView.vue'),
        meta: { title: '中心组学习', group: '业务', perm: PERM.STUDY_QUERY },
      },
      {
        path: 'meeting',
        name: 'meeting',
        component: () => import('@/views/MeetingView.vue'),
        meta: { title: '组织生活', group: '业务', perm: PERM.MEETING_QUERY },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { title: '创建账号', group: '系统', role: 'system_admin' },
      },
      {
        path: 'system',
        name: 'system',
        component: () => import('@/views/SystemView.vue'),
        meta: { title: '系统状态', group: '系统', role: 'system_admin' },
      },
      {
        path: 'governance',
        name: 'governance',
        component: () => import('@/views/GovernanceView.vue'),
        meta: { title: '管理与审核', group: '系统', perm: PERM.REVIEW_MANAGE },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { title: '访问受限' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在', public: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved ?? { top: 0 }
  },
})
window.addEventListener('party:session-cleared', () => {
  if (router.currentRoute.value.name !== 'login') {
    void router.replace({
      name: 'login',
      query: {
        next: router.currentRoute.value.fullPath,
        ...(isSessionExpired() ? { reason: 'expired' } : {}),
      },
    })
  }
})

router.beforeEach(async (to) => {
  if (!session.state.resolved) {
    await session.restore()
  }

  if (to.meta.public) {
    // 已登录用户访问登录页时直接送回主界面，避免重复登录
    if (to.name === 'login' && session.isAuthenticated.value) {
      return { path: '/ask' }
    }
    return true
  }

  if (!session.isAuthenticated.value) {
    return {
      name: 'login',
      query: { next: to.fullPath, ...(isSessionExpired() ? { reason: 'expired' } : {}) },
    }
  }

  if (
    (to.meta.perm && !session.can(to.meta.perm)) ||
    (isSelfServiceRole(session.state.user?.role) && to.meta.perm && !MEMBER_FUNCTION_PERMISSIONS.has(to.meta.perm)) ||
    (to.meta.role && session.state.user?.role !== to.meta.role)
  ) {
    return { name: 'forbidden' }
  }

  return true
})

router.afterEach((to) => {
  const title = to.meta.title
  document.title = title ? `${title} · 党建工作智能体` : '党建工作智能体'
})
