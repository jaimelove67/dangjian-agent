import { http } from './http'
import type {
  DocumentCreateResponse,
  DocumentListResponse,
  DocumentResponse,
  DocumentStatusUpdate,
  DocumentUploadForm,
  DocStatus,
} from './types'

/**
 * app/api/v1/knowledge.py
 *
 * 后端接口：创建（multipart）、按 doc_id 查询、改状态、分页列表、软删除。
 * 列表与删除已接入真实接口，不再使用示例数据源。
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

/** 列表查询参数（与后端 Query 参数逐一对齐） */
export interface KnowledgeListParams {
  page?: number
  page_size?: number
  /** effective / expired / abolished，空或省略表示全部 */
  status?: DocStatus | ''
  keyword?: string
}

/** 分页查询知识库文件列表 */
export function listKnowledgeDocuments(
  params: KnowledgeListParams = {},
): Promise<DocumentListResponse> {
  const clean: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') clean[k] = v
  }
  return http.get('/knowledge-docs', { params: clean })
}

/** 软删除知识库文件，返回删除后的文档（状态标记为已废止） */
export function deleteKnowledgeDocument(docId: string): Promise<DocumentResponse> {
  return http.delete(`/knowledge-docs/${encodeURIComponent(docId)}`)
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
