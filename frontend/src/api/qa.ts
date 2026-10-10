import { http } from './http'
import type { AskQuestionRequest, AskQuestionResponse, HealthResponse, ReadyResponse, QASessionListResponse } from './types'

/** app/api/v1/qa.py */

export function askQuestion(payload: AskQuestionRequest): Promise<AskQuestionResponse> {
  return http.post('/qa', payload)
}

export function listQASessions(params: { page?: number; page_size?: number } = {}): Promise<QASessionListResponse> {
  return http.get('/qa/sessions', { params })
}

/** app/api/v1/health.py */

export function checkHealth(): Promise<HealthResponse> {
  return http.get('/health')
}

export function checkReady(): Promise<ReadyResponse> {
  return http.get('/health/ready', { validateStatus: (status) => status === 200 || status === 503 })
}
