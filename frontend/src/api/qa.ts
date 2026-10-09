import { http } from './http'
import type { AskQuestionRequest, AskQuestionResponse, HealthResponse } from './types'

/** app/api/v1/qa.py */

export function askQuestion(payload: AskQuestionRequest): Promise<AskQuestionResponse> {
  return http.post('/qa', payload)
}

/** app/api/v1/health.py */

export function checkHealth(): Promise<HealthResponse> {
  return http.get('/health')
}

export function checkReady(): Promise<HealthResponse> {
  return http.get('/health/ready')
}
