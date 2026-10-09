import { http } from './http'
import type { LoginRequest, PermissionCode, TokenResponse, UserInfo } from './types'

/** app/api/v1/auth.py */

export function login(payload: LoginRequest): Promise<TokenResponse> {
  // 登录失败时后端返回统一的模糊化提示，用于防止用户名枚举，前端原样展示即可
  return http.post('/auth/login', payload)
}

export function getMe(): Promise<UserInfo> {
  return http.get('/auth/me')
}

export function refreshToken(refresh?: string): Promise<TokenResponse> {
  // 后端从 Authorization: Bearer <refresh_token> 读取，不放在 body 里
  return http.post('/auth/refresh', null, {
    headers: refresh ? { Authorization: `Bearer ${refresh}` } : undefined,
  })
}

export function logout(): Promise<null> {
  return http.post('/auth/logout')
}

/** app/api/v1/auth.py::GET /auth/codes —— 返回权限码字符串数组 */
export function getPermissionCodes(): Promise<PermissionCode[]> {
  return http.get('/auth/codes')
}
