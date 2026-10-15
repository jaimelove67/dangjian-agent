import { http } from './http'
import type {
  DocumentCreateResponse,
  DocumentResponse,
  DocReviewStatus,
  DocumentStatusUpdate,
  DocumentUploadForm,
  DocAuthority,
  DocStatus,
  DocValidity,
  DocumentListResponse,
} from './types'

/** app/api/v1/knowledge.py：列表、详情、创建和状态维护均为真实接口。 */
export function listDocuments(params: { page?: number; page_size?: number; q?: string; status?: string; level?: string; review_status?: DocReviewStatus; due_for_review?: boolean }): Promise<DocumentListResponse> {
  return http.get('/knowledge-docs', { params })
}

export function getDocument(docId: string): Promise<DocumentResponse> {
  return http.get(`/knowledge-docs/${encodeURIComponent(docId)}`)
}

export function deleteDocument(docId: string): Promise<DocumentResponse> {
  return http.delete(`/knowledge-docs/${encodeURIComponent(docId)}`)
}

export function replaceDocumentContent(doc: DocumentResponse, file: File): Promise<DocumentCreateResponse> {
  const data = new FormData()
  data.append('file', file)
  data.append('expected_revision', String(doc.content_revision ?? 1))
  return http.put(`/knowledge-docs/${encodeURIComponent(doc.doc_id)}/content`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function updateDocumentStatus(
  docId: string,
  status: DocStatus,
): Promise<void> {
  const payload: DocumentStatusUpdate = { status }
  return http.patch(`/knowledge-docs/${encodeURIComponent(docId)}/status`, payload)
}

/** 上传为 multipart/form-data，字段名与后端 Form(...) 声明逐一对齐 */
export function createDocument(form: DocumentUploadForm): Promise<DocumentCreateResponse> {
  const fd = new FormData()
  fd.append('file', form.file)
  fd.append('doc_id', form.doc_id)
  fd.append('file_name', form.file_name)
  fd.append('title', form.title)
  fd.append('issuer', form.issuer)
  fd.append('level', form.level)
  fd.append('visibility', form.visibility)
  fd.append('effective_date', form.effective_date)
  fd.append('security_level', form.security_level)
  fd.append('tags', form.tags)
  if (form.doc_number) fd.append('doc_number', form.doc_number)
  if (form.summary) fd.append('summary', form.summary)
  if (form.expiration_date) fd.append('expiration_date', form.expiration_date)
  if (form.status) fd.append('status', form.status)
  if (form.authority) fd.append('authority', form.authority)
  if (form.validity) fd.append('validity', form.validity)
  if (form.field_levels) fd.append('field_levels', form.field_levels)

  return http.post('/knowledge-docs', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 公共库内容审核发布：批准进入检索范围，退回须写明意见（T-KB-12）。 */
export function reviewDocument(
  docId: string,
  decision: 'approve' | 'reject',
  note?: string,
): Promise<DocumentResponse> {
  return http.post(`/knowledge-docs/${encodeURIComponent(docId)}/review`, { decision, note })
}

/** 登记供给复核确认：核对仍现行有效并重排下次复核日程（T-KB-13）。 */
export function confirmDocumentMaintenance(
  docId: string,
  note?: string,
): Promise<DocumentResponse> {
  return http.post(`/knowledge-docs/${encodeURIComponent(docId)}/maintenance`, { note })
}

export interface DocumentProcessing {
  doc_id: string
  status: 'pending' | 'partial' | 'ready' | 'failed' | 'no_chunks'
  total_chunks: number
  embedded_chunks: number
  pending_chunks: number
  error: string | null
  content_revision: number
  retry_endpoint: string | null
}

export interface DocumentMetadataInput {
  title: string
  issuer: string
  doc_number: string | null
  level: DocumentResponse['level']
  visibility: DocumentResponse['visibility']
  security_level: DocumentResponse['security_level']
  effective_date: string
  expiration_date: string | null
  tags: string
  summary: string | null
  /** T-DATA-05：权威来源与效力状态可校正，语义见 app/core/constants.py */
  authority?: DocAuthority
  validity?: DocValidity
  /** 字段级敏感等级；null 表示清除标注 */
  field_levels?: Record<string, string> | null
  reason: string
}

export function getProcessingStatus(docId: string): Promise<DocumentProcessing> {
  return http.get(`/knowledge-docs/${encodeURIComponent(docId)}/processing-status`)
}

export function processDocument(docId: string): Promise<{ embedded_count: number }> {
  return http.post('/embeddings/embed', { doc_id: docId, force_update: false })
}

export function updateDocumentMetadata(docId: string, input: DocumentMetadataInput): Promise<DocumentResponse> {
  return http.patch(`/knowledge-docs/${encodeURIComponent(docId)}/metadata`, input)
}

export function getOriginalFile(docId: string, revision: number): Promise<Blob> {
  return http.get(`/knowledge-docs/${encodeURIComponent(docId)}/file`, { params: { revision }, responseType: 'blob' })
}
