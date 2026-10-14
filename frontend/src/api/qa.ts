import { http } from './http'
import type { AskQuestionRequest, AskQuestionResponse, HealthResponse, ReadyResponse, QASessionListResponse } from './types'

/** app/api/v1/qa.py */

export function askQuestion(payload: AskQuestionRequest): Promise<AskQuestionResponse> {
  return http.post('/qa', payload)
}

export function listQASessions(params: { page?: number; page_size?: number } = {}): Promise<QASessionListResponse> {
  return http.get('/qa/sessions', { params })
}

/** app/api/v1/qa.py::DELETE /qa/sessions/{session_record_id} —— 软删除本人记录 */
export function deleteQASession(sessionRecordId: string): Promise<{ id: string; deleted: boolean }> {
  return http.delete(`/qa/sessions/${encodeURIComponent(sessionRecordId)}`)
}

/** app/api/v1/health.py */

export function checkHealth(): Promise<HealthResponse> {
  return http.get('/admin/health')
}

export function checkReady(): Promise<ReadyResponse> {
  return http.get('/admin/health/ready', { validateStatus: (status) => status === 200 || status === 503 })
}
