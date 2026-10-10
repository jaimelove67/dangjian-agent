import { http } from './http'
import type {
  DocumentCreateResponse,
  DocumentResponse,
  DocumentStatusUpdate,
  DocumentUploadForm,
  DocStatus,
  DocumentListResponse,
} from './types'

/** app/api/v1/knowledge.py：列表、详情、创建和状态维护均为真实接口。 */
export function listDocuments(params: { page?: number; page_size?: number; q?: string; status?: string; level?: string }): Promise<DocumentListResponse> {
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

  return http.post('/knowledge-docs', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
