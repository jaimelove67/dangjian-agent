import axios, { type AxiosError, type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { ErrorCode, type ApiEnvelope } from './types'
import type { TokenResponse } from './types'

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
    window.dispatchEvent(new Event('party:session-cleared'))
  },
}

/**
 * 会话被动失效标记。
 *
 * 只有"令牌过期/被吊销"这类**非用户主动**的登出才置位，界面据此在登录页
 * 说明"登录状态已失效"，避免用户莫名其妙被踢回登录页而不知道原因。
 * 用户主动点"退出"时由 session.signOut() 清掉，不会误报。
 */
let sessionExpired = false

export function markSessionExpired(): void {
  sessionExpired = true
}

export function isSessionExpired(): boolean {
  return sessionExpired
}

export function clearSessionExpiry(): void {
  sessionExpired = false
}

/** 后端异常处理器不总是返回标准包裹体（如 422 校验失败），做一次收敛 */
function normalizeError(err: AxiosError<Partial<ApiEnvelope<unknown>>>): ApiError {
  const status = err.response?.status
  const body = err.response?.data
  const traceId = body?.trace_id ?? err.response?.headers?.['x-request-id'] ?? ''

  if (body && typeof body.code === 'number') {
    return new ApiError(
      withRetryHint(body.message || '请求失败', err),
      body.code,
      String(traceId),
      status,
    )
  }

  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
    return new ApiError('请求超时，请检查网络或后端服务是否在线', -1, '', status)
  }

  if (!err.response) {
    return new ApiError('无法连接到后端服务，请确认后端已启动', -1, '', status)
  }

  return new ApiError(`请求失败（HTTP ${status ?? '未知'}）`, -1, String(traceId), status)
}

/**
 * 文件下载（`responseType: 'blob'`）失败时，响应体对 axios 是 Blob 而不是包裹体。
 *
 * 不还原的话，后端为导出准备的"超限请分批导出""越权"这类**可执行提示**会退化成
 * "请求失败（HTTP 413）"，用户既不知道原因也不知道怎么办。这里按内容类型解回 JSON。
 */
async function readBlobError(
  err: AxiosError<unknown>,
): Promise<AxiosError<Partial<ApiEnvelope<unknown>>>> {
  const data = err.response?.data
  const isBlob = typeof Blob !== 'undefined' && data instanceof Blob
  if (isBlob && (!data.type || data.type.includes('json'))) {
    try {
      const text = await data.text()
      if (err.response) err.response.data = JSON.parse(text)
    } catch {
      // 解析失败就保留原始错误体，交给 normalizeError 回落到通用文案
    }
  }
  return err as AxiosError<Partial<ApiEnvelope<unknown>>>
}

/**
 * 限流响应带上"还要等多久"。
 *
 * 后端在 429 时返回 Retry-After 秒数，用户看得到这个数字才不会反复
 * 无效重试；拿不到响应头时至少给出明确的时间范围。
 */
function withRetryHint(
  message: string,
  err: AxiosError<Partial<ApiEnvelope<unknown>>>,
): string {
  if (err.response?.status !== 429) return message
  const raw = err.response.headers?.['retry-after']
  const seconds = Number.parseInt(String(raw ?? ''), 10)
  const wait = Number.isFinite(seconds) && seconds > 0 ? `约 ${seconds} 秒` : '约 1 分钟'
  if (message.includes('秒') || message.includes('分钟')) return message
  return `${message}（${wait}后可重试）`
}

export const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60000, // 问答涉及检索 + 重排 + 大模型生成，10s 不够
  headers: { 'Content-Type': 'application/json' },
})

type SessionRequest = InternalAxiosRequestConfig & { sessionToken?: string; retried?: boolean }

http.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token && !config.headers.has('Authorization')) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (token && config.headers.Authorization === `Bearer ${token}`) {
    (config as SessionRequest).sessionToken = token
  }
  return config
})

let refreshPending: Promise<TokenResponse> | null = null

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
  async (err: AxiosError<Partial<ApiEnvelope<unknown>>>) => {
    const apiErr = normalizeError(await readBlobError(err))
    const original = err.config as SessionRequest | undefined
    const authRequest = original?.url?.startsWith('/auth/') &&
      !['/auth/me', '/auth/codes'].includes(original.url)
    const currentAccess = tokenStore.get()
    const ownSession = !!currentAccess && !!original?.sessionToken && original.headers.Authorization === `Bearer ${original.sessionToken}`

    if (apiErr.isAuthError && original && !authRequest && ownSession && !original.retried && tokenStore.getRefresh()) {
      original.retried = true
      // 另一个并发请求已经完成刷新时，直接用新令牌重试。
      if (original.sessionToken !== currentAccess) {
        original.headers.Authorization = `Bearer ${currentAccess}`
        return http.request(original)
      }
      try {
        if (!refreshPending) {
          refreshPending = http.post<never, TokenResponse>('/auth/refresh', null, {
            headers: { Authorization: `Bearer ${tokenStore.getRefresh()}` },
          }).then((tokens) => {
            tokenStore.set(tokens.access_token, tokens.refresh_token)
            return tokens
          }).finally(() => { refreshPending = null })
        }
        const tokens = await refreshPending
        original.headers.Authorization = `Bearer ${tokens.access_token}`
        return http.request(original)
      } catch (refreshError) {
        if (refreshError instanceof ApiError && refreshError.isAuthError) {
          markSessionExpired()
          tokenStore.clear()
        }
        return Promise.reject(refreshError)
      }
    }

    // 令牌失效：清空本地凭证，交给路由守卫跳登录页，不在此处自行跳转
    if (apiErr.isAuthError && (ownSession || original?.url === '/auth/refresh')) {
      markSessionExpired()
      tokenStore.clear()
    }

    return Promise.reject(apiErr)
  },
)
