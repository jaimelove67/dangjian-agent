import { http } from './http'
import type {
  AskQuestionRequest,
  AskQuestionResponse,
  HealthResponse,
  QASessionListResponse,
} from './types'

/** app/api/v1/qa.py */

export function askQuestion(payload: AskQuestionRequest): Promise<AskQuestionResponse> {
  return http.post('/qa', payload)
}

/** 分页查询当前用户的问答历史（时间倒序） */
export function listQASessions(page = 1, pageSize = 20): Promise<QASessionListResponse> {
  return http.get('/qa/sessions', { params: { page, page_size: pageSize } })
}

/** app/api/v1/health.py */

export function checkHealth(): Promise<HealthResponse> {
  return http.get('/health')
}

export function checkReady(): Promise<HealthResponse> {
  return http.get('/health/ready')
}
