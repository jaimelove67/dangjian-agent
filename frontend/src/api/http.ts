import axios, { type AxiosError, type AxiosInstance, type AxiosResponse } from 'axios'

import { ErrorCode, type ApiEnvelope } from './types'

/**
 * 统一的 HTTP 客户端。
 *
 * 与后端契约（app/main.py）严格对齐：
 *   - 所有路由挂在 /api/v1 下，开发期由 vite 把 /api 重写为 /api/v1
 *   - 响应体恒为 { code, message, data, trace_id }
 *   - code === 0 表示成功，此时**只把 data 交给调用方**
 *   - 非 0 时抛出 ApiError，携带 code / trace_id，便于界面显示可粘贴的
 *     request id（本项目排障要靠 trace_id，不能只提示"请求失败"）
 */

const TOKEN_KEY = 'party.access_token'
const REFRESH_KEY = 'party.refresh_token'

export class ApiError extends Error {
  readonly code: number
  readonly traceId: string
  readonly httpStatus?: number

  constructor(message: string, code: number, traceId = '', httpStatus?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.httpStatus = httpStatus
  }

  /** 是否为"需要重新登录"类错误 */
  get isAuthError(): boolean {
    return this.code === ErrorCode.UNAUTHORIZED || this.httpStatus === 401
  }

  /** 是否为租户隔离拦截（40302）。界面上要单独解释，不能笼统说"无权限" */
  get isTenantIsolation(): boolean {
    return this.code === ErrorCode.TENANT_ISOLATION
  }
}

export const tokenStore = {
  get(): string | null {
    return localStorage.getItem(TOKEN_KEY)
  },
  getRefresh(): string | null {
    return localStorage.getItem(REFRESH_KEY)
  },
  set(access: string, refresh?: string): void {
    localStorage.setItem(TOKEN_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear(): void {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

/** 后端异常处理器不总是返回标准包裹体（如 422 校验失败），做一次收敛 */
function normalizeError(err: AxiosError<Partial<ApiEnvelope<unknown>>>): ApiError {
  const status = err.response?.status
  const body = err.response?.data
  const traceId = body?.trace_id ?? err.response?.headers?.['x-request-id'] ?? ''

  if (body && typeof body.code === 'number') {
    return new ApiError(body.message || '请求失败', body.code, String(traceId), status)
  }

  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
    return new ApiError('请求超时，请检查网络或后端服务是否在线', -1, '', status)
  }

  if (!err.response) {
    return new ApiError('无法连接到后端服务，请确认服务已在 8000 端口启动', -1, '', status)
  }

  return new ApiError(`请求失败（HTTP ${status ?? '未知'}）`, -1, String(traceId), status)
}

export const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60000, // 问答涉及检索 + 重排 + 大模型生成，10s 不够
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res: AxiosResponse<ApiEnvelope<unknown>>) => {
    const body = res.data

    // 标准包裹体：成功时只把 data 交给调用方（调用方拿到的是载荷本身，
    // 不是 AxiosResponse，也不是包裹体）
    if (body && typeof body.code === 'number') {
      if (body.code === ErrorCode.SUCCESS) {
        return body.data as never
      }
      throw new ApiError(body.message || '业务处理失败', body.code, body.trace_id)
    }

    // 非包裹体（如文件流、裸 JSON）：透传载荷
    return body as never
  },
  (err: AxiosError<Partial<ApiEnvelope<unknown>>>) => {
    const apiErr = normalizeError(err)

    // 令牌失效：清空本地凭证，交给路由守卫跳登录页，不在此处自行跳转
    if (apiErr.isAuthError) {
      tokenStore.clear()
    }

    return Promise.reject(apiErr)
  },
)
