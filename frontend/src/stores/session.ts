import { computed, reactive, readonly } from 'vue'

import * as authApi from '@/api/auth'
import { tokenStore } from '@/api/http'
import type { PermissionCode, UserInfo } from '@/api/types'

/**
 * 会话状态。
 *
 * 刻意不引入 Pinia：本项目需要跨页面共享的状态只有"当前用户 + 权限码"，
 * 一个模块级 reactive 对象足够，少一层依赖就少一层出问题的可能。
 *
 * 权限仅用于**界面显隐**。服务端始终独立校验权限，前端隐藏按钮
 * 不构成任何安全保证，反之也不能因前端未隐藏就认定有权限。
 */

interface SessionState {
  user: UserInfo | null
  permissions: PermissionCode[]
  loading: boolean
  /** 是否已尝试过恢复会话，避免路由守卫重复请求 */
  resolved: boolean
}

const state = reactive<SessionState>({
  user: null,
  permissions: [],
  loading: false,
  resolved: false,
})

const isAuthenticated = computed(() => state.user !== null)

function can(code: PermissionCode): boolean {
  return state.permissions.includes(code)
}

/** 持有任一权限即可 */
function canAny(codes: PermissionCode[]): boolean {
  return codes.some((c) => state.permissions.includes(c))
}

async function signIn(username: string, password: string): Promise<UserInfo> {
  state.loading = true
  try {
    const tokens = await authApi.login({ username, password })
    tokenStore.set(tokens.access_token, tokens.refresh_token)
    const [user, permissions] = await Promise.all([
      authApi.getMe(),
      authApi.getPermissionCodes(),
    ])
    state.user = user
    state.permissions = permissions
    state.resolved = true
    return user
  } finally {
    state.loading = false
  }
}

/** 应用启动时调用：有令牌就换回用户信息，失败则静默登出 */
async function restore(): Promise<void> {
  if (state.resolved) return

  if (!tokenStore.get()) {
    state.resolved = true
    return
  }

  state.loading = true
  try {
    const [user, permissions] = await Promise.all([
      authApi.getMe(),
      authApi.getPermissionCodes(),
    ])
    state.user = user
    state.permissions = permissions
  } catch {
    // 令牌过期或被吊销：清干净，由路由守卫送回登录页
    tokenStore.clear()
    state.user = null
    state.permissions = []
  } finally {
    state.loading = false
    state.resolved = true
  }
}

async function signOut(): Promise<void> {
  try {
    if (tokenStore.get()) await authApi.logout()
  } catch {
    // 后端登出目前是空实现（Redis 黑名单待办），失败不影响本地登出
  } finally {
    tokenStore.clear()
    state.user = null
    state.permissions = []
    state.resolved = true
  }
}

export const session = {
  state: readonly(state) as Readonly<SessionState>,
  isAuthenticated,
  can,
  canAny,
  signIn,
  signOut,
  restore,
}
