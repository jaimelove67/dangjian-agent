import { ApiError, http, tokenStore } from './http'
import type { LoginRequest, PermissionCode, TokenResponse, UserInfo } from './types'

/** app/api/v1/auth.py */

export function login(payload: LoginRequest): Promise<TokenResponse> {
  // 登录失败时后端返回统一的模糊化提示，用于防止用户名枚举，前端原样展示即可
  return http.post('/auth/login', payload)
}

export function getMe(): Promise<UserInfo> {
  return http.get('/auth/me')
}

export async function refreshToken(refresh?: string): Promise<TokenResponse> {
  // 后端从 Authorization: Bearer <refresh_token> 读取，不放在 body 里
  const token = refresh ?? tokenStore.getRefresh()
  if (!token) throw new ApiError('缺少刷新令牌，请重新登录', 40101, '', 401)
  const tokens: TokenResponse = await http.post('/auth/refresh', null, {
    headers: { Authorization: `Bearer ${token}` },
  })
  tokenStore.set(tokens.access_token, tokens.refresh_token)
  return tokens
}

export function logout(): Promise<{ message: string }> {
  return http.post('/auth/logout')
}

/** app/api/v1/auth.py::GET /auth/codes —— 返回权限码字符串数组 */
export function getPermissionCodes(): Promise<PermissionCode[]> {
  return http.get('/auth/codes')
}
