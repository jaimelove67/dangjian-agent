import { http } from './http'
import type {
  AskQuestionRequest,
  AskQuestionResponse,
  HealthResponse,
  QAAttachmentMeta,
  QARecordListResponse,
  ReadyResponse,
  QASessionListResponse,
} from './types'

/** app/api/v1/qa.py */

export function askQuestion(payload: AskQuestionRequest): Promise<AskQuestionResponse> {
  return http.post('/qa', payload)
}

/**
 * 上传一份提问附件（app/api/v1/qa.py::POST /qa/attachments）。
 *
 * `cloudOcr` 是用户对"允许把图片/扫描件发到云端识别文字"的明确同意：后端默认拒绝，
 * 未同意时返回 428，界面据此弹确认框而不是当成普通失败。
 */
export function uploadQAAttachment(
  file: File,
  options: { cloudOcr?: boolean } = {},
): Promise<QAAttachmentMeta> {
  const data = new FormData()
  data.append('file', file)
  if (options.cloudOcr) data.append('cloud_ocr', 'true')
  return http.post('/qa/attachments', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    // 扫描件逐页识别较慢，给足时间，避免前端先超时而后端还在识别
    timeout: 180000,
  })
}

export function listQASessions(params: { page?: number; page_size?: number } = {}): Promise<QASessionListResponse> {
  return http.get('/qa/sessions', { params })
}

/** app/api/v1/qa.py::DELETE /qa/sessions/{session_record_id} —— 软删除本人记录 */
export function deleteQASession(sessionRecordId: string): Promise<{ id: string; deleted: boolean }> {
  return http.delete(`/qa/sessions/${encodeURIComponent(sessionRecordId)}`)
}

/** app/api/v1/qa.py::GET /qa/records —— 问答记录集中查看（需 admin.audit，T-SYS-06） */
export function listQaRecords(params: Record<string, string | number | boolean> = {}): Promise<QARecordListResponse> {
  return http.get('/qa/records', { params })
}

/** 导出问答记录台账（Excel，附导出说明；后端写审计） */
export function exportQaRecords(params: Record<string, string | number | boolean> = {}): Promise<Blob> {
  return http.get('/qa/records/export', { params, responseType: 'blob' })
}

/** app/api/v1/health.py */

export function checkHealth(): Promise<HealthResponse> {
  return http.get('/admin/health')
}

export function checkReady(): Promise<ReadyResponse> {
  return http.get('/admin/health/ready', { validateStatus: (status) => status === 200 || status === 503 })
}
