import request from '../utils/request'

// 登录接口
export interface LoginParams {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  name: string
  role: string
  tenant_id: string
  email?: string
  phone?: string
}

// 登录
export const login = (data: LoginParams) => {
  return request.post<any, LoginResponse>('/auth/login', data)
}

// 获取用户信息
export const getUserInfo = () => {
  return request.get<any, UserInfo>('/user/info')
}

// 获取权限码
export const getPermissions = () => {
  return request.get<any, string[]>('/auth/codes')
}

// 刷新令牌
export const refreshToken = () => {
  const token = localStorage.getItem('refresh_token')
  if (!token) return Promise.reject(new Error('请先登录'))
  return request.post<any, LoginResponse>('/auth/refresh', null, {
    headers: { Authorization: `Bearer ${token}` }
  })
}

// 退出登录
export const logout = () => {
  return request.post('/auth/logout')
}

// 健康检查
export const healthCheck = () => {
  return request.get('/health')
}
