import { http } from './http'
import type {
  DocumentCreateResponse,
  DocumentResponse,
  DocumentStatusUpdate,
  DocumentUploadForm,
  DocStatus,
} from './types'

/**
 * app/api/v1/knowledge.py
 *
 * ⚠️ 后端仅提供三个接口：创建、按 doc_id 查询、改状态。
 *    **没有列表接口**（无 GET /knowledge-docs），因此列表页使用 mock
 *    数据源（见 ./mock.ts），并在界面上以「示例数据」徽标显式标注，
 *    避免把演示数据误当成真实库内容。
 */

export function getDocument(docId: string): Promise<DocumentResponse> {
  return http.get(`/knowledge-docs/${encodeURIComponent(docId)}`)
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
